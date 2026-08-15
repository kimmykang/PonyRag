"""
智能客服系统 - 文档处理模块

作者: kimikang

完整上传流程：
  1. 用户上传原始文件（PDF / DOCX / XLSX / PPTX / TXT / MD）
  2. 调用 markitdown Python API 将原始文件转换为 .md 格式
     - 若配置了 OCR_MODEL，启用 markitdown-ocr 插件，自动 OCR 图片型文档
     - 若源文件本身是 .md，跳过转换
  3. 以生成的 .md 文件为标的，使用 tiktoken 分块
  4. 将分块结果写入 ChromaDB 向量库（由 vector_store.py 完成）

依赖：
  - markitdown：pip install markitdown
  - markitdown-ocr（可选）：pip install markitdown-ocr openai
  - langchain-community TextLoader：读取 .md 文本
  - langchain-text-splitters：文档分块
"""
import subprocess
from pathlib import Path
from typing import List

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import CHUNK_SIZE, CHUNK_OVERLAP, UPLOAD_DIR, OLLAMA_BASE_URL, OCR_MODEL

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
    将原始文件转换为同名 .md 文件，保存在同目录下。

    转换策略：
      1. 若源文件已是 .md，直接返回
      2. 若同名 .md 已存在，直接复用（幂等）
      3. 优先使用 markitdown Python API 转换：
         - 若配置了 OCR_MODEL，启用 markitdown-ocr 插件，
           自动对图片型 PDF/扫描件进行 OCR
         - OCR 使用本地 Ollama（OpenAI 兼容接口），无需联网
      4. Python API 失败时回退到 CLI 命令行

    Args:
        src_path: 原始文件的绝对路径

    Returns:
        生成的 .md 文件路径（字符串）

    Raises:
        RuntimeError: 转换失败且回退也失败
    """
    src = Path(src_path)

    # 原生 MD 文件无需转换
    if src.suffix.lower() == ".md":
        return str(src)

    md_path = src.with_suffix(".md")

    # 已存在则直接复用，实现幂等
    if md_path.exists():
        return str(md_path)

    # ── 优先：Python API（支持 OCR）────────────────────────────
    try:
        from markitdown import MarkItDown

        if OCR_MODEL:
            # 使用 Ollama 本地视觉模型做 OCR
            try:
                from openai import OpenAI
                ollama_client = OpenAI(
                    base_url=f"{OLLAMA_BASE_URL}/v1",
                    api_key="ollama",  # Ollama 不校验 key，填任意值即可
                )
                md_converter = MarkItDown(
                    enable_plugins=True,
                    llm_client=ollama_client,
                    llm_model=OCR_MODEL,
                )
                print(f"[Convert] 使用 OCR 模型 {OCR_MODEL} 转换: {src.name}")
            except ImportError:
                # openai 或 markitdown-ocr 未安装，回退到普通转换
                print(f"[Convert] markitdown-ocr 或 openai 未安装，跳过 OCR")
                md_converter = MarkItDown()
        else:
            md_converter = MarkItDown()

        result = md_converter.convert(str(src))
        text = result.text_content or ""

        if not text.strip():
            raise RuntimeError("markitdown Python API 返回空内容")

        md_path.write_text(text, encoding="utf-8")
        print(f"[Convert] Python API 转换成功: {src.name} → {md_path.name}")
        return str(md_path)

    except Exception as e:
        print(f"[Convert] Python API 失败，尝试 CLI 回退: {e}")

    # ── 回退：CLI 命令行 ────────────────────────────────────────
    try:
        result = subprocess.run(
            ["markitdown", str(src), "-o", str(md_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"markitdown CLI 失败 (exit {result.returncode}): {result.stderr.strip()}"
            )
        if not md_path.exists():
            raise RuntimeError("markitdown CLI 未生成输出文件")
        print(f"[Convert] CLI 转换成功: {src.name} → {md_path.name}")
        return str(md_path)
    except FileNotFoundError:
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
    列出指定 uploads 目录中已上传并转换完成的文档。

    展示策略：
      - 以 .md 文件为准（所有文档最终都转为 .md 入库）
      - 若某 .md 存在同名原始文件（.pdf/.docx 等），显示原始文件名（更直观）
      - 若只有 .md（原生 md 上传，或原始文件已删除），显示 .md 文件名
      - 跳过隐藏文件（以 . 开头）

    每条记录包含：
      filename   : 展示用文件名（优先原始文件名，其次 .md 文件名）
      size       : 文件大小（字节）
      created    : 创建时间戳
      md_ready   : 始终为 True（列出的都是已有 .md 的文档）
      md_filename: 对应 .md 文件名

    Args:
        upload_dir: 上传目录路径，默认使用 config.UPLOAD_DIR

    Returns:
        文档信息字典列表
    """
    if upload_dir is None:
        upload_dir = UPLOAD_DIR

    upload_path = Path(upload_dir)
    if not upload_path.exists():
        return []

    docs = []
    seen_stems = set()  # 防止同一文档重复出现

    for f in sorted(upload_path.iterdir()):
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue

        ext = f.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue

        stem = f.stem

        if ext == ".md":
            # .md 文件：直接列出
            if stem in seen_stems:
                continue
            # 检查是否存在同名原始文件（用原始文件名展示更直观）
            display_name = f.name
            for orig_ext in (".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt"):
                orig = upload_path / (stem + orig_ext)
                if orig.exists():
                    display_name = orig.name
                    break
            seen_stems.add(stem)
            docs.append({
                "filename":    display_name,
                "size":        f.stat().st_size,
                "created":     f.stat().st_ctime,
                "md_ready":    True,
                "md_filename": f.name,
            })
        else:
            # 原始文件（pdf/docx 等）：只在没有同名 .md 时列出（转换失败的情况）
            if stem in seen_stems:
                continue
            md_file = upload_path / (stem + ".md")
            if md_file.exists():
                continue  # 已有 .md，会在上面的 .md 分支处理
            seen_stems.add(stem)
            docs.append({
                "filename":    f.name,
                "size":        f.stat().st_size,
                "created":     f.stat().st_ctime,
                "md_ready":    False,
                "md_filename": None,
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
