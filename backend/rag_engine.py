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
            temperature=0.3,   # 较低温度，保证回答基于参考知识，减少"创作"
            num_ctx=4096,      # 上下文窗口大小（token 数）
            timeout=120,       # 超时 120 秒，大模型推理可能较慢
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

    def _trim_context(self, context: str, max_tokens: int = 2000) -> str:
        """
        裁剪上下文文本，防止超出 LLM 的 prompt 长度限制。

        裁剪策略：
          按双换行分割成段落，贪心地从头累积，
          直到预估字节数超过 max_tokens * 3 为止（中文字符约 3 字节）。

        Args:
            context:    拼接的参考知识文本
            max_tokens: 允许的最大 token 数（粗略估算）

        Returns:
            裁剪后的上下文文本
        """
        parts = context.split(chr(10) + chr(10))  # 按空行分段
        kept = []
        total = 0
        for part in parts:
            estimated = len(part.encode("utf-8"))
            if total + estimated > max_tokens * 3:  # 超出限制则停止累积
                break
            kept.append(part)
            total += estimated
        # 若全部段落都超限，至少保留第一段的截断版本
        return (chr(10) + chr(10)).join(kept) if kept else (parts[0][:max_tokens * 3] if parts else "")

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

        # ── 第三步：构建参考上下文和来源信息 ────────────────────────
        context_parts = []
        sources = []
        for i, doc in enumerate(reranked_docs):
            context_parts.append(doc.page_content)
            source_info = doc.metadata.get("source", "unknown")
            sources.append({
                "index":  i + 1,
                "source": source_info,
                # 优先使用 rerank_score，若无则降级使用向量相似度
                "score":  round(doc.metadata.get("rerank_score", doc.metadata.get("similarity_score", 0)), 4),
            })

        context = (chr(10) + chr(10)).join(context_parts)
        context = self._trim_context(context, max_tokens=2000)  # 裁剪防止超限

        # ── 第四步：构建 Prompt ─────────────────────────────────────
        prompt_template = (
            "你是一个智能客服助手。请根据以下参考知识回答用户的问题。\n"
            "要求：\n"
            "1. 如果参考知识中有相关信息，请基于参考内容回答问题\n"
            "2. 如果参考知识中没有相关信息，请如实告知用户无法回答\n"
            "3. 回答要专业、简洁、有条理\n\n"
            "参考知识：\n{context}\n\n"
            "用户问题：{question}\n\n"
            "请回答："
        )
        system_prompt = prompt_template.format(context=context, question=question)

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
            answer = self.llm.invoke(system_prompt)
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
    
    def answer_with_docs(self, question: str, documents: List[Document], chat_history: Optional[List[tuple]] = None) -> dict:
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
        
        # 构建上下文和来源
        context_parts = []
        sources = []
        for i, doc in enumerate(reranked_docs):
            context_parts.append(doc.page_content)
            source_info = doc.metadata.get("source", "unknown")
            sources.append({
                "index":  i + 1,
                "source": source_info,
                "score":  round(doc.metadata.get("rerank_score", doc.metadata.get("similarity_score", 0)), 4),
            })
        
        context = (chr(10) + chr(10)).join(context_parts)
        context = self._trim_context(context, max_tokens=2000)
        
        # 构建 Prompt
        prompt_template = (
            "你是一个智能客服助手。请根据以下参考知识回答用户的问题。\n"
            "要求：\n"
            "1. 如果参考知识中有相关信息，请基于参考内容回答问题\n"
            "2. 如果参考知识中没有相关信息，请如实告知用户无法回答\n"
            "3. 回答要专业、简洁、有条理\n\n"
            "参考知识：\n{context}\n\n"
            "用户问题：{question}\n\n"
            "请回答："
        )
        system_prompt = prompt_template.format(context=context, question=question)
        
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
            answer = self.llm.invoke(system_prompt)
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

    def stream_answer_with_docs(self, question: str, documents: List[Document], chat_history: Optional[List[tuple]] = None):
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

        # 构建上下文和来源
        context_parts = []
        sources = []
        for i, doc in enumerate(reranked_docs):
            context_parts.append(doc.page_content)
            source_info = doc.metadata.get("source", "unknown")
            sources.append({
                "index":  i + 1,
                "source": source_info,
                "score":  round(doc.metadata.get("rerank_score", doc.metadata.get("similarity_score", 0)), 4),
            })

        context = (chr(10) + chr(10)).join(context_parts)
        context = self._trim_context(context, max_tokens=2000)

        # 构建 Prompt（与 answer_with_docs 完全一致）
        prompt_template = (
            "你是一个智能客服助手。请根据以下参考知识回答用户的问题。\n"
            "要求：\n"
            "1. 如果参考知识中有相关信息，请基于参考内容回答问题\n"
            "2. 如果参考知识中没有相关信息，请如实告知用户无法回答\n"
            "3. 回答要专业、简洁、有条理\n\n"
            "参考知识：\n{context}\n\n"
            "用户问题：{question}\n\n"
            "请回答："
        )
        system_prompt = prompt_template.format(context=context, question=question)

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
            with httpx.Client(transport=httpx.HTTPTransport(), timeout=120) as client:
                with client.stream(
                    "POST",
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model":  CHAT_MODEL,
                        "prompt": system_prompt,
                        "stream": True,
                        "options": {
                            "temperature": 0.3,
                            "num_ctx":     4096,
                        },
                    },
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            chunk = _json.loads(line)
                        except Exception:
                            continue
                        token = chunk.get("response", "")
                        if token:
                            full_answer.append(token)
                            yield {"token": token}
                        if chunk.get("done"):
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
