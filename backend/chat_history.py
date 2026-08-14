"""
聊天历史记录模块 - SQLite 持久化

作者: kimikang

数据库结构：
  表 messages:
    id          INTEGER PRIMARY KEY AUTOINCREMENT
    session_id  TEXT     NOT NULL   -- 会话 ID（前端生成的 UUID 前缀）
    role        TEXT     NOT NULL   -- "user" 或 "assistant"
    content     TEXT     NOT NULL   -- 消息正文
    sources     TEXT                -- JSON 序列化的参考来源列表（仅 assistant 消息有）
    created_at  TEXT     NOT NULL   -- ISO 格式时间戳

设计说明：
  - 使用 Python 内置 sqlite3，无需额外依赖
  - 数据库文件默认保存在 backend/ 目录下的 chat_history.db
  - 所有写操作使用 context manager 自动提交/回滚
  - 线程安全：check_same_thread=False + 应用层保证每次操作独立连接
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

# 数据库文件路径（与 app.py 同目录）
DB_PATH = Path(__file__).parent / "chat_history.db"


def _get_conn() -> sqlite3.Connection:
    """
    创建并返回一个 SQLite 连接。
    每次操作用独立连接，避免多线程共享同一连接的问题。
    row_factory = sqlite3.Row 使查询结果可用列名访问。
    """
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    初始化数据库：创建 messages 表（如不存在）。
    应用启动时调用一次即可。
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT    NOT NULL,
                role       TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                sources    TEXT    DEFAULT '[]',
                created_at TEXT    NOT NULL
            )
        """)
        # 为常用查询字段建索引，提升按 session_id 查询和全量查询速度
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages (session_id, id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_created
            ON messages (created_at)
        """)
        conn.commit()


def save_message(
    session_id: str,
    role: str,
    content: str,
    sources: List[Dict[str, Any]] = None,
) -> int:
    """
    保存一条聊天消息到数据库。

    Args:
        session_id: 会话 ID
        role:       "user" 或 "assistant"
        content:    消息正文
        sources:    参考来源列表（仅 assistant 消息需要），如 [{"index":1,"source":"xxx.md","score":0.85}]

    Returns:
        新插入行的 id
    """
    sources_json = json.dumps(sources or [], ensure_ascii=False)
    created_at = datetime.now().isoformat(timespec="seconds")

    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (session_id, role, content, sources, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, sources_json, created_at),
        )
        conn.commit()
        return cur.lastrowid


def get_history(limit: int = 200) -> List[Dict[str, Any]]:
    """
    获取最近的聊天历史记录（跨所有会话，按时间正序）。

    前端加载页面时调用，用于恢复历史消息到界面。

    Args:
        limit: 最多返回的消息条数，默认 200

    Returns:
        消息列表，每项包含 id / session_id / role / content / sources / created_at
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, sources, created_at
            FROM messages
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    # 反转使结果为正序（最旧在前）
    result = []
    for row in reversed(rows):
        result.append({
            "id":         row["id"],
            "session_id": row["session_id"],
            "role":       row["role"],
            "content":    row["content"],
            "sources":    json.loads(row["sources"] or "[]"),
            "created_at": row["created_at"],
        })
    return result


def clear_history():
    """
    清空全部聊天历史记录。

    执行 DELETE FROM messages 并重置自增计数器。
    """
    with _get_conn() as conn:
        conn.execute("DELETE FROM messages")
        # 重置自增 ID（可选，保持 ID 从 1 重新开始）
        conn.execute("DELETE FROM sqlite_sequence WHERE name='messages'")
        conn.commit()


def get_message_count() -> int:
    """
    返回数据库中的消息总条数，用于统计展示。
    """
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()
        return row["cnt"] if row else 0
