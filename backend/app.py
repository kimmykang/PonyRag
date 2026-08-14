"""
智能客服系统 - FastAPI 主应用

作者: kimikang

职责：
  - 提供 RESTful HTTP API，供前端调用
  - 管理应用生命周期（启动时索引文档、后台加载模型）
  - 协调 document_processor / rag_engine / vector_store 三个模块

启动流程：
  1. 设置 NO_PROXY 环境变量（必须在所有 httpx 导入前完成）
  2. FastAPI lifespan：
     a. 启动后台线程检查/加载三个 Ollama 模型
     b. 批量索引 uploads 目录中尚未入库的文档
  3. 模型全部就绪后自动在浏览器中打开前端页面

代理绕过说明：
  httpx 0.28+ 默认读取 Windows 系统代理，会导致对
  localhost:11434 的请求返回 502。通过在最开头设置
  NO_PROXY / no_proxy 环境变量，以及在工具函数中使用
  httpx.HTTPTransport() 显式直连，双重保障绕过代理。
"""
import os

# ──────────────────────────────────────────────────────────────
# 关键：在所有 httpx 相关库导入前设置 NO_PROXY
# httpx 在模块导入时读取代理配置，因此必须在这里最先设置
# ──────────────────────────────────────────────────────────────
for _proxy_key in ("NO_PROXY", "no_proxy"):
    _existing = os.environ.get(_proxy_key, "")
    _no_proxy_hosts = "localhost,127.0.0.1"
    if _existing:
        if "localhost" not in _existing:
            os.environ[_proxy_key] = _existing + "," + _no_proxy_hosts
    else:
        os.environ[_proxy_key] = _no_proxy_hosts

import uuid
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import HOST, PORT, UPLOAD_DIR, VECTOR_DB_PATH, OLLAMA_BASE_URL, CHAT_MODEL, EMBED_MODEL, RERANK_MODEL
from document_processor import (
    parse_document, chunk_texts, upload_file, list_documents, cleanup_document,
    convert_to_md, ALLOWED_EXTENSIONS,
)
from rag_engine import RagEngine
from vector_store import VectorStoreManager
from chat_history import init_db, save_message, get_history, clear_history
from knowledge_base import (
    init_kb_table, create_kb, get_kb, list_kbs, list_enabled_kbs,
    update_kb, delete_kb, get_kb_upload_dir, get_kb_index_marker,
)

# 索引标记文件路径：记录哪些 .md 文件已入库（默认知识库兼容旧格式）
_INDEX_MARKER = Path(UPLOAD_DIR) / ".indexed"

# 全局 RAG 引擎字典：{ kb_id: RagEngine }，按知识库懒加载
_rag_engines: dict = {}
_rag_engines_lock = threading.Lock()

# 兼容旧代码的 rag_engine 变量（指向默认知识库引擎）
rag_engine: Optional[RagEngine] = None

# ──────────────────────────────────────────────────────────────
# 模型状态管理
# 三个模型各自维护独立状态，供前端轮询展示
# ──────────────────────────────────────────────────────────────

# 模型状态字典，每个 key 对应一个模型：
#   status: "checking"（检查中）| "loading"（加载中）| "ready"（就绪）| "error"（失败）
#   message: 当前状态的详细描述，显示在前端侧边栏
_model_status: dict = {
    "chat":   {"model": CHAT_MODEL,   "status": "checking", "message": "检查中..."},
    "embed":  {"model": EMBED_MODEL,  "status": "checking", "message": "检查中..."},
    "rerank": {"model": RERANK_MODEL, "status": "checking", "message": "检查中..."},
}
# 互斥锁：_model_status 可能被后台线程写、HTTP 请求读，需加锁保护
_model_status_lock = threading.Lock()


def _set_model_status(key: str, status: str, message: str):
    """
    线程安全地更新指定模型的状态，同时打印日志。

    Args:
        key:     模型标识，"chat" / "embed" / "rerank"
        status:  新状态字符串
        message: 状态说明文字
    """
    with _model_status_lock:
        _model_status[key]["status"] = status
        _model_status[key]["message"] = message
    print(f"[ModelStatus] {key} ({_model_status[key]['model']}): {status} - {message}")


def _ollama_client() -> httpx.Client:
    """
    创建一个直连 Ollama 的 httpx 客户端（绕过系统代理）。

    使用 httpx.HTTPTransport() 显式指定传输层，
    确保即使环境变量未生效，请求也不会经过代理服务器。

    Returns:
        httpx.Client 实例（调用方需用 with 语句管理生命周期）
    """
    return httpx.Client(transport=httpx.HTTPTransport())


def _get_local_models() -> set:
    """
    查询 Ollama 本地已下载的模型列表（调用 /api/tags 接口）。

    返回模型 name 字符串集合，如 {"qwen3.6:27b", "qwen3-embedding:4b"}。
    精确匹配，不做任何名称变换。

    Returns:
        模型名称集合；若请求失败则返回空集合（调用方会触发拉取流程）
    """
    try:
        with _ollama_client() as client:
            resp = client.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return {m.get("name", "") for m in data.get("models", [])}
    except Exception as e:
        print(f"[ModelStatus] _get_local_models error: {e}")
        return set()


def _pull_model(model_name: str):
    """
    通过 Ollama /api/pull 接口拉取模型到本地。

    使用流式请求保持长连接直到拉取完成（大模型可能需要数分钟）。
    拉取过程中不逐行解析进度，只等待连接关闭即可。

    Args:
        model_name: 模型名称，如 "qwen3.6:27b"

    Raises:
        RuntimeError: 拉取过程中发生网络或服务端错误
    """
    try:
        with _ollama_client() as client:
            with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/pull",
                json={"name": model_name, "stream": True},
                timeout=600,   # 大模型拉取可能超过 10 分钟
            ) as resp:
                for _ in resp.iter_lines():
                    pass  # 消费响应流，等待拉取完成
    except Exception as e:
        raise RuntimeError(f"pull 失败: {e}")


def _ensure_model(key: str, model_name: str):
    """
    确保指定模型已在 Ollama 本地并加载到显存（预热）。

    执行步骤：
      1. 查询本地模型列表，若不存在则拉取（_pull_model）
      2. 发送一次极小请求触发模型加载到显存（预热）：
         - embed 模型：调用 /api/embeddings
         - chat/rerank 模型：调用 /api/generate
      3. 更新 _model_status 供前端轮询

    Args:
        key:        模型标识，"chat" / "embed" / "rerank"
        model_name: Ollama 模型名称
    """
    _set_model_status(key, "checking", f"检查模型 {model_name}...")

    # 步骤 1：检查本地是否已下载
    local = _get_local_models()
    if model_name not in local:
        _set_model_status(key, "loading", f"模型不存在，正在拉取 {model_name}...")
        try:
            _pull_model(model_name)
        except Exception as e:
            _set_model_status(key, "error", f"拉取失败: {e}")
            return

    # 步骤 2：预热 - 发送小请求让模型加载到显存
    _set_model_status(key, "loading", f"正在加载 {model_name} 到显存...")
    try:
        with _ollama_client() as client:
            if key == "embed":
                # 嵌入模型使用 /api/embeddings 预热
                client.post(
                    f"{OLLAMA_BASE_URL}/api/embeddings",
                    json={"model": model_name, "prompt": "hi"},
                    timeout=120,
                )
            elif key in ("chat", "rerank"):
                # 对话/Rerank 模型使用 /api/generate 预热
                client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={"model": model_name, "prompt": "hi", "stream": False},
                    timeout=120,
                )
        _set_model_status(key, "ready", "已就绪")
    except Exception as e:
        _set_model_status(key, "error", f"加载失败: {e}")


def _open_browser():
    """
    在系统默认浏览器中打开前端页面。

    延迟 1 秒后再打开，确保 uvicorn 已完全就绪（能接受请求）。
    仅在所有模型检查完成后调用一次。
    """
    import webbrowser, time
    time.sleep(1)
    url = f"http://localhost:{PORT}"
    print(f"[Browser] 打开浏览器: {url}")
    webbrowser.open(url)


def _check_and_load_models(
    chat_model: str = None,
    embed_model: str = None,
    rerank_model: str = None,
    open_browser_after: bool = False,
    changed_keys: list = None,
):
    """
    后台线程入口：检查并加载模型，完成后可选打开浏览器。

    加载顺序：embed → chat → rerank
    优先加载嵌入模型，确保文档检索功能最早可用。

    Args:
        chat_model:        对话模型名，None 时使用 config.CHAT_MODEL
        embed_model:       嵌入模型名，None 时使用 config.EMBED_MODEL
        rerank_model:      Rerank 模型名，None 时使用 config.RERANK_MODEL
        open_browser_after: 全部完成后是否打开浏览器（首次启动时为 True）
        changed_keys:      仅重新加载的模型 key 列表，如 ["embed", "chat"]
                           None 表示全部加载（首次启动时）
    """
    import config as _cfg
    _chat   = chat_model   or _cfg.CHAT_MODEL
    _embed  = embed_model  or _cfg.EMBED_MODEL
    _rerank = rerank_model or _cfg.RERANK_MODEL

    all_models = [("embed", _embed), ("chat", _chat), ("rerank", _rerank)]

    if changed_keys is None:
        # 首次启动：全部加载，全部重置状态
        models_to_load = all_models
        for key, model_name in models_to_load:
            with _model_status_lock:
                _model_status[key]["model"]   = model_name
                _model_status[key]["status"]  = "checking"
                _model_status[key]["message"] = "检查中..."
    else:
        # 模型变更：只重置并加载有变更的模型
        models_to_load = [(k, m) for k, m in all_models if k in changed_keys]
        for key, model_name in models_to_load:
            with _model_status_lock:
                _model_status[key]["model"]   = model_name
                _model_status[key]["status"]  = "checking"
                _model_status[key]["message"] = "检查中..."
        print(f"[ModelStatus] 仅重新加载变更的模型: {changed_keys}")

    # 逐个检查并加载
    for key, model_name in models_to_load:
        _ensure_model(key, model_name)

    # 检查是否有加载失败的模型，打印告警
    with _model_status_lock:
        errors = [k for k, v in _model_status.items() if v["status"] == "error"]
    print(f"[ModelStatus] {'所有' if changed_keys is None else '变更'}模型检查完成")
    if errors:
        print(f"[Warning] 以下模型加载失败: {errors}，部分功能可能受限")

    if open_browser_after:
        _open_browser()


# ──────────────────────────────────────────────────────────────
# Pydantic 数据模型（请求/响应 Schema）
# ──────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """聊天请求体"""
    question: str                         # 用户问题（必填）
    session_id: Optional[str] = None      # 会话 ID，前端生成，用于关联多轮对话
    chat_history: Optional[list] = None   # 历史对话，格式 [["user/assistant", "内容"], ...]
    kb_ids: Optional[list] = None         # 要检索的知识库 ID 列表，None 时检索所有启用的知识库


class ChatResponse(BaseModel):
    """聊天响应体"""
    answer: str          # LLM 生成的回答
    sources: list        # 参考来源列表，每项含 index/source/score
    has_knowledge: bool  # 是否从知识库中找到相关内容
    session_id: str      # 回传 session_id，前端可用于续接对话


class ModelInfo(BaseModel):
    """当前模型配置信息"""
    chat_model: str
    embed_model: str
    rerank_model: str
    ollama_url: str


class ModelConfigRequest(BaseModel):
    """更换模型的请求体"""
    chat_model: str    # 新的对话模型名
    embed_model: str   # 新的嵌入模型名
    rerank_model: str  # 新的 Rerank 模型名


class KBCreateRequest(BaseModel):
    """创建知识库请求体"""
    name: str
    description: str = ""


class KBUpdateRequest(BaseModel):
    """更新知识库请求体"""
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[int] = None


# ──────────────────────────────────────────────────────────────
# FastAPI 应用生命周期
# ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 应用生命周期管理（启动/关闭钩子）。

    启动时：
      1. 初始化 SQLite 聊天历史数据库
      2. 检查 embedding 模型配置一致性（防止模型变更后未清空向量库）
      3. 在后台线程中检查/加载三个 Ollama 模型（不阻塞主线程）
      4. 批量索引 uploads 目录中尚未入库的文档
      5. 模型全部就绪后，后台线程自动打开浏览器

    关闭时：yield 之后的代码会在 Ctrl+C 时执行（当前无需清理资源）
    """
    print("=" * 50)
    print("  Starting up...")
    print("=" * 50)

    # 初始化 SQLite 聊天历史数据库
    init_db()

    # 初始化知识库元数据表
    init_kb_table()

    # 迁移旧数据：将 uploads/ 根目录的文档移到 uploads/knowledge_base/
    _migrate_legacy_uploads()

    # 检查 embedding 模型配置一致性
    _check_embed_model_consistency()

    # 后台线程启动模型检查（daemon=True 确保主进程退出时线程也终止）
    t = threading.Thread(
        target=_check_and_load_models,
        kwargs={"open_browser_after": True},
        daemon=True,
    )
    t.start()

    # 批量索引所有知识库中未入库的文档
    _batch_ingest_all_kbs()
    print("=" * 50)
    yield  # 应用运行期间阻塞在此


# ──────────────────────────────────────────────────────────────
# FastAPI 应用实例
# ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="智能客服系统",
    description="LangChain + Ollama + ChromaDB 智能客服",
    version="2.0.0",
    lifespan=lifespan,
)

# 允许所有来源的跨域请求（开发环境便利性；生产环境应限制 allow_origins）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载前端静态文件目录，路径前缀 /static
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────

def get_rag_engine(kb_id: str = "knowledge_base") -> RagEngine:
    """
    获取指定知识库的 RAG 引擎（按 kb_id 缓存，懒加载）。

    更换模型后，调用 _invalidate_rag_engines() 清空缓存，
    下次调用时用新配置重新创建。

    Args:
        kb_id: 知识库 ID（ChromaDB 集合名），默认 "knowledge_base"

    Returns:
        RagEngine 实例
    """
    global rag_engine
    with _rag_engines_lock:
        if kb_id not in _rag_engines or _rag_engines[kb_id] is None:
            _rag_engines[kb_id] = RagEngine(collection_name=kb_id)
        engine = _rag_engines[kb_id]
    # 兼容旧代码
    if kb_id == "knowledge_base":
        rag_engine = engine
    return engine


def _invalidate_rag_engines():
    """销毁所有 RAG 引擎缓存，下次请求时重建（换模型后调用）"""
    global rag_engine
    with _rag_engines_lock:
        _rag_engines.clear()
    rag_engine = None
    # 触发垃圾回收，释放 ChromaDB 客户端连接
    import gc
    gc.collect()


def _load_indexed(kb_id: str = None) -> set:
    """
    从 .indexed 标记文件读取已入库的文件名集合。

    Args:
        kb_id: 知识库 ID，None 时使用全局默认（兼容旧格式）
    """
    if kb_id and kb_id != "knowledge_base":
        marker = get_kb_index_marker(kb_id)
    else:
        marker = _INDEX_MARKER
    if not marker.exists():
        return set()
    with open(marker, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _save_indexed(names: set, kb_id: str = None):
    """
    将已入库的文件名集合写回 .indexed 标记文件。

    Args:
        names: 当前已索引的全部文件名集合
        kb_id: 知识库 ID，None 时使用全局默认（兼容旧格式）
    """
    if kb_id and kb_id != "knowledge_base":
        marker = get_kb_index_marker(kb_id)
    else:
        marker = _INDEX_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    with open(marker, "w", encoding="utf-8") as f:
        for name in sorted(names):
            f.write(name + "\n")


def _migrate_legacy_uploads():
    """
    一次性迁移：将 uploads/ 根目录的旧文档移动到 uploads/knowledge_base/ 子目录。

    旧版本把文件直接放在 uploads/ 根目录，新版本每个知识库有独立子目录。
    这个函数在启动时执行一次，将根目录的文档文件（非子目录）移动到默认知识库目录。
    已在子目录的文件不受影响，保证幂等。
    """
    root_dir = Path(UPLOAD_DIR)
    if not root_dir.exists():
        return

    from document_processor import ALLOWED_EXTENSIONS

    # 找出根目录中直接存放的文档文件（非 .indexed 等系统文件）
    files_to_migrate = []
    for f in root_dir.iterdir():
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        if f.suffix.lower() in ALLOWED_EXTENSIONS:
            files_to_migrate.append(f)

    if not files_to_migrate:
        return

    # 目标目录：默认知识库
    dest_dir = get_kb_upload_dir("knowledge_base")
    dest_dir.mkdir(parents=True, exist_ok=True)

    migrated = 0
    for f in files_to_migrate:
        dest = dest_dir / f.name
        if dest.exists():
            # 目标已存在，删除源文件避免重复
            f.unlink()
        else:
            import shutil
            shutil.move(str(f), str(dest))
        migrated += 1

    # 迁移 .indexed 标记文件
    old_indexed = root_dir / ".indexed"
    new_indexed = dest_dir / ".indexed"
    if old_indexed.exists() and not new_indexed.exists():
        import shutil
        shutil.move(str(old_indexed), str(new_indexed))

    if migrated > 0:
        print(f"[Migrate] 已将 {migrated} 个旧文件迁移到 uploads/knowledge_base/")


def _batch_ingest_all_kbs():
    """
    启动时批量索引所有知识库中尚未入库的文档。
    遍历所有已注册的知识库，依次调用 _batch_ingest。
    """
    kbs = list_kbs()
    for kb in kbs:
        kb_id = kb["kb_id"]
        kb_dir = get_kb_upload_dir(kb_id)
        print(f"[Batch] 索引知识库: {kb['name']} ({kb_id})")
        _batch_ingest(str(kb_dir), kb_id)


def _batch_ingest(upload_dir: str, kb_id: str = "knowledge_base"):
    """
    批量索引指定目录中尚未入库的文档到对应知识库。

    两阶段流程：
      阶段 1 - 格式转换：
        遍历所有非 .md 文件（pdf/docx/xlsx/pptx 等），
        若同名 .md 不存在则调用 markitdown 转换。

      阶段 2 - 向量入库：
        遍历所有 .md 文件，跳过已在 .indexed 中的文件，
        对新文件执行：读取 → 分块 → 向量化 → 写入 ChromaDB。
        每成功处理一个文件立即更新 .indexed，防止中断后重复。

    Args:
        upload_dir: 知识库的上传目录路径
        kb_id:      知识库 ID，用于确定 ChromaDB 集合名
    """
    dir_path = Path(upload_dir)
    if not dir_path.exists():
        return

    indexed  = _load_indexed(kb_id)
    ingested = 0
    skipped  = 0
    errors   = []

    # ── 阶段 1：转换非 md 文件 ──────────────────────────────────
    for f in sorted(dir_path.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        ext = f.suffix.lower()
        if ext in (".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt"):
            md_path = f.with_suffix(".md")
            if not md_path.exists():
                try:
                    convert_to_md(str(f))
                    print(f"[Batch] Converted: {f.name} → {md_path.name}")
                except Exception as e:
                    errors.append(f"{f.name}: convert failed: {e}")

    # ── 阶段 2：以 .md 文件为标的入库 ──────────────────────────
    for f in sorted(dir_path.iterdir()):
        if not f.is_file() or f.suffix.lower() != ".md" or f.name.startswith("."):
            continue
        if f.name in indexed:
            skipped += 1
            continue
        try:
            texts = parse_document(str(f))
            if not texts:
                errors.append(f"{f.name}: empty")
                continue
            chunks = chunk_texts(texts, is_markdown=True)
            if not chunks:
                errors.append(f"{f.name}: chunk failed")
                continue
            get_rag_engine(kb_id).ingest_document(f.name, chunks)
            indexed.add(f.name)
            _save_indexed(indexed, kb_id)
            ingested += 1
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    if errors:
        print(f"[Batch:{kb_id}] Errors:")
        for err in errors:
            print(f"  - {err}")
    print(f"[Batch:{kb_id}] Done: {ingested} indexed, {skipped} skipped, {len(errors)} errors")


def _update_env_file(env_path: Path, updates: dict):
    """
    原地更新 .env 文件中的指定键值，保留注释和其他配置不变。

    更新逻辑：
      - 逐行扫描，找到匹配的 KEY=VALUE 行则替换值
      - 注释行（# 开头）原样保留
      - 不在 updates 中的键原样保留
      - updates 中有但文件里没有的键，追加到文件末尾

    Args:
        env_path: .env 文件的 Path 对象
        updates:  需要更新的键值对字典，如 {"CHAT_MODEL": "llama3"}
    """
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # 保留注释行和空行
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)
    # 追加文件中不存在的新键
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _check_embed_model_consistency():
    """
    启动时检查 embedding 模型配置一致性。
    
    策略：比较 .embed_model 标记文件中的模型名与 .env 中的 EMBED_MODEL。
    不一致则彻底删除 vector_db 目录并重新索引。
    不依赖 Ollama HTTP（启动时模型可能还未就绪）。
    """
    vector_db_path = Path(VECTOR_DB_PATH)
    model_marker = vector_db_path / ".embed_model"
    
    last_model = ""
    if model_marker.exists():
        try:
            last_model = model_marker.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    
    current_model = EMBED_MODEL

    # 模型名不一致，且向量库目录非空（有数据）
    if last_model and last_model != current_model:
        print(f"[Startup] ⚠️ Embedding 模型变更: {last_model} → {current_model}")
        try:
            import shutil
            if vector_db_path.exists():
                shutil.rmtree(str(vector_db_path))
                print(f"[Startup] ✅ 已删除旧 vector_db 目录")
            
            kbs = list_kbs()
            for kb in kbs:
                _save_indexed(set(), kb["kb_id"])
            print(f"[Startup] ✅ 已清空 {len(kbs)} 个知识库的索引标记")
            print(f"[Startup] 🔄 将在模型就绪后自动重新索引...")
            _reindex_all_documents()
        except Exception as e:
            print(f"[Startup] 处理失败: {e}")

    # 更新标记文件
    try:
        vector_db_path.mkdir(parents=True, exist_ok=True)
        model_marker.write_text(current_model, encoding="utf-8")
    except Exception as e:
        print(f"[Startup] 无法写入模型标记文件: {e}")


def _reindex_all_documents():
    """
    重新索引所有知识库中的 .md 文档。

    用于 embedding 模型变更后自动重建向量库。
    遍历所有知识库，分别清空并重新索引。
    执行流程：
      1. 等待 embed 模型就绪
      2. 清空 RAG 引擎缓存（确保使用全新的 ChromaDB 客户端）
      3. 遍历所有知识库
      4. 每个知识库：扫描文档 → 读取 → 分块 → 向量化 → 写入 ChromaDB
      5. 更新各知识库的 .indexed 标记文件
    """
    global _reindex_status
    _reindex_status = {
        "in_progress": True,
        "total": 0,
        "current": 0,
        "success": 0,
        "failed": 0,
        "current_file": "",
        "status": "准备中..."
    }

    print("[Reindex] 开始重新索引所有文档...")

    # 等待 embedding 模型加载完成（最多等待 60 秒）
    import time
    wait_time = 0
    _reindex_status["status"] = "等待模型加载..."
    while wait_time < 60:
        with _model_status_lock:
            embed_status = _model_status.get("embed", {}).get("status", "")
        if embed_status == "ready":
            break
        if embed_status == "error":
            print("[Reindex] Embedding 模型加载失败，无法重新索引")
            _reindex_status["in_progress"] = False
            _reindex_status["status"] = "模型加载失败"
            return
        print(f"[Reindex] 等待 Embedding 模型加载... ({wait_time}s)")
        time.sleep(3)
        wait_time += 3

    if wait_time >= 60:
        print("[Reindex] Embedding 模型加载超时，无法重新索引")
        _reindex_status["in_progress"] = False
        _reindex_status["status"] = "模型加载超时"
        return

    print("[Reindex] Embedding 模型已就绪，准备索引文档")
    
    # 关键：再次清空 RAG 引擎缓存，确保使用全新的 ChromaDB 客户端
    # 这样可以避免任何残留的集合元数据（尤其是维度信息）
    _invalidate_rag_engines()
    time.sleep(1)  # 等待垃圾回收释放旧客户端
    print("[Reindex] 已清空 RAG 引擎缓存，确保使用新模型配置")

    # 收集所有知识库的所有 .md 文件
    kbs = list_kbs()
    all_files = []  # [(kb_id, Path)]
    for kb in kbs:
        kb_id = kb["kb_id"]
        kb_dir = get_kb_upload_dir(kb_id)
        for f in sorted(kb_dir.glob("*.md")):
            if not f.name.startswith("."):
                all_files.append((kb_id, f))

    total = len(all_files)
    _reindex_status["total"] = total
    _reindex_status["status"] = "正在索引..."

    if total == 0:
        print("[Reindex] 没有找到需要索引的文档")
        _reindex_status["in_progress"] = False
        _reindex_status["status"] = "没有文档需要索引"
        return

    print(f"[Reindex] 找到 {total} 个文档（跨 {len(kbs)} 个知识库）")

    # 按知识库分组记录已索引文件
    kb_indexed: dict = {kb["kb_id"]: set() for kb in kbs}
    errors = []

    for kb_id, f in all_files:
        _reindex_status["current_file"] = f.name

        try:
            texts = parse_document(str(f))
            if not texts:
                errors.append(f"{f.name}: 文档为空")
                _reindex_status["failed"] += 1
                _reindex_status["current"] += 1
                continue

            chunks = chunk_texts(texts, is_markdown=True)
            if not chunks:
                errors.append(f"{f.name}: 分块失败")
                _reindex_status["failed"] += 1
                _reindex_status["current"] += 1
                continue

            engine = get_rag_engine(kb_id)
            engine.ingest_document(f.name, chunks)
            kb_indexed[kb_id].add(f.name)
            _reindex_status["success"] += 1
            _reindex_status["current"] += 1
            print(f"[Reindex] [{_reindex_status['current']}/{total}] ✅ {f.name} (kb={kb_id}, {len(chunks)} 块)")

        except Exception as e:
            errors.append(f"{f.name}: {str(e)}")
            _reindex_status["failed"] += 1
            _reindex_status["current"] += 1
            print(f"[Reindex] [{_reindex_status['current']}/{total}] ❌ {f.name}: {e}")

    # 保存各知识库的索引标记
    for kb_id, indexed_set in kb_indexed.items():
        _save_indexed(indexed_set, kb_id)

    _reindex_status["in_progress"] = False
    _reindex_status["status"] = "完成"

    print("=" * 60)
    print(f"[Reindex] 重新索引完成:")
    print(f"  ✅ 成功: {_reindex_status['success']}")
    print(f"  ❌ 失败: {_reindex_status['failed']}")
    if errors:
        print(f"  错误详情:")
        for err in errors:
            print(f"    - {err}")
    print("=" * 60)


# 全局重新索引状态
_reindex_status = {
    "in_progress": False,
    "total": 0,
    "current": 0,
    "success": 0,
    "failed": 0,
    "current_file": "",
    "status": ""
}


# ──────────────────────────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    """根路径返回前端 index.html（单页应用入口）"""
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/knowledge")
async def serve_knowledge():
    """知识库管理页面入口"""
    return FileResponse(os.path.join(FRONTEND_DIR, "knowledge.html"))


@app.get("/api/health")
async def health_check():
    """
    健康检查接口，前端用于检测后端服务是否可用。

    响应：{"status": "ok"}
    """
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    聊天接口：基于 RAG 回答用户问题，支持跨多个知识库检索。

    当 kb_ids 为 None 时，检索所有当前启用的知识库并合并结果。
    """
    # 确定要检索的知识库列表
    if req.kb_ids:
        kb_ids = req.kb_ids
    else:
        # 检索所有启用的知识库
        enabled = list_enabled_kbs()
        if not enabled:
            return ChatResponse(
                answer="暂无可用的知识库。请先在知识库管理页面创建并启用至少一个知识库。",
                sources=[],
                has_knowledge=False,
                session_id=req.session_id or str(uuid.uuid4()),
            )
        kb_ids = [kb["kb_id"] for kb in enabled]

    # 跨多个知识库并行检索，合并结果
    import config as _cfg
    all_docs = []
    for kb_id in kb_ids:
        try:
            engine = get_rag_engine(kb_id)
            col_count = engine.vector_store.client.get_collection(kb_id).count() if kb_id in [c.name for c in engine.vector_store.client.list_collections()] else 0
            docs = engine.vector_store.search(req.question, collection_name=kb_id, top_k=_cfg.TOP_K)
            print(f"[Chat] 知识库 {kb_id}: 集合条目={col_count}, 检索到={len(docs)} 条, TOP_K={_cfg.TOP_K}")
            all_docs.extend(docs)
        except Exception as e:
            print(f"[Chat] 检索知识库 {kb_id} 时出错: {e}")
            import traceback
            traceback.print_exc()
            continue

    print(f"[Chat] 合并后总文档数: {len(all_docs)}")

    if not all_docs:
        result = {
            "answer": "抱歉，知识库中暂无相关内容。请先上传文档到知识库。",
            "sources": [],
            "has_knowledge": False,
        }
    else:
        # 用主引擎执行 rerank + 生成
        main_engine = get_rag_engine(kb_ids[0])
        result = main_engine.answer_with_docs(
            question=req.question,
            documents=all_docs,
            chat_history=req.chat_history,
        )

    session_id = req.session_id or str(uuid.uuid4())
    save_message(session_id, "user", req.question)
    save_message(session_id, "assistant", result["answer"], result["sources"])

    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        has_knowledge=result["has_knowledge"],
        session_id=session_id,
    )


@app.get("/api/models")
async def get_model_info():
    """
    查询当前模型配置（从 config.py 读取）。

    响应体示例：
      {
        "chat_model": "qwen3.6:27b",
        "embed_model": "qwen3-embedding:4b",
        "rerank_model": "MedAIBase/Qwen3-VL-Reranker:2b",
        "ollama_url": "http://localhost:11434"
      }
    """
    return ModelInfo(
        chat_model=CHAT_MODEL,
        embed_model=EMBED_MODEL,
        rerank_model=RERANK_MODEL,
        ollama_url=OLLAMA_BASE_URL,
    )


@app.get("/api/ollama/models")
async def get_ollama_models():
    """
    从 Ollama 获取本地已下载的模型列表，供前端「模型设置」下拉框使用。

    直接转发 Ollama /api/tags 的结果，返回格式：
      {
        "models": [
          {"name": "qwen3.6:27b", "size": 15000000000},
          {"name": "qwen3-embedding:4b", "size": 2500000000},
          ...
        ]
      }

    若 Ollama 未启动或请求失败，返回空列表（前端显示"无法获取模型列表"）。
    """
    try:
        with _ollama_client() as client:
            resp = client.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = [
                {"name": m.get("name", ""), "size": m.get("size", 0)}
                for m in data.get("models", [])
                if m.get("name")
            ]
            return {"models": models}
    except Exception as e:
        print(f"[OllamaModels] 获取模型列表失败: {e}")
        return {"models": []}


@app.get("/api/model-status")
async def get_model_status():
    """
    查询三个模型的当前加载状态（供前端轮询）。

    响应体示例：
      {
        "models": {
          "chat": {
            "model": "qwen3.6:27b",
            "status": "ready",
            "message": "已就绪"
          },
          "embed": {...},
          "rerank": {...}
        }
      }

    status 可能值：
      - "checking"：检查本地是否存在
      - "loading"：正在拉取或加载到显存
      - "ready"：已就绪，可接受请求
      - "error"：加载失败，message 中有错误详情
    """
    with _model_status_lock:
        return {"models": dict(_model_status)}


@app.get("/api/reindex-status")
async def get_reindex_status():
    """
    获取重新索引进度状态，供前端轮询展示进度条。
    
    响应体示例：
      {
        "in_progress": true,
        "total": 10,
        "current": 3,
        "success": 2,
        "failed": 1,
        "current_file": "example.md",
        "status": "正在索引...",
        "percentage": 30.0
      }
    """
    with _model_status_lock:
        status = dict(_reindex_status)
    
    # 计算百分比
    if status["total"] > 0:
        status["percentage"] = round((status["current"] / status["total"]) * 100, 1)
    else:
        status["percentage"] = 0.0
    
    return status

@app.post("/api/save-config")
@app.post("/api/config/models")
async def save_config(req: ModelConfigRequest):
    """
    保存新的模型配置，并触发后台重新加载模型。

    处理流程：
      1. 检测 embedding 模型是否变更
      2. 如果变更：
         a. 清空向量库（旧向量与新模型不兼容）
         b. 清空索引标记
         c. 使用新模型重新索引所有 .md 文档
      3. 将新配置写入 .env 文件
      4. 运行时更新 config 模块的全局变量
      5. 销毁当前 RAG 引擎（下次请求会用新配置重建）
      6. 启动后台线程重新检查/加载三个新模型

    请求体示例：
      {
        "chat_model": "llama3:8b",
        "embed_model": "nomic-embed-text",
        "rerank_model": "some/rerank:1.0"
      }

    响应：
      {"status": "success", "message": "...", "embed_changed": bool, 
       "vectors_cleared": bool, "docs_reindexed": int}

    注意：
      - embedding 模型变更会自动清空并重建向量库
      - 重建过程在后台进行，不阻塞响应
    """
    import config as _cfg
    
    # 检测各模型是否变更
    chat_changed  = req.chat_model   != _cfg.CHAT_MODEL
    embed_changed = req.embed_model  != _cfg.EMBED_MODEL
    rerank_changed = req.rerank_model != _cfg.RERANK_MODEL
    changed_keys  = (["chat"]   if chat_changed   else []) + \
                    (["embed"]  if embed_changed  else []) + \
                    (["rerank"] if rerank_changed else [])
    
    vectors_cleared = False
    docs_reindexed = 0
    
    # 如果 embedding 模型变更，清空所有知识库的向量库并准备重建
    if embed_changed:
        try:
            # 步骤 1：先销毁所有 RAG 引擎缓存（释放 ChromaDB 客户端连接）
            _invalidate_rag_engines()
            print("[Config] 已销毁所有 RAG 引擎缓存")
            
            # 步骤 2：删除整个 vector_db 目录
            # 避免 ChromaDB 残留旧 UUID 集合导致维度冲突
            import shutil
            import time
            vector_db_path = Path(VECTOR_DB_PATH)
            if vector_db_path.exists():
                # 确保所有文件句柄已释放（Windows 文件锁问题）
                time.sleep(0.5)
                shutil.rmtree(str(vector_db_path))
                print(f"[Config] 已删除整个 vector_db 目录")
            
            # 步骤 3：清空所有知识库的索引标记
            kbs = list_kbs()
            for kb in kbs:
                _save_indexed(set(), kb["kb_id"])
            vectors_cleared = True
            print(f"[Config] Embedding 模型已变更，已清空 {len(kbs)} 个知识库的向量索引标记")

            # 步骤 4：重建目录并更新模型标记
            vector_db_path.mkdir(parents=True, exist_ok=True)
            model_marker = vector_db_path / ".embed_model"
            model_marker.write_text(req.embed_model, encoding="utf-8")
            print(f"[Config] 已更新模型标记: {req.embed_model}")
            
        except Exception as e:
            print(f"[Config] 清空向量库失败: {e}")
            import traceback
            traceback.print_exc()
    
    env_path = Path(os.path.dirname(__file__)) / ".env"
    # 更新 .env 文件
    _update_env_file(
        env_path,
        {
            "CHAT_MODEL":   req.chat_model,
            "EMBED_MODEL":  req.embed_model,
            "RERANK_MODEL": req.rerank_model,
        }
    )
    # 运行时更新 config 模块全局变量
    _cfg.CHAT_MODEL   = req.chat_model
    _cfg.EMBED_MODEL  = req.embed_model
    _cfg.RERANK_MODEL = req.rerank_model

    # 销毁所有 RAG 引擎缓存，下次请求会用新配置重新初始化
    _invalidate_rag_engines()

    # 后台线程：只重新加载有变更的模型
    if changed_keys:
        t = threading.Thread(
            target=_check_and_load_models,
            kwargs={
                "chat_model":   req.chat_model,
                "embed_model":  req.embed_model,
                "rerank_model": req.rerank_model,
                "open_browser_after": False,
                "changed_keys": changed_keys,
            },
            daemon=True,
        )
        t.start()
        print(f"[Config] 已触发重新加载: {changed_keys}")

    # 如果 embedding 模型变更，启动后台线程重新索引所有文档
    if embed_changed:
        reindex_thread = threading.Thread(
            target=_reindex_all_documents,
            daemon=True,
        )
        reindex_thread.start()

    message = f"配置已保存，正在重新加载: {', '.join(changed_keys) if changed_keys else '无变更'}"
    if embed_changed:
        message += "。向量库已清空，正在后台重新索引所有文档..."

    return {
        "status": "success",
        "message": message,
        "embed_changed": embed_changed,
        "vectors_cleared": vectors_cleared,
        "reindexing": embed_changed,
        "changed_keys": changed_keys,
    }


@app.post("/api/upload")
async def upload_doc(file: UploadFile = File(...), kb_id: str = "knowledge_base"):
    """
    上传文档接口：接收前端上传的单个文件，转换为 Markdown 并索引到指定知识库的向量库。

    处理流程：
      1. 调用 document_processor.upload_file 保存原文件到对应知识库的 uploads 目录
      2. 若文件非 .md，调用 convert_to_md（markitdown 转换）
      3. 读取 .md 文件内容，分块（chunk_texts，启用 Markdown 语法感知）
      4. 调用 RagEngine.ingest_document 写入向量库
      5. 更新知识库的 .indexed 标记，记录已入库
      6. 删除原始非 md 文件（保留转换后的 .md 文件）

    请求：
      multipart/form-data, file 字段
      Form 参数: kb_id (可选，默认 "knowledge_base")

    响应：
      {"status": "success", "message": "文档 xxx.pdf 已上传并索引"}

    错误：
      - 文件格式不支持 → 400
      - 空文档/分块失败 → 400
      - Markitdown 转换失败 → 500
    """
    # 验证知识库是否存在
    kb = get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    
    try:
        # 保存到对应知识库的上传目录
        kb_upload_dir = get_kb_upload_dir(kb_id)
        fpath = upload_file(file, upload_dir=str(kb_upload_dir))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    md_path = Path(fpath)
    # 若非 md 文件，调用 markitdown 转换
    if md_path.suffix.lower() != ".md":
        try:
            md_path = Path(convert_to_md(fpath))  # convert_to_md 返回字符串，转为 Path
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Markitdown 转换失败: {e}")

    # 读取 md 内容并分块
    texts = parse_document(str(md_path))
    if not texts:
        raise HTTPException(status_code=400, detail="文档为空或无法解析")
    chunks = chunk_texts(texts, is_markdown=True)
    if not chunks:
        raise HTTPException(status_code=400, detail="文档分块失败")

    # 入库到指定知识库
    engine = get_rag_engine(kb_id)
    engine.ingest_document(md_path.name, chunks)

    # 更新知识库的索引标记
    indexed = _load_indexed(kb_id)
    indexed.add(md_path.name)
    _save_indexed(indexed, kb_id)

    return {"status": "success", "message": f"文档 {file.filename} 已上传并索引到知识库「{kb['name']}」"}


@app.get("/api/documents")
async def get_documents(kb_id: str = "knowledge_base"):
    """
    查询指定知识库已索引的文档列表（从向量库 metadata 中去重）。

    查询参数:
      kb_id: 知识库 ID，默认 "knowledge_base"

    响应体示例：
      {
        "documents": [
          {"name": "2024欣生代产品QA.md", "upload_time": "2024-01-15 10:30:00"}
        ]
      }

    upload_time 为文件系统修改时间（mtime），用于前端排序展示。
    """
    # 验证知识库是否存在
    kb = get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    
    # 从知识库的上传目录读取文档列表
    kb_upload_dir = get_kb_upload_dir(kb_id)
    docs_list = list_documents(upload_dir=str(kb_upload_dir))
    return {"documents": docs_list}


@app.get("/api/config/rag-params")
async def get_rag_params():
    """
    读取当前 RAG 检索参数配置。
    """
    import config as _cfg
    return {
        "top_k": _cfg.TOP_K,
        "rerank_top_k": _cfg.RERANK_TOP_K,
        "chunk_size": _cfg.CHUNK_SIZE,
        "chunk_overlap": _cfg.CHUNK_OVERLAP,
        "num_ctx": 4096,  # 从 rag_engine 读取，这里用默认值
    }


class RagParamsRequest(BaseModel):
    top_k: int
    rerank_top_k: int
    chunk_size: int
    chunk_overlap: int
    num_ctx: int


@app.post("/api/config/rag-params")
async def save_rag_params(req: RagParamsRequest):
    """
    保存 RAG 检索参数到 .env 文件并实时生效。
    """
    # 参数校验
    if req.top_k < 1 or req.top_k > 50:
        raise HTTPException(status_code=400, detail="TOP_K 范围: 1~50")
    if req.rerank_top_k < 1 or req.rerank_top_k > req.top_k:
        raise HTTPException(status_code=400, detail="RERANK_TOP_K 不能超过 TOP_K")
    if req.chunk_size < 100 or req.chunk_size > 2000:
        raise HTTPException(status_code=400, detail="CHUNK_SIZE 范围: 100~2000")
    if req.chunk_overlap < 0 or req.chunk_overlap >= req.chunk_size:
        raise HTTPException(status_code=400, detail="CHUNK_OVERLAP 必须小于 CHUNK_SIZE")
    if req.num_ctx < 512 or req.num_ctx > 32768:
        raise HTTPException(status_code=400, detail="num_ctx 范围: 512~32768")

    # 写入 .env
    env_path = Path(__file__).parent / ".env"
    _update_env_file(env_path, {
        "TOP_K": str(req.top_k),
        "RERANK_TOP_K": str(req.rerank_top_k),
        "CHUNK_SIZE": str(req.chunk_size),
        "CHUNK_OVERLAP": str(req.chunk_overlap),
    })

    # 运行时立即生效
    import config as _cfg
    _cfg.TOP_K = req.top_k
    _cfg.RERANK_TOP_K = req.rerank_top_k
    _cfg.CHUNK_SIZE = req.chunk_size
    _cfg.CHUNK_OVERLAP = req.chunk_overlap

    # num_ctx 需要重建 RAG 引擎才能生效
    chunk_size_changed = req.chunk_size != _cfg.CHUNK_SIZE
    if req.num_ctx != 4096 or chunk_size_changed:
        # 更新所有引擎的 LLM num_ctx
        with _rag_engines_lock:
            for engine in _rag_engines.values():
                if engine:
                    engine.llm.num_ctx = req.num_ctx

    print(f"[RagParams] 参数已更新: TOP_K={req.top_k}, RERANK_TOP_K={req.rerank_top_k}, "
          f"CHUNK_SIZE={req.chunk_size}, CHUNK_OVERLAP={req.chunk_overlap}, num_ctx={req.num_ctx}")

    return {"status": "success", "message": "参数已保存并生效"}


@app.get("/api/stats")
async def get_stats(kb_id: str = "knowledge_base"):
    """
    获取指定知识库的统计信息：向量库条目数 + 上传文件数。

    查询参数:
      kb_id: 知识库 ID，默认 "knowledge_base"
             特殊值 "all" 表示获取所有知识库的总和

    响应体示例：
      {
        "vector_documents": 142,
        "uploaded_files": 3,
        "kb_id": "knowledge_base",
        "kb_name": "默认知识库"
      }
      
      或（当 kb_id="all" 时）：
      {
        "vector_documents": 256,
        "uploaded_files": 10,
        "kb_id": "all",
        "kb_name": "所有知识库"
      }
    """
    # 如果是请求所有知识库的统计
    if kb_id == "all":
        all_kbs = list_kbs()
        total_vectors = 0
        total_files = 0
        
        for kb in all_kbs:
            try:
                engine = get_rag_engine(kb["kb_id"])
                stats = engine.vector_store.get_stats(kb["kb_id"])
                total_vectors += stats.get("document_count", 0)
                
                kb_upload_dir = get_kb_upload_dir(kb["kb_id"])
                total_files += len(list_documents(upload_dir=str(kb_upload_dir)))
            except Exception as e:
                print(f"[Stats] 获取知识库 {kb['kb_id']} 统计失败: {e}")
                continue
        
        return {
            "vector_documents": total_vectors,
            "uploaded_files": total_files,
            "kb_id": "all",
            "kb_name": "所有知识库"
        }
    
    # 单个知识库的统计
    kb = get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    
    engine = get_rag_engine(kb_id)
    stats = engine.vector_store.get_stats(kb_id)
    vector_count = stats.get("document_count", 0)
    
    kb_upload_dir = get_kb_upload_dir(kb_id)
    file_count = len(list_documents(upload_dir=str(kb_upload_dir)))
    
    return {
        "vector_documents": vector_count,
        "uploaded_files": file_count,
        "kb_id": kb_id,
        "kb_name": kb["name"]
    }


@app.post("/api/clear-db")
async def clear_db(kb_id: str = "knowledge_base"):
    """
    清空指定知识库的向量数据库（删除 collection）。

    同时清空该知识库的 .indexed 标记文件，使下次启动时重新索引所有文档。

    请求体（可选）:
      {"kb_id": "knowledge_base"}

    响应：
      {"success": true, "message": "向量库已清空"}
    """
    # 验证知识库是否存在
    kb = get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    
    engine = get_rag_engine(kb_id)
    engine.vector_store.clear_collection(kb_id)
    # 清空索引标记，允许重新索引
    _save_indexed(set(), kb_id)
    return {"success": True, "message": f"知识库「{kb['name']}」的向量库已清空"}


@app.delete("/api/documents/{filename}")
async def delete_doc(filename: str, kb_id: str = "knowledge_base"):
    """
    删除文档：从指定知识库的向量库和文件系统中移除指定文档。

    处理流程：
      1. 确定要删除的 .md 文件名（向量库中的 source 标识）
      2. 调用 RagEngine.delete_document 删除向量库中该文件的所有块
      3. 调用 document_processor.cleanup_document 删除文件系统中的文件
      4. 从知识库的 .indexed 标记中移除该文件名

    路径参数：
      filename: 文件名，可以是原始文件（如 "report.pdf"）或 .md 文件
    
    查询参数:
      kb_id: 知识库 ID，默认 "knowledge_base"

    响应：
      {"status": "success", "message": "文档 xxx 已删除", "vectors_removed": int}

    错误：
      - 文件不存在 → 404
      - 删除失败 → 500
    """
    # 验证知识库是否存在
    kb = get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    
    try:
        # 确定要从向量库删除的 .md 文件名
        # 因为入库时使用的是 md_path.name 作为 source
        file_path = Path(filename)
        if file_path.suffix.lower() == ".md":
            md_filename = filename
        else:
            # 原始文件（如 .pdf），需要找到对应的 .md 文件名
            md_filename = file_path.stem + ".md"
        
        engine = get_rag_engine(kb_id)
        vectors_removed = engine.delete_document(md_filename)
        
        # 从知识库的上传目录删除文件
        kb_upload_dir = get_kb_upload_dir(kb_id)
        cleanup_document(filename, upload_dir=str(kb_upload_dir))
        
        # 从知识库的索引标记中移除 .md 文件名
        indexed = _load_indexed(kb_id)
        indexed.discard(md_filename)
        _save_indexed(indexed, kb_id)
        
        return {
            "status": "success",
            "message": f"文档 {filename} 已从知识库「{kb['name']}」删除",
            "vectors_removed": vectors_removed
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")


# ──────────────────────────────────────────────────────────────
# 聊天历史 API
# ──────────────────────────────────────────────────────────────

@app.get("/api/chat-history")
async def get_chat_history(limit: int = 200):
    """
    获取聊天历史记录（从 SQLite 读取）。

    前端页面加载时调用，用于恢复历史消息到对话界面。

    查询参数：
      limit: 最多返回的消息条数，默认 200

    响应体示例：
      {
        "messages": [
          {
            "id": 1,
            "session_id": "abc123",
            "role": "user",
            "content": "欣生代计划A保额多少？",
            "sources": [],
            "created_at": "2024-08-10T10:30:00"
          },
          {
            "id": 2,
            "session_id": "abc123",
            "role": "assistant",
            "content": "计划A年度最高保额为80万元。",
            "sources": [{"index": 1, "source": "产品QA.md", "score": 0.85}],
            "created_at": "2024-08-10T10:30:05"
          }
        ]
      }
    """
    messages = get_history(limit=limit)
    return {"messages": messages}


@app.delete("/api/chat-history")
async def delete_chat_history():
    """
    清空全部聊天历史记录（从 SQLite 删除所有消息）。

    同时会清空前端的对话界面（由前端在收到响应后处理）。

    响应：
      {"status": "success", "message": "聊天记录已清空"}
    """
    clear_history()
    return {"status": "success", "message": "聊天记录已清空"}


# ──────────────────────────────────────────────────────────────
# 知识库管理 API
# ──────────────────────────────────────────────────────────────

@app.get("/api/knowledge-bases")
async def list_knowledge_bases():
    """
    获取所有知识库列表。
    
    响应体示例：
      {
        "knowledge_bases": [
          {
            "id": 1,
            "kb_id": "knowledge_base",
            "name": "默认知识库",
            "description": "系统默认知识库",
            "enabled": 1,
            "created_at": "2024-01-01 00:00:00",
            "document_count": 5,
            "vector_count": 123
          }
        ]
      }
    """
    kbs = list_kbs()
    # 为每个知识库添加统计信息
    for kb in kbs:
        kb_id = kb["kb_id"]
        # 文档数量
        upload_dir = get_kb_upload_dir(kb_id)
        doc_files = [f for f in upload_dir.iterdir() if f.suffix.lower() == ".md" and not f.name.startswith(".")]
        kb["document_count"] = len(doc_files)
        
        # 向量数量
        try:
            vs = VectorStoreManager()
            stats = vs.get_stats(kb_id)
            kb["vector_count"] = stats.get("document_count", 0)
        except Exception:
            kb["vector_count"] = 0
    
    return {"knowledge_bases": kbs}


@app.post("/api/knowledge-bases")
async def create_knowledge_base(req: KBCreateRequest):
    """
    创建新知识库。
    
    请求体：
      {
        "name": "客服知识库",
        "description": "客服部门专用知识库"
      }
    
    响应体：
      {
        "status": "success",
        "knowledge_base": {...}
      }
    """
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="知识库名称不能为空")
    
    try:
        kb = create_kb(name=req.name.strip(), description=req.description.strip())
        return {
            "status": "success",
            "message": f"知识库「{kb['name']}」创建成功",
            "knowledge_base": kb
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建知识库失败: {str(e)}")


@app.put("/api/knowledge-bases/{kb_id}")
async def update_knowledge_base(kb_id: str, req: KBUpdateRequest):
    """
    更新知识库信息（名称、描述、启用状态）。
    
    请求体（部分更新）：
      {
        "name": "新名称",
        "description": "新描述",
        "enabled": 0
      }
    
    响应体：
      {
        "status": "success",
        "knowledge_base": {...}
      }
    """
    kb = get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    
    try:
        updated_kb = update_kb(
            kb_id=kb_id,
            name=req.name.strip() if req.name else None,
            description=req.description.strip() if req.description else None,
            enabled=req.enabled
        )
        return {
            "status": "success",
            "message": "知识库信息已更新",
            "knowledge_base": updated_kb
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新知识库失败: {str(e)}")


@app.delete("/api/knowledge-bases/{kb_id}")
async def delete_knowledge_base(kb_id: str):
    """
    删除知识库及其所有数据（文档、向量、索引标记）。
    
    注意：默认知识库 "knowledge_base" 不允许删除。
    
    响应体：
      {
        "status": "success",
        "message": "知识库已删除"
      }
    """
    if kb_id == "knowledge_base":
        raise HTTPException(status_code=400, detail="默认知识库不允许删除")
    
    kb = get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    
    try:
        # 1. 清空向量库集合
        vs = VectorStoreManager()
        vs.clear_collection(kb_id)
        
        # 2. 删除上传目录
        import shutil
        upload_dir = get_kb_upload_dir(kb_id)
        if upload_dir.exists():
            shutil.rmtree(upload_dir)
        
        # 3. 删除数据库记录
        success = delete_kb(kb_id)
        if not success:
            raise Exception("删除数据库记录失败")
        
        # 4. 从缓存中移除
        with _rag_engines_lock:
            if kb_id in _rag_engines:
                del _rag_engines[kb_id]
        
        return {
            "status": "success",
            "message": f"知识库「{kb['name']}」已删除"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除知识库失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    # 开发模式启动（reload=False 避免二次执行 lifespan）
    uvicorn.run("app:app", host=HOST, port=PORT, reload=False)
