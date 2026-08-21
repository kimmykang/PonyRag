"""
智能客服系统 - 向量数据库模块

作者: kimikang

架构说明：
  使用 ChromaDB 作为向量存储后端，LangChain OllamaEmbeddings 生成向量。

  关键设计决策：
  ┌─────────────────────────────────────────────────────────┐
  │ 不将 OllamaEmbeddings 传入 ChromaDB 的 embedding_function│
  │                                                         │
  │ 原因：ChromaDB 0.4.16+ 要求 EmbeddingFunction 实现      │
  │       __call__(self, input) 签名，LangChain 的实现不符合 │
  │       该接口，直接传入会导致 "Extra inputs not permitted" │
  │       错误。                                             │
  │                                                         │
  │ 解决方案：在应用层手动调用 embed_documents / embed_query │
  │           生成向量，再以 embeddings= 参数直接传给 ChromaDB│
  └─────────────────────────────────────────────────────────┘

  文档 ID 策略：
    使用 MD5(source::chunk_index::content[:64]) 作为唯一 ID，
    避免跨文件 ID 碰撞，同时实现幂等写入（相同内容不重复存储）。
"""
import hashlib
from typing import List, Optional

import chromadb
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document

from config import VECTOR_DB_PATH, EMBED_MODEL, TOP_K, OLLAMA_BASE_URL


def _doc_id(source: str, chunk_index: int, content: str) -> str:
    """
    生成文档块的稳定唯一 ID（MD5 hash）。

    设计原则：
      - 基于来源文件名 + 块序号 + 内容前缀三元组计算，确保全局唯一
      - 同一文件重新索引时，相同内容生成相同 ID，ChromaDB 会自动跳过重复写入
      - 避免简单序号（doc_0, doc_1）在多文件场景下的 ID 碰撞

    Args:
        source:      来源文件名，如 "report.md"
        chunk_index: 该文档内的块序号（0-based）
        content:     块文本内容（仅取前 64 字符参与 hash）

    Returns:
        32 位十六进制 MD5 字符串
    """
    raw = f"{source}::{chunk_index}::{content[:64]}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class VectorStoreManager:
    """
    ChromaDB 向量库管理器

    职责：
      - 管理 ChromaDB 集合的创建/获取
      - 封装文档的向量化写入、语义检索、按来源删除等操作
      - 屏蔽 ChromaDB API 细节，为上层（RagEngine）提供简洁接口
    """

    def __init__(self):
        # 初始化 Ollama 嵌入模型，用于将文本转为向量
        self.embeddings = OllamaEmbeddings(
            model=EMBED_MODEL,
            base_url=OLLAMA_BASE_URL,
        )
        # ChromaDB 持久化客户端，数据保存在 VECTOR_DB_PATH 目录
        self.client = chromadb.PersistentClient(path=VECTOR_DB_PATH)

    def _get_or_create_collection(self, collection_name: str):
        """
        获取指定名称的向量集合，不存在则创建。

        注意：创建时不传入 embedding_function，
        所有向量化操作在应用层完成后再写入 ChromaDB。

        Args:
            collection_name: 集合名称，如 "knowledge_base"

        Returns:
            ChromaDB Collection 对象
        """
        try:
            return self.client.get_collection(collection_name)
        except Exception:
            return self.client.create_collection(collection_name)

    def add_documents(
        self,
        collection_name: str,
        chunks: List[str],
        metadatas: Optional[List[dict]] = None,
    ) -> int:
        """
        将文档块批量写入向量库。

        写入流程：
          1. 为每个块计算稳定 ID（基于内容 hash）
          2. 查询已存在的 ID，过滤重复内容（幂等写入）
          3. 调用 OllamaEmbeddings 对新块生成向量
          4. 将文本、向量、元数据一起写入 ChromaDB

        Args:
            collection_name: 目标集合名称
            chunks:          文本块列表
            metadatas:       每个块的元数据列表，必须包含 "source" 字段
                             默认为 [{"source": "unknown"}, ...]

        Returns:
            实际新增的块数量（已存在的块不计入）
        """
        if not chunks:
            return 0

        col = self._get_or_create_collection(collection_name)

        if metadatas is None:
            metadatas = [{"source": "unknown"} for _ in chunks]

        # 为每个块生成唯一 ID
        ids = [_doc_id(metadatas[i].get("source", ""), i, chunks[i]) for i in range(len(chunks))]

        # 查询哪些 ID 已存在，过滤后只写入新块
        existing = col.get(ids=ids, include=[])
        existing_set = set(existing.get("ids", []))
        new_indices = [i for i, doc_id in enumerate(ids) if doc_id not in existing_set]

        if not new_indices:
            return 0  # 所有块都已存在，无需写入

        new_ids    = [ids[i]       for i in new_indices]
        new_chunks = [chunks[i]    for i in new_indices]
        new_metas  = [metadatas[i] for i in new_indices]

        # 分批生成向量（每批 50 个），避免 Ollama 单次请求超时
        # 526 个 chunk 一次性 embed 容易超时；50 个一批约 2~5 秒，稳定可靠
        EMBED_BATCH = 50
        vectors = []
        for i in range(0, len(new_chunks), EMBED_BATCH):
            batch = new_chunks[i:i + EMBED_BATCH]
            print(f"[VectorStore] embedding {i+1}~{i+len(batch)}/{len(new_chunks)} chunks...")
            batch_vecs = self.embeddings.embed_documents(batch)
            vectors.extend(batch_vecs)

        # 分批写入 ChromaDB，每批最多 100 条，避免 Rust 层崩溃
        BATCH_SIZE = 100
        for start in range(0, len(new_ids), BATCH_SIZE):
            end = start + BATCH_SIZE
            batch_ids    = new_ids[start:end]
            batch_docs   = new_chunks[start:end]
            batch_vecs   = vectors[start:end]
            batch_metas  = new_metas[start:end]

            # 过滤空文本（ChromaDB 不接受空字符串）
            valid = [(i, d, v, m) for i, d, v, m in zip(batch_ids, batch_docs, batch_vecs, batch_metas) if d.strip()]
            if not valid:
                continue
            v_ids, v_docs, v_vecs, v_metas = zip(*valid)

            try:
                col.add(
                    documents=list(v_docs),
                    embeddings=list(v_vecs),
                    metadatas=list(v_metas),
                    ids=list(v_ids),
                )
            except Exception as e:
                err_msg = str(e)
                print(f"[VectorStore] add batch failed: {err_msg}")
                # 若是维度不匹配（换了 embedding 模型），重建集合后重试
                if "dimension" in err_msg.lower() or "embedding" in err_msg.lower():
                    print("[VectorStore] 向量维度不匹配，重建集合...")
                    try:
                        self.client.delete_collection(collection_name)
                    except Exception:
                        pass
                    col = self._get_or_create_collection(collection_name)
                    col.add(
                        documents=list(v_docs),
                        embeddings=list(v_vecs),
                        metadatas=list(v_metas),
                        ids=list(v_ids),
                    )
                else:
                    raise

        return len(new_ids)

    def search(
        self,
        query: str,
        collection_name: str = "knowledge_base",
        top_k: int = None,
    ) -> List[Document]:
        """
        语义相似度检索，返回与查询最相关的文档块。

        检索流程：
          1. 将查询文本向量化（embed_query）
          2. 在 ChromaDB 中做余弦相似度检索
          3. 将距离转换为相似度分数（1 / (1 + distance)）
          4. 返回 LangChain Document 对象列表，附带 similarity_score 元数据

        Args:
            query:           用户查询文本
            collection_name: 目标集合名称
            top_k:           返回结果数量，默认使用配置中的 TOP_K

        Returns:
            Document 列表，按相似度降序排列
        """
        if top_k is None:
            top_k = TOP_K

        col = self._get_or_create_collection(collection_name)

        # 在应用层生成查询向量
        query_vector = self.embeddings.embed_query(query)

        try:
            # 防止请求数量超过集合实际大小
            results = col.query(
                query_embeddings=[query_vector],
                n_results=min(top_k, col.count() or 1),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            err_msg = str(e)
            # 检测维度不匹配错误
            if "dimension" in err_msg.lower() or "embedding" in err_msg.lower():
                print(f"[VectorStore] 检索时维度不匹配，集合 {collection_name} 可能使用旧模型创建")
                print(f"[VectorStore] 错误详情: {err_msg}")
                # 记录到 .pending_delete，下次启动自动清理
                try:
                    from pathlib import Path as _Path
                    from config import VECTOR_DB_PATH as _VDB
                    pending = _Path(_VDB) / ".pending_delete"
                    existing = set(pending.read_text(encoding="utf-8").splitlines()) if pending.exists() else set()
                    existing.add(collection_name)
                    pending.write_text("\n".join(sorted(existing)), encoding="utf-8")
                    print(f"[VectorStore] 已记录到 .pending_delete，下次启动将自动清理: {collection_name}")
                except Exception as pe:
                    print(f"[VectorStore] 写入 .pending_delete 失败: {pe}")
                # 抛出异常让上层感知，而不是静默返回空
                raise
            else:
                raise

        # 将 ChromaDB 结果转换为 LangChain Document 对象
        documents = []
        if results["documents"] and results["documents"][0]:
            for i, doc_text in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
                distance = results["distances"][0][i] if results.get("distances") else 0
                # 将 L2 距离转换为 0~1 相似度（距离越小，相似度越高）
                similarity = 1.0 / (1.0 + distance)
                documents.append(Document(
                    page_content=doc_text,
                    metadata={**metadata, "similarity_score": similarity},
                ))

        return documents

    def delete_by_source(self, source: str, collection_name: str = "knowledge_base") -> int:
        """
        删除所有来自指定文档的向量块。

        用于文档删除时同步清理向量库，保证知识库数据与文件系统一致。

        Args:
            source:          来源文件名，与 add_documents 时 metadata["source"] 一致
            collection_name: 目标集合名称

        Returns:
            实际删除的块数量
        """
        try:
            col = self._get_or_create_collection(collection_name)
            # 按 source 字段过滤出所有相关块的 ID
            result = col.get(where={"source": source}, include=[])
            ids = result.get("ids", [])
            if ids:
                col.delete(ids=ids)
            return len(ids)
        except Exception as e:
            print(f"[VectorStore] delete_by_source error: {e}")
            return 0

    def get_stats(self, collection_name: str = "knowledge_base") -> dict:
        """
        获取向量库统计信息（当前集合的文档块总数）。

        Args:
            collection_name: 集合名称

        Returns:
            {"document_count": int, "collection": str}
            出错时返回 {"error": str}
        """
        try:
            col = self._get_or_create_collection(collection_name)
            count = col.count()
            return {"document_count": count, "collection": collection_name}
        except Exception as e:
            return {"error": str(e)}

    def clear_collection(self, collection_name: str = "knowledge_base") -> bool:
        """
        完全清空指定集合（删除集合本身，而非逐条删除）。

        用于前端「清空向量库」功能，下次访问时会自动重建空集合。

        Args:
            collection_name: 要清空的集合名称

        Returns:
            True 表示清空成功，False 表示操作失败
        """
        try:
            self.client.delete_collection(collection_name)
            return True
        except Exception:
            return False
