"""
智能客服系统 - 文档处理模块

作者: kimikang

完整上传流程：
  1. 用户上传原始文件（PDF / DOCX / XLSX / PPTX / TXT / MD）
  2. 调用系统命令 `markitdown` 将原始文件转换为 .md 格式
     - 原始文件保留在 uploads 目录，便于追溯
     - 若源文件本身是 .md，跳过转换
  3. 以生成的 .md 文件为标的，使用 tiktoken 分块
  4. 将分块结果写入 ChromaDB 向量库（由 vector_store.py 完成）

依赖：
  - markitdown CLI：pip install markitdown
  - langchain-community TextLoader：读取 .md 文本
  - langchain-text-splitters：文档分块
"""
import subprocess
from pathlib import Path
from typing import List

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import CHUNK_SIZE, CHUNK_OVERLAP, UPLOAD_DIR

# ──────────────────────────────────────────────────────────────
# 支持的文件格式集合
# ──────────────────────────────────────────────────────────────

# 不需要转换的原生 Markdown 格式
_MD_NATIVE = {".md"}

# 需要通过 markitdown 转换为 .md 的格式
_CONVERTIBLE = {".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt"}

# 所有允许上传的格式（供 app.py 做文件类型校验）
ALLOWED_EXTENSIONS = _MD_NATIVE | _CONVERTIBLE


# ──────────────────────────────────────────────────────────────
# 文件转换
# ──────────────────────────────────────────────────────────────

def convert_to_md(src_path: str) -> str:
    """
    调用 markitdown CLI 将原始文件转换为同名 .md 文件，保存在同目录下。

    转换规则：
      - 若源文件已是 .md，直接返回源路径（无需转换）
      - 若同名 .md 已存在，直接复用（幂等，避免重复转换）
      - 否则执行 markitdown <src> -o <src>.md

    Args:
        src_path: 原始文件的绝对路径

    Returns:
        生成的 .md 文件路径（字符串）

    Raises:
        RuntimeError: markitdown 未安装、转换失败或未生成输出文件
    """
    src = Path(src_path)

    # 原生 MD 文件无需转换
    if src.suffix.lower() == ".md":
        return str(src)

    md_path = src.with_suffix(".md")

    # 已存在则直接复用，实现幂等
    if md_path.exists():
        return str(md_path)

    try:
        result = subprocess.run(
            ["markitdown", str(src), "-o", str(md_path)],
            capture_output=True,   # 捕获 stdout/stderr
            text=True,
            timeout=120,           # 最多等 2 分钟，防止大文件卡死
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"markitdown 转换失败 (exit {result.returncode}): {result.stderr.strip()}"
            )
        if not md_path.exists():
            raise RuntimeError(f"markitdown 未生成输出文件: {md_path}")
        return str(md_path)
    except FileNotFoundError:
        # 系统 PATH 里找不到 markitdown 命令
        raise RuntimeError("markitdown 命令未找到，请先安装: pip install markitdown")


# ──────────────────────────────────────────────────────────────
# 文档解析
# ──────────────────────────────────────────────────────────────

def parse_document(file_path: str) -> List[str]:
    """
    读取 .md 文件的原始文本，返回非空文本段落列表。

    说明：所有上传文件在入库前都已转换为 .md，因此这里统一用
    TextLoader 读取，保留完整的 Markdown 结构（标题、表格等），
    由后续分块器按 Markdown 语义切分。

    Args:
        file_path: .md 文件的绝对路径

    Returns:
        非空文本字符串列表（LangChain Document.page_content 的集合）

    Raises:
        RuntimeError: 文件读取失败
    """
    try:
        loader = TextLoader(file_path, encoding="utf-8")
        pages = loader.load()
        # 过滤空内容，去除首尾空白
        texts = [page.page_content.strip() for page in pages if page.page_content.strip()]
        return texts
    except Exception as e:
        raise RuntimeError(f"文档读取失败: {file_path}, 错误: {e}")


# ──────────────────────────────────────────────────────────────
# 文本分块
# ──────────────────────────────────────────────────────────────

def chunk_texts(texts: List[str], is_markdown: bool = True) -> List[str]:
    """
    将文本列表切分为固定大小的语义块，供向量化存储。

    分块策略（Markdown 模式）：
      优先按标题层级（##、###、####）分割，保持章节完整性；
      章节过长时再按段落（双换行）→ 单行 → 标点逐级细分。

    Args:
        texts:       待切分的文本字符串列表
        is_markdown: 是否使用 Markdown 语义分隔符（默认 True）

    Returns:
        切分后的文本块列表（每块长度不超过 CHUNK_SIZE token）
    """
    if is_markdown:
        # Markdown 专用分隔符：优先按标题层级切分，保留文档结构
        separators = ["\n## ", "\n### ", "\n#### ", "\n\n", "\n", "。", ".", " ", ""]
    else:
        # 普通文本分隔符
        separators = ["\n\n", "\n", "。", ".", "；", ";", " ", ""]

    # 使用 tiktoken 计算 token 数（与 LLM 的 token 计算方式一致）
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=CHUNK_SIZE,      # 每块最大 token 数
        chunk_overlap=CHUNK_OVERLAP, # 相邻块重叠 token 数，防止语义截断
        separators=separators,
    )

    chunks = []
    for text in texts:
        chunk_list = splitter.split_text(text)
        chunks.extend(chunk_list)
    return chunks


# ──────────────────────────────────────────────────────────────
# 文件上传保存
# ──────────────────────────────────────────────────────────────

def upload_file(file, filename: str = None, upload_dir: str = None) -> str:
    """
    将上传的文件保存到指定的 uploads 目录。

    仅保存原始文件，不做格式转换（转换由 app.py 调用 convert_to_md 完成）。

    Args:
        file:       FastAPI UploadFile 对象（包含文件名和文件流）
        filename:   可选，覆盖原始文件名
        upload_dir: 可选，上传目录路径，默认使用 config.UPLOAD_DIR

    Returns:
        原始文件的保存路径（字符串）

    Raises:
        ValueError: 文件格式不在 ALLOWED_EXTENSIONS 中
    """
    if filename is None:
        filename = file.filename
    
    if upload_dir is None:
        upload_dir = UPLOAD_DIR

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的文件格式: {ext}，支持格式: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    raw_path = Path(upload_dir) / filename
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    content = file.file.read()
    with open(raw_path, "wb") as f:
        f.write(content)

    return str(raw_path)


# ──────────────────────────────────────────────────────────────
# 文档列表
# ──────────────────────────────────────────────────────────────

def list_documents(upload_dir: str = None) -> List[dict]:
    """
    列出指定 uploads 目录中已上传的原始文档。

    过滤规则：
      - 跳过隐藏文件（以 . 开头，如 .indexed）
      - 跳过不在 ALLOWED_EXTENSIONS 中的文件类型
      - 跳过"转换产物"：若一个 .md 文件存在同名的原始文件（.pdf/.docx 等），
        则该 .md 是由 markitdown 自动生成的，不单独列出

    每条记录包含：
      filename   : 文件名
      size       : 文件大小（字节）
      created    : 创建时间戳
      md_ready   : 是否已有对应 .md 文件（即已完成转换）
      md_filename: 对应 .md 文件名（若存在）

    Args:
        upload_dir: 上传目录路径，默认使用 config.UPLOAD_DIR

    Returns:
        文档信息字典列表
    """
    if upload_dir is None:
        upload_dir = UPLOAD_DIR
    
    docs = []
    upload_path = Path(upload_dir)
    if not upload_path.exists():
        return docs

    for f in upload_path.iterdir():
        if not f.is_file():
            continue
        # 跳过隐藏文件（.indexed 等系统文件）
        if f.name.startswith("."):
            continue
        ext = f.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue

        # 判断该 .md 是否是转换产物（存在同名原始文件）
        if ext == ".md":
            has_source = any(
                (upload_path / (f.stem + orig_ext)).exists()
                for orig_ext in (".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt")
            )
            if has_source:
                continue  # 转换产物，不单独列出，避免列表重复

        # 检查是否已有对应的 .md 文件
        md_file = upload_path / (f.stem + ".md")
        docs.append({
            "filename":    f.name,
            "size":        f.stat().st_size,
            "created":     f.stat().st_ctime,
            "md_ready":    md_file.exists(),         # True 表示已转换，可直接入库
            "md_filename": md_file.name if md_file.exists() else None,
        })

    return docs


# ──────────────────────────────────────────────────────────────
# 文档删除
# ──────────────────────────────────────────────────────────────

def cleanup_document(filename: str, upload_dir: str = None) -> bool:
    """
    删除指定文档文件，同时删除其 markitdown 转换产生的 .md 文件（如有）。

    注意：此函数只删除磁盘文件，向量库中的对应数据由
    app.py 的 delete_document 接口单独调用 vector_store.delete_by_source 清理。

    Args:
        filename:   要删除的文件名（仅文件名，不含目录路径）
        upload_dir: 上传目录路径，默认使用 config.UPLOAD_DIR

    Returns:
        True 表示原始文件已成功删除，False 表示文件不存在
    """
    if upload_dir is None:
        upload_dir = UPLOAD_DIR
    
    upload_path = Path(upload_dir)
    doc_path = upload_path / filename
    deleted = False

    # 删除原始文件
    if doc_path.exists():
        doc_path.unlink()
        deleted = True

    # 若原始文件不是 .md，则同步删除自动生成的同名 .md
    if Path(filename).suffix.lower() != ".md":
        md_path = upload_path / (Path(filename).stem + ".md")
        if md_path.exists():
            md_path.unlink()

    return deleted
