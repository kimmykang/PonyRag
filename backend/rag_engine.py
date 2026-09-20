"""
智能客服系统 - RAG 引擎（Retrieval-Augmented Generation）

作者: kimikang

RAG 完整链路：
  用户问题
    → 向量检索（VectorStoreManager.search）：召回 TOP_K 个相关文档块
    → Rerank 精排（_rerank_documents）：根据 RERANK_METHOD 选择精排方式，保留 RERANK_TOP_K 个
        - cross_encoder：本地 HuggingFace CrossEncoder（默认，GPU 加速，精度最高）
        - listwise：用 CHAT_MODEL 做 Listwise 批量排序
        - ollama：通过 Ollama API 推理（embed 或 generate+logprob，兼容旧逻辑）
    → 标题扩展（_expand_by_title）：补全同标题路径下的所有 chunk
    → 上下文裁剪（_build_context）：防止 prompt 超出 LLM 上下文窗口
    → LLM 生成（OllamaLLM.invoke）：基于参考知识生成最终回答

代理绕过说明：
  所有 Ollama HTTP 请求均使用 httpx.HTTPTransport() 显式传入，
  绕过 Windows 系统代理（httpx 0.28+ 默认读取系统代理会导致 502）。
"""
from typing import List, Optional

import threading
import httpx
from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_core.documents import Document

from config import (
    CHAT_MODEL, EMBED_MODEL, RERANK_MODEL,
    TOP_K, RERANK_TOP_K, OLLAMA_BASE_URL,
    RERANK_METHOD, CROSS_ENCODER_MODEL, CROSS_ENCODER_DEVICE,
    OLLAMA_KEEP_ALIVE, NUM_CTX,
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


def rewrite_query(question: str, chat_history: list = None) -> str:
    """
    问题改写（Query Rewrite）：结合对话历史把省略指代的问题补全为独立完整的查询。

    场景示例：
      历史：Q: 某某的ABC计划的区别
      当前：大概保费是多少
      改写：某某的ABC计划的大概保费分别是多少

    策略：
      - 无历史对话，或历史只有1条，直接返回原问题（无需改写）
      - 优先使用 REWRITE_MODEL（轻量模型），未配置则使用 CHAT_MODEL
      - 失败则降级返回原问题

    Args:
        question:     当前用户问题
        chat_history: 历史对话列表，格式 [["user"/"assistant", "内容"], ...]

    Returns:
        改写后的完整问题字符串
    """
    # 无历史或只有一轮，当前问题已经是完整的
    if not chat_history or len(chat_history) < 2:
        print(f"[QueryRewrite] 跳过（历史条数={len(chat_history) if chat_history else 0}）: '{question}'")
        return question

    try:
        from config import CHAT_MODEL, OLLAMA_BASE_URL, THINKING
        import config as _cfg

        # 优先用轻量改写模型，没有则用对话模型
        rewrite_model = getattr(_cfg, "REWRITE_MODEL", "") or CHAT_MODEL

        # 只取最近 4 条（2轮），足够理解指代，不引入过多噪音
        recent = chat_history[-4:]
        history_lines = []
        for h in recent:
            role = "用户" if h[0] in ("user", True, "用户") else "客服"
            history_lines.append(f"{role}: {h[1]}")
        history_str = "\n".join(history_lines)

        prompt = (
            "/no_think\n"
            "你的任务是【问题改写】，不是回答问题。\n\n"
            "根据以下对话历史，将最后的用户问题改写为一个独立、完整的问题。\n"
            "严格要求：\n"
            "1. 只输出改写后的问题本身，不得回答问题内容\n"
            "2. 不得输出任何解释、分析、列表或正文内容\n"
            "3. 补全省略的主语、宾语、指代词（如「它」「这个」「哪个」「分别」等）\n"
            "4. 保持原意不变，不要添加任何假设或推断\n"
            "5. 如果当前问题已经完整独立，原样返回\n"
            "6. 输出必须是一句话的问题，以「？」或「?」结尾\n\n"
            f"对话历史：\n{history_str}\n\n"
            f"当前问题：{question}\n\n"
            "改写后的问题（只输出一句话）："
        )

        with httpx.Client(transport=httpx.HTTPTransport(), timeout=120) as client:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": rewrite_model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "think": THINKING,
                    # num_ctx 与 answer_with_docs / stream_answer_with_docs 保持一致
                    # Ollama 对同一模型不同 num_ctx 会触发完整卸载重载，导致显存抖动
                    # REWRITE_MODEL 与 CHAT_MODEL 相同时尤其重要
                    "options": {"temperature": 0, "num_ctx": NUM_CTX},
                },
            )
            resp.raise_for_status()
            rewritten = resp.json().get("response", "").strip()

        # 改写结果为空则降级（LLM 没有输出任何内容）
        if not rewritten:
            print(f"[QueryRewrite] LLM 返回空内容，使用原问题: '{question}'")
            return question

        # 过度扩写检测：改写结果不应远长于原问题，也不应含 markdown 标记
        # 典型场景：LLM 把改写任务当成问答任务，直接输出了回答内容
        _is_overwritten = (
            len(rewritten) > max(len(question) * 3, 150)   # 超过原问题3倍且绝对超过150字
            or "\n" in rewritten                            # 包含换行（说明输出了多行内容）
            or rewritten.startswith("**")                   # markdown 加粗开头
            or "* **" in rewritten                          # markdown 列表
        )
        if _is_overwritten:
            print(f"[QueryRewrite] 检测到过度扩写（{len(rewritten)}字），降级使用原问题: '{question}'")
            return question

        if rewritten == question:
            print(f"[QueryRewrite] 问题已完整，无需改写: '{question}'")
        else:
            print(f"[QueryRewrite] '{question}' → '{rewritten}'")
        return rewritten

    except Exception as e:
        print(f"[QueryRewrite] 改写失败，使用原问题: {e}")
        return question


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
        remaining = char_limit - total_chars

        if len(content) <= remaining:
            # 完整加入
            context_parts.append(content)
            total_chars += len(content)
            source_info = doc.metadata.get("source", "unknown")
            sources.append({
                "index":  i + 1,
                "source": source_info,
                "score":  round(doc.metadata.get("rerank_score", doc.metadata.get("similarity_score", 0)), 4),
            })
        else:
            # 超限：截断填充剩余空间后停止，不再尝试后续 chunk
            # 避免高分大 chunk 被跳过、低分小 chunk 反而进入上下文的问题
            from config import CONTEXT_TRUNCATE_MIN
            if remaining >= CONTEXT_TRUNCATE_MIN:
                context_parts.append(content[:remaining])
                total_chars += remaining
                source_info = doc.metadata.get("source", "unknown")
                sources.append({
                    "index":  i + 1,
                    "source": source_info,
                    "score":  round(doc.metadata.get("rerank_score", doc.metadata.get("similarity_score", 0)), 4),
                })
            break

    context = "\n\n".join(context_parts)
    print(f"[RAG] 最终上下文: {len(sources)} 个chunk, {total_chars} 字符")
    return context, sources


def _build_rag_prompt(context: str, question: str) -> str:
    """
    构建 RAG prompt。所有文本内容（角色定义、关键词、指令、模板）
    均从 prompt_config.json 读取，代码本身不含任何业务文字硬编码。
    """
    from config import load_prompt_config
    cfg = load_prompt_config()

    # 判断是否为列举型问题
    list_keywords: list = cfg["list_keywords"]
    is_list_question = any(kw.lower() in question.lower() for kw in list_keywords)

    # 取对应指令列表并编号
    key = "instructions_list" if is_list_question else "instructions_default"
    instr_items: list = cfg[key]
    instructions = "\n".join(f"{i+1}. {item}" for i, item in enumerate(instr_items)) + "\n\n"

    # 组装完整 prompt
    system_role: str = cfg["system_role"]
    template: str = cfg["prompt_template"]
    body = template.format(instructions=instructions, context=context, question=question)
    return f"{system_role}\n{body}"


# 模块级 CrossEncoder 单例（跨 RagEngine 实例共享，启动时预加载）
_global_cross_encoder = None
_global_cross_encoder_lock = threading.Lock()


def _resolve_cross_encoder_device() -> str:
    """
    解析 CROSS_ENCODER_DEVICE 配置，返回实际使用的 device 字符串。

    CROSS_ENCODER_DEVICE 可选值：
      auto — 有 CUDA 则返回 "cuda"，否则返回 "cpu"（默认）
      gpu  — 强制返回 "cuda"（无 CUDA 时会抛异常，由调用方处理）
      cpu  — 强制返回 "cpu"
    """
    import torch
    setting = CROSS_ENCODER_DEVICE.strip().lower()
    if setting == "gpu":
        return "cuda"
    if setting == "cpu":
        return "cpu"
    # auto：有 CUDA 用 GPU，否则 CPU
    return "cuda" if torch.cuda.is_available() else "cpu"


def preload_cross_encoder():
    """
    启动时预加载 CrossEncoder，占住显存后再让 Ollama 加载大模型。

    调用时机：app.py lifespan 启动阶段，在 _check_and_load_models 线程启动之前。
    只有 RERANK_METHOD=cross_encoder 时才执行，其他模式直接返回。
    成功后将实例写入模块级 _global_cross_encoder，供所有 RagEngine 实例共享。

    device 由 CROSS_ENCODER_DEVICE 控制（auto/gpu/cpu）。
    """
    global _global_cross_encoder
    if RERANK_METHOD.strip().lower() != "cross_encoder":
        return
    if _global_cross_encoder is not None:
        return
    with _global_cross_encoder_lock:
        if _global_cross_encoder is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
            device = _resolve_cross_encoder_device()
            print(f"[Rerank] 预加载 CrossEncoder: {CROSS_ENCODER_MODEL}  device={device}  (CROSS_ENCODER_DEVICE={CROSS_ENCODER_DEVICE})")
            _global_cross_encoder = CrossEncoder(
                CROSS_ENCODER_MODEL,
                device=device,
                max_length=512,
            )
            print(f"[Rerank] CrossEncoder 预加载完成  device={device}")
        except Exception as e:
            print(f"[Rerank] CrossEncoder 预加载失败（将在首次使用时重试）: {e}")


class RagEngine:
    """
    RAG 引擎：封装向量检索 → Rerank → LLM 生成的完整链路。

    每次 app.py 调用 get_rag_engine() 时懒加载单例实例。
    更换模型时，app.py 会将全局实例置为 None，下次请求时重新初始化。
    """

    def __init__(self, collection_name: str = "knowledge_base"):
        """
        初始化 RAG 引擎。

        Args:
            collection_name: 默认使用的 ChromaDB 集合名（知识库 ID），
                             多知识库场景下可在 answer_with_docs 时传入 collection_names 覆盖。
        """
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
            num_ctx=NUM_CTX,
            keep_alive=OLLAMA_KEEP_ALIVE,
            timeout=300,       # 超时 300 秒，大上下文推理需要更长时间
        )

        # Rerank 组件懒加载：在首次调用 _rerank_documents 时初始化
        # 避免启动时就加载大模型占用资源
        self._cross_encoder = None       # sentence_transformers.CrossEncoder 实例
        self._cross_encoder_lock = threading.Lock()
        self._listwise_llm = None        # ChatOllama 实例（listwise 模式）

    def _rerank_documents(self, query: str, documents: List[Document], top_k: int) -> List[Document]:
        """
        Rerank 精排入口：根据 RERANK_METHOD 分发到对应实现。

        RERANK_METHOD 可选值（在 .env 中配置）：
          cross_encoder — 本地 HuggingFace CrossEncoder（默认，GPU 加速，精度最高）
          listwise      — 用 CHAT_MODEL 做 Listwise 批量排序（精度高，大模型速度慢）
          ollama        — 通过 Ollama 推理（embed 或 generate+logprob，兼容旧逻辑）

        降级策略：任何异常均降级到向量相似度排序。
        """
        if not documents:
            return documents

        method = RERANK_METHOD.strip().lower()
        print(f"[Rerank] method={method}  docs={len(documents)}  top_k={top_k}")

        try:
            if method == "none":
                # 跳过 rerank，直接按向量相似度排序
                scored = sorted(documents, key=lambda d: d.metadata.get("similarity_score", 0), reverse=True)
                return scored[:top_k]
            elif method == "cross_encoder":
                return self._rerank_by_cross_encoder(query, documents, top_k)
            elif method == "listwise":
                return self._rerank_by_listwise(query, documents, top_k)
            else:
                # ollama 模式（原有逻辑）
                return self._rerank_by_ollama(query, documents, top_k)
        except Exception as e:
            print(f"[Rerank] 失败，降级到相似度排序: {e}")
            scored = sorted(documents, key=lambda d: d.metadata.get("similarity_score", 0), reverse=True)
            return scored[:top_k]

    # ── CrossEncoder 模式 ──────────────────────────────────────────────────────

    def _get_cross_encoder(self):
        """
        获取 CrossEncoder 实例，优先复用启动时预加载的全局单例。

        全局单例由 preload_cross_encoder() 在 app 启动时提前加载到 GPU，
        这样 Ollama 大模型加载时 CrossEncoder 已占住显存，不会发生显存竞争。
        若全局单例未就绪（preload 失败或未调用），则降级为实例级懒加载。
        """
        global _global_cross_encoder
        # 优先使用全局预加载实例（启动时已占显存）
        if _global_cross_encoder is not None:
            return _global_cross_encoder
        # 降级：实例级懒加载（首次 rerank 时初始化）
        if self._cross_encoder is None:
            with self._cross_encoder_lock:
                if self._cross_encoder is None:
                    # 再次检查全局实例，避免并发重复加载
                    if _global_cross_encoder is not None:
                        return _global_cross_encoder
                    try:
                        from sentence_transformers import CrossEncoder
                        device = _resolve_cross_encoder_device()
                        print(f"[Rerank] 加载 CrossEncoder: {CROSS_ENCODER_MODEL}  device={device}  (CROSS_ENCODER_DEVICE={CROSS_ENCODER_DEVICE})")
                        self._cross_encoder = CrossEncoder(
                            CROSS_ENCODER_MODEL,
                            device=device,
                            max_length=512,
                        )
                        print(f"[Rerank] CrossEncoder 加载完成  device={device}")
                    except ImportError:
                        raise RuntimeError(
                            "cross_encoder 模式需要 sentence_transformers，"
                            "请运行: pip install sentence-transformers"
                        )
        return self._cross_encoder

    def _rerank_by_cross_encoder(self, query: str, documents: List[Document], top_k: int) -> List[Document]:
        """
        CrossEncoder 模式：本地 HuggingFace 模型推理，GPU 加速。
        BAAI/bge-reranker-v2-m3 在 RTX 3090 上 6 个文档约 0.1s。
        """
        encoder = self._get_cross_encoder()
        pairs = [(query, doc.page_content) for doc in documents]
        scores = encoder.predict(pairs)   # ndarray[float32]

        ranked = sorted(
            zip(scores, documents),
            key=lambda x: x[0],
            reverse=True,
        )
        result = []
        for score, doc in ranked[:top_k]:
            doc = Document(
                page_content=doc.page_content,
                metadata={**doc.metadata, "rerank_score": round(float(score), 4)},
            )
            result.append(doc)

        print(f"[Rerank] cross_encoder 完成，top scores: {[round(float(s),4) for s,_ in ranked[:top_k]]}")
        return result

    # ── Listwise 模式 ──────────────────────────────────────────────────────────

    _LISTWISE_SYSTEM = (
        "You are a document relevance ranking assistant.\n"
        "Given a query and a list of documents, return a JSON array of document IDs "
        "sorted from most relevant to least relevant.\n"
        "Output ONLY a JSON array of integers, e.g.: [2, 0, 4, 1, 3]\n"
        "Do NOT include any explanation or other text."
    )
    _LISTWISE_USER_TMPL = (
        "Query: {query}\n\n"
        "Documents:\n{doc_list}\n\n"
        "Return a JSON array of the document IDs sorted by relevance (most relevant first). "
        "Output ONLY the JSON array."
    )

    def _get_listwise_llm(self):
        """懒加载 Listwise 用的 ChatOllama。"""
        if self._listwise_llm is None:
            from langchain_ollama import ChatOllama
            self._listwise_llm = ChatOllama(
                model=CHAT_MODEL,
                base_url=OLLAMA_BASE_URL,
                temperature=0,
            )
        return self._listwise_llm

    def _rerank_by_listwise(self, query: str, documents: List[Document], top_k: int) -> List[Document]:
        """
        Listwise 模式：一次 LLM 调用对所有候选文档批量排序。
        精度高，但依赖 LLM 的结构化输出能力；大模型（27B+）速度较慢。
        """
        import json as _json
        import re as _re
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = self._get_listwise_llm()
        doc_lines = "\n".join(
            f"[{i}] {doc.page_content[:600]}" for i, doc in enumerate(documents)
        )
        messages = [
            SystemMessage(content=self._LISTWISE_SYSTEM),
            HumanMessage(content=self._LISTWISE_USER_TMPL.format(
                query=query, doc_list=doc_lines)),
        ]
        response = llm.invoke(messages)
        raw = response.content if hasattr(response, "content") else str(response)
        print(f"[Rerank] listwise raw output: {raw[:120]!r}")

        # 解析 JSON 数组，容错各种格式
        ranked_ids = self._parse_listwise_ids(raw, len(documents))
        result = []
        for rank, idx in enumerate(ranked_ids[:top_k]):
            doc = documents[idx]
            result.append(Document(
                page_content=doc.page_content,
                metadata={**doc.metadata, "rerank_score": round(1.0 / (rank + 1), 4)},
            ))
        print(f"[Rerank] listwise 完成，ranked_ids={ranked_ids[:top_k]}")
        return result

    @staticmethod
    def _parse_listwise_ids(raw: str, n_docs: int) -> List[int]:
        """
        解析 Listwise LLM 输出的 JSON 整数数组，容错各种格式。

        优先用正则提取 [x, y, z] 格式，失败则逐个提取数字。
        未在输出中出现的合法索引追加到末尾（兜底保证所有文档都参与排序）。

        Args:
            raw:    LLM 原始输出文本
            n_docs: 文档总数，用于过滤越界 ID

        Returns:
            去重后的文档索引列表，长度等于 n_docs
        """
        import json as _json, re as _re
        m = _re.search(r'\[[\d,\s]+\]', raw)
        if m:
            try:
                ids = [int(x) for x in _json.loads(m.group()) if 0 <= int(x) < n_docs]
                missing = [i for i in range(n_docs) if i not in ids]
                return ids + missing
            except Exception:
                pass
        nums = [int(x) for x in _re.findall(r'\d+', raw) if int(x) < n_docs]
        seen, dedup = set(), []
        for x in nums:
            if x not in seen:
                seen.add(x); dedup.append(x)
        return dedup + [i for i in range(n_docs) if i not in seen]

    # ── Ollama 模式（原有逻辑） ────────────────────────────────────────────────

    def _rerank_by_ollama(self, query: str, documents: List[Document], top_k: int) -> List[Document]:
        """
        Ollama 模式：通过 Ollama API 推理，根据模型 family 自动选择：
          bert/nomic-bert → embed 模式（/api/embed，第一维 sigmoid）
          其他            → generate+logprob 模式（/api/generate，首 token 概率）
        """
        import math

        model_family = "unknown"
        try:
            with httpx.Client(transport=httpx.HTTPTransport(), timeout=5) as c:
                tags = c.get(f"{OLLAMA_BASE_URL}/api/tags").json()
                for m in tags.get("models", []):
                    if m["name"].split(":")[0] == RERANK_MODEL.split(":")[0] or m["name"] == RERANK_MODEL:
                        model_family = m.get("details", {}).get("family", "unknown")
                        break
        except Exception:
            pass

        use_embed = model_family in ("bert", "nomic-bert")
        print(f"[Rerank] ollama model={RERANK_MODEL} family={model_family} mode={'embed' if use_embed else 'generate'}")

        if use_embed:
            return self._rerank_by_embed(query, documents, top_k)
        else:
            return self._rerank_by_generate(query, documents, top_k)

    def _rerank_by_embed(self, query: str, documents: List[Document], top_k: int) -> List[Document]:
        """
        Embed 模式 rerank（bge-reranker 系列）：
        将 query+document 拼对后调用 /api/embed，embedding 第一维为相关性 score。
        """
        import math
        pairs = [f"query: {query}\npassage: {doc.page_content}" for doc in documents]
        with httpx.Client(transport=httpx.HTTPTransport(), timeout=60) as client:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/embed",
                json={"model": RERANK_MODEL, "input": pairs},
            )
            resp.raise_for_status()
            embeddings = resp.json().get("embeddings", [])

        # bge-reranker embedding 第一维就是相关性 logit，用 sigmoid 转换到 0~1
        scored = []
        for i, (doc, emb) in enumerate(zip(documents, embeddings)):
            logit = emb[0] if emb else 0.0
            score = 1.0 / (1.0 + math.exp(-logit))  # sigmoid
            doc.metadata["rerank_score"] = round(score, 4)
            scored.append((score, i, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = [doc for _, _, doc in scored[:top_k]]
        print(f"[Rerank] embed 模式成功，top scores: {[round(s, 4) for s, _, _ in scored[:top_k]]}")
        return result

    def _rerank_by_generate(self, query: str, documents: List[Document], top_k: int) -> List[Document]:
        """
        Generate 模式 rerank（Qwen3-VL-Reranker 等生成式模型）：
        对每个文档发送判断 prompt，取首 token 的 logprob 作为相关性 score。
        e^logprob 越接近 1.0（logprob 越接近 0）表示该 token 越确定 → 相关性越高。
        """
        import math
        prompt_tpl = (
            "<|im_start|>system\n"
            "Judge whether the document is helpful for answering the query. "
            "Respond with only yes or no.\n<|im_end|>\n"
            "<|im_start|>user\n"
            "Query: {query}\n"
            "Document: {doc}\n<|im_end|>\n"
            "<|im_start|>assistant\n"
        )

        scored = []
        with httpx.Client(transport=httpx.HTTPTransport(), timeout=60) as client:
            for i, doc in enumerate(documents):
                prompt = prompt_tpl.format(query=query, doc=doc.page_content[:1500])
                try:
                    resp = client.post(
                        f"{OLLAMA_BASE_URL}/api/generate",
                        json={
                            "model": RERANK_MODEL,
                            "prompt": prompt,
                            "stream": False,
                            "think": False,
                            "options": {"temperature": 0, "num_predict": 1},
                            "logprobs": True,
                        },
                        timeout=30,
                    )
                    data = resp.json()
                    lp_list = data.get("logprobs", [])
                    if lp_list:
                        logprob = lp_list[0].get("logprob", -10.0)
                        # logprob 越接近 0 → 该 token 概率越高 → 相关性越确定
                        # 取负值使其越大越相关（原始 logprob 是负数）
                        score = math.exp(logprob)  # 范围 (0, 1]
                    else:
                        score = 0.0
                    doc.metadata["rerank_score"] = round(score, 4)
                    scored.append((score, i, doc))
                except Exception as e:
                    print(f"[Rerank] 文档 {i} 打分失败: {e}")
                    score = doc.metadata.get("similarity_score", 0.0)
                    doc.metadata["rerank_score"] = round(score, 4)
                    scored.append((score, i, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = [doc for _, _, doc in scored[:top_k]]
        print(f"[Rerank] generate 模式成功，top scores: {[round(s, 4) for s, _, _ in scored[:top_k]]}")
        return result

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
        from config import TITLE_GENERIC_SUFFIXES as _GENERIC_SUFFIXES, QUERY_STOPWORDS as _QUERY_STOPWORDS

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
        # 1. 标题直接出现在问题里 → 精确命中（要求标题长度 ≥ 4，避免"保障""计划"等短词滥匹配）
        # 2. 核心词（去通用尾部词）在问题里 → 精确命中
        # 注意：不做 question in t 方向的匹配（问题通常比标题长，会产生大量误命中）

        # 通用尾部词表和停用词表已在函数顶部从 config 导入（_GENERIC_SUFFIXES / _QUERY_STOPWORDS）

        def _extract_core(title: str) -> str:
            """去掉标题末尾的通用词，返回语义核心部分"""
            t = title
            for suf in _GENERIC_SUFFIXES:
                if t.endswith(suf) and len(t) > len(suf):
                    t = t[: -len(suf)].strip()
            return t

        hit_titles = set()
        if question:
            for t in all_titles:
                # 策略1：标题出现在问题里（如"海外特药药品清单"在问题中）
                # 只对足够长的标题做子串匹配，4字以下的短标题（"计划""保障"等）跳过
                if len(t) >= 4 and t in question:
                    hit_titles.add(t)
                    continue
                # 策略2：核心词（去通用尾部词）在问题里
                core = _extract_core(t)
                if len(core) >= 4 and core in question:
                    hit_titles.add(t)
                    continue
                # 策略3：问题里的关键词出现在标题里（双向匹配，处理"海外特药"→"海外特药药品清单"）
                # 从问题中提取长度≥4的连续子串，判断是否为标题子串
                # 限制：问题子串不能是停用词（在 config.QUERY_STOPWORDS 中配置），避免误命中
                for qlen in range(min(len(question), 10), 3, -1):  # 从最长到最短（最多取10字）
                    for qi in range(len(question) - qlen + 1):
                        qsub = question[qi:qi + qlen]
                        if qsub in _QUERY_STOPWORDS:
                            continue
                        if qsub in t and len(qsub) >= 4:
                            hit_titles.add(t)
                            break
                    if t in hit_titles:
                        break

        # 全局标题扫描兜底：
        # 若向量检索召回的 chunk 里根本没有相关标题（all_titles 为空或不匹配），
        # 直接扫向量库中所有 chunk 的 [标题]，用问题关键词匹配。
        # 典型场景：问"海外特药有哪些"时，TOP_K 没召回任何"海外特药"相关 chunk，
        #           all_titles 里没有"海外特药药品清单"，策略1/2/3 均失败。
        if not hit_titles and question:
            cols_to_scan = collection_names if collection_names else [self.collection_name]
            try:
                for col_name in cols_to_scan:
                    col = self.vector_store._get_or_create_collection(col_name)
                    if col.count() == 0:
                        continue
                    raw = col.get(include=["documents"])
                    for doc_text in raw.get("documents", []):
                        t = _title(doc_text)
                        if not t or len(t) < 4:
                            continue
                        # 用问题子串匹配标题
                        matched = False
                        if t in question:
                            matched = True
                        if not matched:
                            core = _extract_core(t)
                            if len(core) >= 4 and core in question:
                                matched = True
                        if not matched:
                            for qlen in range(min(len(question), 10), 3, -1):
                                for qi in range(len(question) - qlen + 1):
                                    qsub = question[qi:qi + qlen]
                                    if qsub in _QUERY_STOPWORDS:
                                        continue
                                    if qsub in t and len(qsub) >= 4:
                                        matched = True
                                        break
                                if matched:
                                    break
                        if matched:
                            hit_titles.add(t)
                if hit_titles:
                    print(f"[RAG] _expand_by_title 全局扫描命中: {hit_titles}")
            except Exception as e:
                print(f"[RAG] _expand_by_title 全局扫描失败: {e}")

        # fallback：精确匹配失败时，只取相似度最高的 chunk 所属标题，不扩展全部
        # 仅当 rerank_score 或 similarity_score 超过阈值时才做 fallback，
        # 避免完全不相关的 chunk（如 score < 0.05）误触发标题扩展
        if not hit_titles:
            best_title = ""
            best_sim = -1.0
            for doc in reranked:
                t = _title(doc.page_content)
                if not t:
                    continue
                # 优先用 rerank_score（更精准），没有则用 similarity_score
                score = doc.metadata.get("rerank_score", doc.metadata.get("similarity_score", 0.0))
                if score > best_sim:
                    best_sim = score
                    best_title = t
            # 只有得分超过最低阈值才做 fallback 扩展，防止不相关 chunk 污染上下文
            FALLBACK_MIN_SCORE = 0.1
            if best_title and best_sim >= FALLBACK_MIN_SCORE:
                hit_titles = {best_title}

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
            # 收集命中标题对应的 source 文件名，用 where 条件只拉取相关文件，避免全量扫描
            hit_sources = list({
                d.metadata.get("source") for d in reranked + all_docs
                if _title(d.page_content) in hit_titles and d.metadata.get("source")
            })

            for col_name in cols_to_search:
                col = self.vector_store._get_or_create_collection(col_name)
                if col.count() == 0:
                    continue

                # 按 source 过滤，只拉取命中标题所在文件的 chunk
                if hit_sources:
                    try:
                        raw = col.get(
                            where={"source": {"$in": hit_sources}},
                            include=["documents", "metadatas"],
                        )
                        all_col_docs = raw.get("documents", [])
                        all_col_metas = raw.get("metadatas", [])
                    except Exception:
                        # ChromaDB 版本不支持 $in 时降级到全量（兼容旧版本）
                        raw = col.get(include=["documents", "metadatas"])
                        all_col_docs = raw.get("documents", [])
                        all_col_metas = raw.get("metadatas", [])
                else:
                    raw = col.get(include=["documents", "metadatas"])
                    all_col_docs = raw.get("documents", [])
                    all_col_metas = raw.get("metadatas", [])

                print(f"[RAG] _expand_by_title scanning {col_name}: {len(all_col_docs)} docs (sources={hit_sources})")

                # 按标题分组收集候选
                title_candidates = defaultdict(list)
                for doc_text, meta in zip(all_col_docs, all_col_metas):
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

        # extra 内按 chunk_index 排序，确保同章节内顺序正确
        extra.sort(key=lambda d: d.metadata.get("chunk_index", 0))

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

        内部复用 answer_with_docs，避免重复维护两套相同的 rerank/prompt/LLM 逻辑。
        """
        relevant_docs = self.vector_store.search(
            question, collection_name=self.collection_name, top_k=TOP_K
        )

        if not relevant_docs:
            return {
                "answer": "抱歉，知识库中暂无相关内容。请先上传文档到知识库。",
                "sources": [],
                "has_knowledge": False,
            }

        return self.answer_with_docs(
            question=question,
            documents=relevant_docs,
            chat_history=chat_history,
            collection_names=[self.collection_name],
        )

    def ingest_document(self, filename: str, chunks: List[str]):
        """
        将文档分块批量写入当前知识库的向量库。

        每个块的 metadata 中记录来源文件名（source），
        便于后续按文件删除对应的向量数据。

        Args:
            filename: .md 文件名，作为向量块的 source 标识
            chunks:   文档分块列表（由 document_processor.chunk_texts 生成）
        """
        # 为每个块添加来源标记和序号（chunk_index 用于 get_chunks_by_source 排序）
        metadatas = [{"source": filename, "chunk_index": i} for i, _ in enumerate(chunks)]
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
                role = "用户" if h[0] in ("user", "用户") else "客服"
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
                                 collection_names: List[str] = None, abort_event=None):
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
        prompt_tokens = 0
        completion_tokens = 0
        _httpx_client = None  # 保存 client 引用，供 abort 时强制关闭
        try:
            import config as _cfg
            from config import THINKING

            # 启动一个监控线程：一旦 abort_event 触发，立即关闭 httpx client
            # 这样即使 iter_lines() 阻塞在 prefill 阶段，也能被强制中断
            def _abort_watcher():
                """
                中止监控线程：等待 abort_event 被设置后，强制关闭 httpx client。

                解决 iter_lines() 在 prefill 阶段长时间阻塞无法响应 abort 的问题。
                通过在独立线程中主动关闭 client，强制中断底层网络连接。
                """
                if abort_event:
                    abort_event.wait()  # 阻塞直到 event 被 set
                    if _httpx_client is not None:
                        print(f"[RAG] abort watcher: force closing httpx client")
                        try:
                            _httpx_client.close()
                        except Exception:
                            pass

            watcher = threading.Thread(target=_abort_watcher, daemon=True)
            watcher.start()

            with httpx.Client(transport=httpx.HTTPTransport(), timeout=300) as client:
                _httpx_client = client

                # 如果在建立连接前就已经 abort，直接退出
                if abort_event and abort_event.is_set():
                    print(f"[RAG] aborted before Ollama request")
                    yield {"done": True, "sources": sources, "has_knowledge": True,
                           "answer": "".join(full_answer).strip(),
                           "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
                    return

                with client.stream(
                    "POST",
                    f"{_cfg.OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model":      _cfg.CHAT_MODEL,
                        "prompt":     system_prompt,
                        "stream":     True,
                        "keep_alive": _cfg.OLLAMA_KEEP_ALIVE,
                        "options": {
                            "temperature": 0.3,
                            "num_ctx":     NUM_CTX,
                        },
                        "think": THINKING,
                    },
                ) as resp:
                    resp.raise_for_status()
                    token_count = 0
                    raw_count = 0
                    for line in resp.iter_lines():
                        # 每次读到新行都检查 abort
                        if abort_event and abort_event.is_set():
                            print(f"[RAG] stream aborted by client, closing Ollama connection")
                            break
                        if not line:
                            continue
                        try:
                            chunk = _json.loads(line)
                        except Exception:
                            continue
                        raw_count += 1
                        if raw_count <= 3:
                            print(f"[RAG] raw chunk[{raw_count}]: {str(chunk)[:150]}")
                        token = chunk.get("response", "")
                        if token:
                            full_answer.append(token)
                            token_count += 1
                            yield {"token": token}
                        if chunk.get("done"):
                            prompt_tokens     = chunk.get("prompt_eval_count", 0)
                            completion_tokens = chunk.get("eval_count", 0)
                            print(f"[RAG] stream done, output_tokens={token_count}, "
                                  f"prompt_tokens={prompt_tokens}, completion_tokens={completion_tokens}")
                            if token_count == 0:
                                print(f"[RAG] done chunk keys: {list(chunk.keys())}, sample: {str(chunk)[:200]}")
                            break

            yield {
                "done":          True,
                "sources":       sources,
                "has_knowledge": True,
                "answer":        "".join(full_answer).strip(),
                "usage": {
                    "prompt_tokens":     prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens":      prompt_tokens + completion_tokens,
                },
            }
        except Exception as e:
            error_msg = str(e)
            msg = "模型响应超时，请稍后重试。" if ("502" in error_msg or "Gateway" in error_msg) else f"模型调用失败: {error_msg}"
            yield {"error": msg, "sources": sources}
