"""
智能客服系统 - 知识库管理模块

作者: kimikang

职责：
  - 维护知识库元数据（名称、描述、启用状态、创建时间）
  - 提供知识库 CRUD 操作
  - 维护文档切分记录（embed_model、chunk_method、参数），用于智能重索引
  - 元数据存储在 SQLite（chat_history.db），与聊天历史共库

数据模型：
  knowledge_bases 表
    id          INTEGER PRIMARY KEY
    kb_id       TEXT UNIQUE         -- 集合名称，同时作为 ChromaDB collection_name
    name        TEXT                -- 用户可见的知识库名称
    description TEXT                -- 可选描述
    enabled     INTEGER DEFAULT 1   -- 1=启用，0=禁用
    created_at  DATETIME            -- 创建时间

  document_chunks 表
    id            INTEGER PRIMARY KEY
    kb_id         TEXT     -- 所属知识库
    filename      TEXT     -- .md 文件名（与 .indexed 标记一致）
    embed_model   TEXT     -- 索引时使用的嵌入模型
    chunk_method  TEXT     -- 切分方式：recursive / markdown / semantic
    chunk_size    INTEGER  -- 分块大小（token）
    chunk_overlap INTEGER  -- 重叠大小（token）
    chunk_count   INTEGER  -- 实际切出的块数
    indexed_at    DATETIME -- 索引时间
    UNIQUE(kb_id, filename)
"""
import sqlite3
import uuid
import re
from datetime import datetime
from pathlib import Path

from config import UPLOAD_DIR

# SQLite 数据库路径（与聊天历史共用同一个文件）
_DB_PATH = Path(__file__).parent / "chat_history.db"


def _conn():
    """创建并返回 SQLite 连接，开启 WAL 模式提升并发性能"""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_kb_table():
    """
    初始化 knowledge_bases 和 document_chunks 表，同时确保默认知识库存在。
    幂等操作，可重复调用。
    """
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id       TEXT UNIQUE NOT NULL,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                enabled     INTEGER DEFAULT 1,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 文档切分记录表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id         TEXT     NOT NULL,
                filename      TEXT     NOT NULL,
                embed_model   TEXT     NOT NULL DEFAULT '',
                chunk_method  TEXT     NOT NULL DEFAULT 'recursive',
                chunk_size    INTEGER  NOT NULL DEFAULT 500,
                chunk_overlap INTEGER  NOT NULL DEFAULT 50,
                chunk_count   INTEGER  NOT NULL DEFAULT 0,
                indexed_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(kb_id, filename)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_doc_chunks_kb
            ON document_chunks (kb_id)
        """)
        conn.commit()

    # 确保默认知识库存在
    if not get_kb("knowledge_base"):
        create_kb(kb_id="knowledge_base", name="默认知识库", description="系统默认知识库")


def _safe_kb_id(name: str) -> str:
    """
    将用户输入的知识库名称转为合法的 ChromaDB 集合名。

    ChromaDB 集合名规则：
      - 3~63 字符
      - 只允许字母、数字、下划线、连字符
      - 不能以下划线或连字符开头/结尾

    这里将中文等字符转为 pinyin 首字母 + uuid 短码。
    """
    # 保留字母、数字、下划线，其他转为下划线
    safe = re.sub(r'[^\w]', '_', name, flags=re.UNICODE)
    # 只保留 ASCII 字母数字和下划线
    safe = re.sub(r'[^a-zA-Z0-9_]', '', safe)
    if not safe:
        safe = "kb"
    # 加上短 uuid 避免碰撞
    short_id = uuid.uuid4().hex[:8]
    kb_id = f"{safe[:20]}_{short_id}"
    return kb_id


def create_kb(name: str, description: str = "", kb_id: str = None) -> dict:
    """
    创建新知识库记录。

    Args:
        name:        用户可见的知识库名称
        description: 可选描述
        kb_id:       指定 collection_name，不指定则自动生成

    Returns:
        创建的知识库信息字典
    """
    if kb_id is None:
        kb_id = _safe_kb_id(name)

    with _conn() as conn:
        conn.execute(
            "INSERT INTO knowledge_bases (kb_id, name, description) VALUES (?, ?, ?)",
            (kb_id, name, description)
        )
        conn.commit()

    # 创建对应的上传目录
    kb_upload_dir = Path(UPLOAD_DIR) / kb_id
    kb_upload_dir.mkdir(parents=True, exist_ok=True)

    return get_kb(kb_id)


def get_kb(kb_id: str) -> dict | None:
    """通过 kb_id 获取知识库信息，不存在返回 None"""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE kb_id = ?", (kb_id,)
        ).fetchone()
    return dict(row) if row else None


def list_kbs() -> list[dict]:
    """返回所有知识库列表（按创建时间升序）"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM knowledge_bases ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_enabled_kbs() -> list[dict]:
    """返回所有已启用的知识库"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM knowledge_bases WHERE enabled = 1 ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_kb(kb_id: str, name: str = None, description: str = None, enabled: int = None) -> dict | None:
    """
    更新知识库信息（部分更新）。

    Args:
        kb_id:       目标知识库
        name:        新名称（None 表示不修改）
        description: 新描述（None 表示不修改）
        enabled:     启用状态 0/1（None 表示不修改）

    Returns:
        更新后的知识库信息，kb_id 不存在时返回 None
    """
    kb = get_kb(kb_id)
    if not kb:
        return None

    updates = {}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    if enabled is not None:
        updates["enabled"] = enabled

    if not updates:
        return kb

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [kb_id]

    with _conn() as conn:
        conn.execute(
            f"UPDATE knowledge_bases SET {set_clause} WHERE kb_id = ?",
            values
        )
        conn.commit()

    return get_kb(kb_id)


def delete_kb(kb_id: str) -> bool:
    """
    删除知识库元数据记录。

    注意：不自动删除 ChromaDB 集合和文件，由调用方处理。
    不允许删除默认知识库 "knowledge_base"。

    Returns:
        True 表示删除成功，False 表示不存在或不允许删除
    """
    if kb_id == "knowledge_base":
        return False  # 默认知识库不允许删除

    with _conn() as conn:
        cursor = conn.execute(
            "DELETE FROM knowledge_bases WHERE kb_id = ?", (kb_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_kb_upload_dir(kb_id: str) -> Path:
    """返回知识库对应的上传目录路径（自动创建）"""
    kb_dir = Path(UPLOAD_DIR) / kb_id
    kb_dir.mkdir(parents=True, exist_ok=True)
    return kb_dir


def get_kb_index_marker(kb_id: str) -> Path:
    """返回知识库对应的 .indexed 标记文件路径"""
    return get_kb_upload_dir(kb_id) / ".indexed"


# ──────────────────────────────────────────────────────────────
# 文档切分记录（document_chunks 表）
# ──────────────────────────────────────────────────────────────

def save_doc_chunk_record(
    kb_id: str,
    filename: str,
    embed_model: str,
    chunk_method: str,
    chunk_size: int,
    chunk_overlap: int,
    chunk_count: int,
):
    """
    保存或更新文档的切分记录。

    每次成功将文档入库向量库后调用，记录当时的配置参数。
    使用 INSERT OR REPLACE 保证同一 (kb_id, filename) 只有一条记录。

    Args:
        kb_id:        知识库 ID
        filename:     .md 文件名
        embed_model:  嵌入模型名称
        chunk_method: 切分方式（recursive/markdown/semantic）
        chunk_size:   分块大小
        chunk_overlap:重叠大小
        chunk_count:  实际切出块数
    """
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute("""
            INSERT INTO document_chunks
                (kb_id, filename, embed_model, chunk_method, chunk_size, chunk_overlap, chunk_count, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(kb_id, filename) DO UPDATE SET
                embed_model   = excluded.embed_model,
                chunk_method  = excluded.chunk_method,
                chunk_size    = excluded.chunk_size,
                chunk_overlap = excluded.chunk_overlap,
                chunk_count   = excluded.chunk_count,
                indexed_at    = excluded.indexed_at
        """, (kb_id, filename, embed_model, chunk_method, chunk_size, chunk_overlap, chunk_count, now))
        conn.commit()


def get_doc_chunk_record(kb_id: str, filename: str) -> dict | None:
    """
    获取指定文档的切分记录。

    Returns:
        dict 包含 embed_model/chunk_method/chunk_size/chunk_overlap/chunk_count/indexed_at，
        不存在时返回 None
    """
    with _conn() as conn:
        row = conn.execute("""
            SELECT * FROM document_chunks WHERE kb_id = ? AND filename = ?
        """, (kb_id, filename)).fetchone()
    return dict(row) if row else None


def list_doc_chunk_records(kb_id: str) -> list[dict]:
    """列出知识库内所有文档的切分记录，按索引时间倒序"""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT * FROM document_chunks WHERE kb_id = ? ORDER BY indexed_at DESC
        """, (kb_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_doc_chunk_record(kb_id: str, filename: str):
    """删除指定文档的切分记录（文档被删除时调用）"""
    with _conn() as conn:
        conn.execute(
            "DELETE FROM document_chunks WHERE kb_id = ? AND filename = ?",
            (kb_id, filename)
        )
        conn.commit()


def delete_all_doc_chunk_records(kb_id: str):
    """删除知识库内所有文档的切分记录（向量库清空时调用）"""
    with _conn() as conn:
        conn.execute("DELETE FROM document_chunks WHERE kb_id = ?", (kb_id,))
        conn.commit()


def get_docs_needing_reindex(
    kb_id: str,
    current_embed_model: str,
    current_chunk_method: str,
    current_chunk_size: int,
    current_chunk_overlap: int,
) -> list[str]:
    """
    找出需要重新切分的文档列表。

    比较标准：embed_model、chunk_method、chunk_size、chunk_overlap
    任意一项与当前配置不一致，该文档就需要重索引。

    Args:
        kb_id:                   知识库 ID
        current_embed_model:     当前嵌入模型
        current_chunk_method:    当前切分方式
        current_chunk_size:      当前分块大小
        current_chunk_overlap:   当前重叠大小

    Returns:
        需要重索引的文件名列表（.md 文件名）
    """
    with _conn() as conn:
        rows = conn.execute("""
            SELECT filename FROM document_chunks
            WHERE kb_id = ?
              AND (
                embed_model   != ? OR
                chunk_method  != ? OR
                chunk_size    != ? OR
                chunk_overlap != ?
              )
        """, (kb_id, current_embed_model, current_chunk_method,
              current_chunk_size, current_chunk_overlap)).fetchall()
    return [r["filename"] for r in rows]
