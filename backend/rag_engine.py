"""
智能客服系统 - RAG 引擎（Retrieval-Augmented Generation）

作者: kimikang

RAG 完整链路：
  用户问题
    → 向量检索（VectorStoreManager.search）：召回 TOP_K 个相关文档块
    → Rerank 精排（Ollama /api/rerank）：从召回结果中保留 RERANK_TOP_K 个
    → 上下文裁剪（_trim_context）：防止 prompt 超出 LLM 上下文窗口
    → LLM 生成（OllamaLLM.invoke）：基于参考知识生成最终回答

代理绕过说明：
  所有 Ollama HTTP 请求均使用 httpx.HTTPTransport() 显式传入，
  绕过 Windows 系统代理（httpx 0.28+ 默认读取系统代理会导致 502）。
"""
from typing import List, Optional

import httpx
from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_core.documents import Document

from config import (
    CHAT_MODEL, EMBED_MODEL, RERANK_MODEL,
    TOP_K, RERANK_TOP_K, OLLAMA_BASE_URL,
)
from vector_store import VectorStoreManager


def _maybe_no_think(prompt: str) -> str:
    """如果 config.THINKING 为 False，在 prompt 前加 /no_think 指令禁用思考模式"""
    try:
        from config import THINKING
        if not THINKING:
            return "/no_think\n" + prompt
    except Exception:
        pass
    return prompt


def _build_context(docs: List[Document], char_limit: int = None):
    """
    从文档列表构建 context 字符串和 sources 列表。
    char_limit 默认从 config.CONTEXT_LIMIT 读取。
    """
    from config import CONTEXT_LIMIT
    if char_limit is None:
        char_limit = CONTEXT_LIMIT
    context_parts = []
    sources = []
    total_chars = 0

    for i, doc in enumerate(docs):
        content = doc.page_content
        if total_chars + len(content) > char_limit:
            continue  # 超限跳过，不中断（后面可能有更短的 chunk）
        context_parts.append(content)
        total_chars += len(content)
        source_info = doc.metadata.get("source", "unknown")
        sources.append({
            "index":  i + 1,
            "source": source_info,
            "score":  round(doc.metadata.get("rerank_score", doc.metadata.get("similarity_score", 0)), 4),
        })

    context = "\n\n".join(context_parts)
    print(f"[RAG] 最终上下文: {len(sources)} 个chunk, {total_chars} 字符")
    return context, sources


def _build_rag_prompt(context: str, question: str) -> str:
    """
    构建 RAG prompt，针对列举型问题强调完整输出。
    
    列举型关键词：有哪些、列出、所有、清单、包括、全部
    """
    is_list_question = any(kw in question for kw in ["有哪些", "列出", "所有", "清单", "包括", "全部", "列表"])
    
    if is_list_question:
        instructions = (
            "1. 如果参考知识中有相关信息，请完整列出参考内容中的所有项目，不要省略任何条目\n"
            "2. 如果参考知识只包含部分条目，请列出所有已提供的条目，并在末尾注明完整清单请以官方文件为准\n"
            "3. 如果参考知识中没有相关信息，请如实告知用户无法回答\n"
            "4. 回答要结构清晰，保留表格格式\n\n"
        )
    else:
        instructions = (
            "1. 如果参考知识中有相关信息，请基于参考内容回答问题\n"
            "2. 如果参考知识中没有相关信息，请如实告知用户无法回答\n"
            "3. 回答要专业、准确、有条理\n\n"
        )
    
    return (
        "你是一个智能客服助手。请根据以下参考知识回答用户的问题。\n"
        "要求：\n"
        f"{instructions}"
        f"参考知识：\n{context}\n\n"
        f"用户问题：{question}\n\n"
        "请回答："
    )


class RagEngine:
    """
    RAG 引擎：封装向量检索 → Rerank → LLM 生成的完整链路。

    每次 app.py 调用 get_rag_engine() 时懒加载单例实例。
    更换模型时，app.py 会将全局实例置为 None，下次请求时重新初始化。
    """

    def __init__(self, collection_name: str = "knowledge_base"):
        # 向量库管理器（读取 VECTOR_DB_PATH 目录的 ChromaDB 数据）
        self.vector_store = VectorStoreManager()
        self.collection_name = collection_name

        # 嵌入模型：与向量库索引时使用的模型必须一致，维度不同会报错
        # 注意：不传 http_client，由 config 层的 NO_PROXY 环境变量控制代理绕过
        self.embeddings = OllamaEmbeddings(
            model=EMBED_MODEL,
            base_url=OLLAMA_BASE_URL,
        )

        # 对话模型：用于最终回答生成
        self.llm = OllamaLLM(
            model=CHAT_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.3,
            num_ctx=131072,
            timeout=300,       # 超时 300 秒，大上下文推理需要更长时间
        )

    def _rerank_documents(self, query: str, documents: List[Document], top_k: int) -> List[Document]:
        """
        调用 Ollama Rerank 接口对召回文档进行精排，返回得分最高的 top_k 个。

        Rerank 原理：
          交叉编码器（Cross-Encoder）同时处理 query 和 document，
          比向量相似度更准确，但计算成本更高，因此只在召回后精排。

        降级策略：
          若 Rerank API 调用失败（网络问题、模型未加载等），
          自动降级为按向量相似度分数排序，保证可用性。

        Args:
            query:     用户问题
            documents: 向量检索召回的文档列表
            top_k:     精排后保留的文档数

        Returns:
            精排后的 Document 列表，每个 doc 的 metadata 中附加 rerank_score
        """
        if not documents:
            return documents

        payload = {
            "model": RERANK_MODEL,
            "query": query,
            "documents": [doc.page_content for doc in documents],
            "top_n": top_k,
        }

        try:
            # 使用显式 HTTPTransport 绕过系统代理
            with httpx.Client(transport=httpx.HTTPTransport()) as client:
                response = client.post(
                    f"{OLLAMA_BASE_URL}/api/rerank",
                    json=payload,
                    timeout=30.0,
                )
            response.raise_for_status()
            result = response.json()

            # 按 score 降序排列，取前 top_k 个
            ranked_items = sorted(result, key=lambda x: x.get("score", 0), reverse=True)
            reranked_docs = []
            for item in ranked_items[:top_k]:
                idx = item.get("index", 0)
                if 0 <= idx < len(documents):
                    doc = documents[idx]
                    doc.metadata["rerank_score"] = item.get("score", 0)
                    reranked_docs.append(doc)
            return reranked_docs

        except Exception:
            # Rerank 失败时降级：按向量相似度排序
            scored = sorted(documents, key=lambda d: d.metadata.get("similarity_score", 0), reverse=True)
            return scored[:top_k]

    def _expand_by_title(self, reranked: List[Document], all_docs: List[Document], top_k: int,
                          collection_names: List[str] = None, question: str = "") -> List[Document]:
        """
        对 rerank 结果做标题路径扩展：
        若某个 chunk 以 [标题路径] 开头进入了 top_k，
        则直接从向量库里查出同一标题路径的所有 chunk 追加进来，
        保证列表型/表格型章节能完整召回。

        collection_names: 要搜索的集合列表，默认用 self.collection_name
        """
        import re as _re

        def _title(text: str) -> str:
            """提取 chunk 开头的 [标题路径] 部分，没有则返回空串"""
            m = _re.match(r'^\[([^\]]+)\]', text.strip())
            return m.group(1) if m else ""

        # 从原始召回（all_docs）中取所有出现的标题
        all_titles = set()
        for doc in all_docs + reranked:
            t = _title(doc.page_content)
            if t:
                all_titles.add(t)

        # 标题匹配策略：
        # 1. 标题直接出现在问题里 → 精确命中
        # 2. 问题直接出现在标题里 → 精确命中（如「国内特药」在「国内特药药品清单」里）
        # 3. 上述都失败 → 用向量相似度最高的 chunk 的标题（fallback）
        hit_titles = set()
        if question:
            for t in all_titles:
                if t in question or question in t:
                    hit_titles.add(t)
                    continue
                # 提取标题的核心词（去掉「药品清单」「清单」等通用后缀），看核心词是否在问题里
                core = t.replace('药品清单', '').replace('清单', '').replace('列表', '').strip()
                if core and core in question:
                    hit_titles.add(t)

        # 如果精确匹配没找到，降级到全部标题（交给 char_limit 控制总量）
        if not hit_titles:
            hit_titles = all_titles

        print(f"[RAG] _expand_by_title hit_titles: {hit_titles}")

        if not hit_titles:
            return reranked

        # 已在 reranked 中的 chunk（用 page_content 前64字符作为标识）
        seen = {doc.page_content[:64] for doc in reranked}

        # 先从 all_docs（已召回的）里找
        extra = []
        for doc in all_docs:
            key = doc.page_content[:64]
            if key in seen:
                continue
            if _title(doc.page_content) in hit_titles:
                extra.append(doc)
                seen.add(key)

        # 再从向量库里按标题前缀查，支持多 collection
        # 再从向量库里按标题前缀查，支持多 collection
        # 按各标题在召回结果中的最高相似度排序，高分标题给更多配额
        from collections import defaultdict
        title_max_sim = defaultdict(float)
        for doc in reranked:
            t = _title(doc.page_content)
            if t:
                sim = doc.metadata.get("similarity_score", 0)
                if sim > title_max_sim[t]:
                    title_max_sim[t] = sim

        # 按相似度降序排列标题，相似度高的标题优先扩展更多 chunk
        sorted_titles = sorted(hit_titles, key=lambda t: title_max_sim.get(t, 0), reverse=True)

        cols_to_search = collection_names if collection_names else [self.collection_name]
        try:
            for col_name in cols_to_search:
                col = self.vector_store._get_or_create_collection(col_name)
                if col.count() == 0:
                    continue
                all_in_col = col.get(include=["documents", "metadatas"])
                all_col_docs = all_in_col.get("documents", [])
                print(f"[RAG] _expand_by_title scanning {col_name}: {len(all_col_docs)} docs")

                # 按标题分组收集候选
                title_candidates = defaultdict(list)
                for doc_text, meta in zip(all_col_docs, all_in_col.get("metadatas", [])):
                    key = doc_text[:64]
                    if key in seen:
                        continue
                    for t in hit_titles:
                        if doc_text.strip().startswith(f"[{t}]"):
                            title_candidates[t].append((doc_text, meta))
                            break

                # 按标题相似度排序依次加入：相似度最高的标题不限量，其余标题最多 2 个 chunk
                for rank, t in enumerate(sorted_titles):
                    max_per_title = None if rank == 0 else 2
                    for count, (doc_text, meta) in enumerate(title_candidates[t]):
                        if max_per_title is not None and count >= max_per_title:
                            break
                        key = doc_text[:64]
                        if key not in seen:
                            extra.append(Document(page_content=doc_text, metadata=meta or {}))
                            seen.add(key)

        except Exception as e:
            print(f"[RAG] _expand_by_title 向量库查询失败: {e}")

        result_docs = reranked + extra
        print(f"[RAG] _expand_by_title: reranked={len(reranked)}, extra={len(extra)}, total={len(result_docs)}, titles={hit_titles}")
        return result_docs

    def _trim_context(self, context: str, max_tokens: int = 2000) -> str:
        """
        裁剪上下文文本，防止超出 LLM 的 prompt 长度限制。

        裁剪策略：
          按双换行分割成段落，贪心地从头累积，
          直到字符数超过 max_tokens * 2 为止（粗略：1 token ≈ 1.5~2 中文字符）。

        Args:
            context:    拼接的参考知识文本
            max_tokens: 允许的最大 token 数（粗略估算）

        Returns:
            裁剪后的上下文文本
        """
        limit = max_tokens * 2  # 字符数上限（比字节数更宽松，适合中文）
        parts = context.split(chr(10) + chr(10))  # 按空行分段
        kept = []
        total = 0
        for part in parts:
            part_len = len(part)
            if total + part_len > limit:
                break
            kept.append(part)
            total += part_len
        # 若全部段落都超限，至少保留第一段的截断版本
        return (chr(10) + chr(10)).join(kept) if kept else (parts[0][:limit] if parts else "")

    def retrieve_and_answer(self, question: str, chat_history: Optional[List[tuple]] = None) -> dict:
        """
        RAG 完整链路：根据用户问题检索知识库并生成回答。

        流程：
          1. 向量检索：从当前知识库 ChromaDB collection 召回 TOP_K 个相关块
          2. Rerank 精排：保留 RERANK_TOP_K 个最相关块
          3. 构建 prompt：将参考知识 + 历史对话 + 用户问题组合成完整 prompt
          4. LLM 生成：调用 Ollama 生成回答

        Args:
            question:     用户当前问题
            chat_history: 历史对话列表，格式为 [("user"/"assistant", "内容"), ...]
                          最多使用最近 6 条（3 轮对话），避免 prompt 过长

        Returns:
            {
              "answer":       str,   # LLM 生成的回答
              "sources":      list,  # 引用来源列表，含 index/source/score
              "has_knowledge": bool  # 是否找到相关知识（False 时为兜底回答）
            }
        """
        # ── 第一步：向量检索 ────────────────────────────────────────
        relevant_docs = self.vector_store.search(question, collection_name=self.collection_name, top_k=TOP_K)

        if not relevant_docs:
            # 知识库为空或无相关内容，返回兜底回答
            return {
                "answer": "抱歉，知识库中暂无相关内容。请先上传文档到知识库。",
                "sources": [],
                "has_knowledge": False,
            }

        # ── 第二步：Rerank 精排 ─────────────────────────────────────
        reranked_docs = self._rerank_documents(question, relevant_docs, top_k=RERANK_TOP_K)
        reranked_docs = self._expand_by_title(reranked_docs, relevant_docs, top_k=RERANK_TOP_K,
                                               question=question)

        # ── 第三步：构建参考上下文和来源信息
        context, sources = _build_context(reranked_docs)
        print(f"[RAG] retrieve_and_answer 最终上下文: {len(sources)} 个chunk")

        # ── 第四步：构建 Prompt ─────────────────────────────────────
        system_prompt = _build_rag_prompt(context, question)

        # 若有历史对话，将最近 6 条（3 轮）拼接到 prompt 前部
        if chat_history:
            history_lines = []
            for h in chat_history[-6:]:
                role = "用户" if h[0] else "客服"
                history_lines.append(f"{role}: {h[1]}")
            history_str = chr(10).join(history_lines)
            system_prompt = "之前的对话记录：\n" + history_str + "\n\n" + system_prompt

        # ── 第五步：LLM 生成回答 ────────────────────────────────────
        try:
            answer = self.llm.invoke(_maybe_no_think(system_prompt))
            return {
                "answer":        answer.strip(),
                "sources":       sources,
                "has_knowledge": True,
            }
        except Exception as e:
            error_msg = str(e)
            # 网关超时（大模型加载慢或显存不足时常见）
            if "502" in error_msg or "Gateway" in error_msg:
                return {
                    "answer":        "模型响应超时，请稍后重试。建议检查 Ollama 是否正常运行。",
                    "sources":       sources,
                    "has_knowledge": True,
                }
            return {
                "answer":        f"模型调用失败: {error_msg}",
                "sources":       sources,
                "has_knowledge": True,
            }

    def ingest_document(self, filename: str, chunks: List[str]):
        """
        将文档分块批量写入当前知识库的向量库。

        每个块的 metadata 中记录来源文件名（source），
        便于后续按文件删除对应的向量数据。

        Args:
            filename: .md 文件名，作为向量块的 source 标识
            chunks:   文档分块列表（由 document_processor.chunk_texts 生成）
        """
        # 为每个块添加来源标记
        metadatas = [{"source": filename} for _ in chunks]
        self.vector_store.add_documents(
            self.collection_name,
            chunks,
            metadatas=metadatas,
        )

    def delete_document(self, filename: str) -> int:
        """
        从当前知识库的向量库中删除指定文档的所有分块。

        通过 metadata.source == filename 匹配并删除对应向量数据。

        Args:
            filename: 要删除的 .md 文件名（与入库时的 source 标识一致）
            
        Returns:
            实际删除的向量块数量
        """
        return self.vector_store.delete_by_source(filename, self.collection_name)
    
    def answer_with_docs(self, question: str, documents: List[Document], chat_history: Optional[List[tuple]] = None,
                          collection_names: List[str] = None) -> dict:
        """
        基于已提供的文档列表生成回答（用于跨知识库检索）。
        
        不执行向量检索，直接对提供的文档进行 Rerank + LLM 生成。
        
        Args:
            question:     用户问题
            documents:    已检索的文档列表（可能来自多个知识库）
            chat_history: 历史对话列表
            
        Returns:
            {
              "answer":       str,
              "sources":      list,
              "has_knowledge": bool
            }
        """
        if not documents:
            return {
                "answer": "抱歉，知识库中暂无相关内容。",
                "sources": [],
                "has_knowledge": False,
            }
        
        # Rerank 精排
        reranked_docs = self._rerank_documents(question, documents, top_k=RERANK_TOP_K)
        reranked_docs = self._expand_by_title(reranked_docs, documents, top_k=RERANK_TOP_K,
                                               collection_names=collection_names,
                                               question=question)
        
        # 构建上下文和来源
        context, sources = _build_context(reranked_docs)
        
        # 构建 Prompt
        system_prompt = _build_rag_prompt(context, question)
        
        # 添加历史对话
        if chat_history:
            history_lines = []
            for h in chat_history[-6:]:
                role = "用户" if h[0] else "客服"
                history_lines.append(f"{role}: {h[1]}")
            history_str = chr(10).join(history_lines)
            system_prompt = "之前的对话记录：\n" + history_str + "\n\n" + system_prompt
        
        # LLM 生成
        try:
            answer = self.llm.invoke(_maybe_no_think(system_prompt))
            return {
                "answer":        answer.strip(),
                "sources":       sources,
                "has_knowledge": True,
            }
        except Exception as e:
            error_msg = str(e)
            if "502" in error_msg or "Gateway" in error_msg:
                return {
                    "answer":        "模型响应超时，请稍后重试。",
                    "sources":       sources,
                    "has_knowledge": True,
                }
            return {
                "answer":        f"模型调用失败: {error_msg}",
                "sources":       sources,
                "has_knowledge": True,
            }

    def stream_answer_with_docs(self, question: str, documents: List[Document], chat_history: Optional[List[tuple]] = None,
                                 collection_names: List[str] = None):
        """
        流式生成回答（SSE 版）。
        直接调用 Ollama /api/generate 流式接口，绕过 LangChain 缓冲问题。

        Yields:
            dict — 每个 token：{"token": "..."}
            dict — 完成信号：{"done": True, "sources": [...], "has_knowledge": bool, "answer": str}
            dict — 错误信号：{"error": "..."}
        """
        import json as _json

        if not documents:
            yield {"done": True, "sources": [], "has_knowledge": False,
                   "answer": "抱歉，知识库中暂无相关内容。"}
            return

        # Rerank 精排
        reranked_docs = self._rerank_documents(question, documents, top_k=RERANK_TOP_K)
        print(f"[RAG] rerank后: {len(reranked_docs)} 个chunk")
        for i, d in enumerate(reranked_docs):
            import re as _re2
            m = _re2.match(r'^\[([^\]]+)\]', d.page_content.strip())
            title = m.group(1) if m else "(无标题)"
            print(f"  [{i}] title={title!r:.40} chars={len(d.page_content)}")
        reranked_docs = self._expand_by_title(reranked_docs, documents, top_k=RERANK_TOP_K,
                                               collection_names=collection_names,
                                               question=question)
        print(f"[RAG] 扩展后: {len(reranked_docs)} 个chunk")

        # 构建上下文和来源
        context, sources = _build_context(reranked_docs)
        print(f"[RAG] stream 最终上下文: {len(sources)} 个chunk")

        # 构建 Prompt（与 answer_with_docs 完全一致）
        system_prompt = _build_rag_prompt(context, question)

        if chat_history:
            history_lines = []
            for h in chat_history[-6:]:
                role = "用户" if h[0] else "客服"
                history_lines.append(f"{role}: {h[1]}")
            history_str = chr(10).join(history_lines)
            system_prompt = "之前的对话记录：\n" + history_str + "\n\n" + system_prompt

        # 直接调用 Ollama /api/generate 流式接口（绕过 LangChain 缓冲）
        full_answer = []
        try:
            import config as _cfg
            from config import THINKING
            with httpx.Client(transport=httpx.HTTPTransport(), timeout=300) as client:
                with client.stream(
                    "POST",
                    f"{_cfg.OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model":  _cfg.CHAT_MODEL,
                        "prompt": system_prompt,
                        "stream": True,
                        "options": {
                            "temperature": 0.3,
                            "num_ctx":     131072,
                        },
                        "think": THINKING,
                    },
                ) as resp:
                    resp.raise_for_status()
                    token_count = 0
                    raw_count = 0
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            chunk = _json.loads(line)
                        except Exception:
                            continue
                        raw_count += 1
                        if raw_count <= 3:  # 打印前3个chunk看结构
                            print(f"[RAG] raw chunk[{raw_count}]: {str(chunk)[:150]}")
                        if not line:
                            continue
                        try:
                            chunk = _json.loads(line)
                        except Exception:
                            continue
                        token = chunk.get("response", "")
                        if token:
                            full_answer.append(token)
                            token_count += 1
                            yield {"token": token}
                        if chunk.get("done"):
                            print(f"[RAG] stream done, total_tokens={token_count}, answer_len={len(''.join(full_answer))}")
                            # 调试：打印原始chunk内容
                            if token_count == 0:
                                print(f"[RAG] done chunk keys: {list(chunk.keys())}, sample: {str(chunk)[:200]}")
                            break

            yield {
                "done":          True,
                "sources":       sources,
                "has_knowledge": True,
                "answer":        "".join(full_answer).strip(),
            }
        except Exception as e:
            error_msg = str(e)
            msg = "模型响应超时，请稍后重试。" if ("502" in error_msg or "Gateway" in error_msg) else f"模型调用失败: {error_msg}"
            yield {"error": msg, "sources": sources}
