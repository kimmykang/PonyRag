"""
智能客服系统 - 文档处理模块

作者: kimikang

完整上传流程：
  1. 用户上传原始文件（PDF / DOCX / XLSX / PPTX / TXT / MD）
  2. 调用 markitdown Python API 将原始文件转换为 .md 格式
     - 若配置了 _dp_cfg.OCR_MODEL，启用 markitdown-ocr 插件，自动 OCR 图片型文档
     - 若源文件本身是 .md，跳过转换
  3. 以生成的 .md 文件为标的，使用 tiktoken 分块
  4. 将分块结果写入 ChromaDB 向量库（由 vector_store.py 完成）

依赖：
  - markitdown：pip install markitdown
  - markitdown-ocr（可选）：pip install markitdown-ocr openai
  - langchain-community TextLoader：读取 .md 文本
  - langchain-text-splitters：文档分块
"""
import re
import subprocess
import httpx
from pathlib import Path
from typing import List

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import CHUNK_SIZE, CHUNK_OVERLAP, UPLOAD_DIR, OLLAMA_BASE_URL, EMBED_MODEL
import config as _dp_cfg  # used for dynamic _dp_cfg.OCR_MODEL lookup

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
# LLM 自动检测切分方式
# ──────────────────────────────────────────────────────────────

def auto_detect_chunk_method(md_path: str) -> str:
    """
    读取 .md 文件前 1500 字符，调用 Ollama 对话模型判断最适合的切分方式。

    返回值: "markdown" | "recursive" | "semantic"
    失败时降级返回 "recursive"

    判断逻辑：
      - markdown  — 文档有明显的 #/## 标题层级（结构化文档）
      - semantic  — 叙事型长文，无明显标题，段落间语义跳跃
      - recursive — 通用文档，或无法判断时的默认值
    """
    from config import CHAT_MODEL, OLLAMA_BASE_URL, THINKING
    try:
        content = Path(md_path).read_text(encoding="utf-8")
        sample = content[:1500].strip()
        if not sample:
            return "recursive"

        prompt = (
            "/no_think\n"
            "请分析以下文档片段，判断最适合的文本切分方式，只返回一个英文单词（markdown / recursive / semantic）：\n\n"
            "切分方式说明：\n"
            "- markdown  ：文档有明显的 #/## 标题层级结构（如产品手册、条款、API文档、表格型知识库）\n"
            "- semantic  ：叙事型长文，无明显标题，段落间有语义跳跃（如新闻、书籍、报告）\n"
            "- recursive ：通用文档，混合结构，或不确定时\n\n"
            f"文档片段：\n{sample}\n\n"
            "只返回一个词（markdown 或 recursive 或 semantic），不要解释："
        )

        with httpx.Client(transport=httpx.HTTPTransport(), timeout=30) as client:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": CHAT_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "think": THINKING,
                    "options": {"temperature": 0, "num_ctx": 2048},
                },
            )
            resp.raise_for_status()
            result = resp.json().get("response", "").strip().lower()

        # 提取第一个合法词
        for word in result.split():
            clean = word.strip(".,;:\"'")
            if clean in ("markdown", "recursive", "semantic"):
                print(f"[AutoDetect] {Path(md_path).name} → {clean}")
                return clean

        print(f"[AutoDetect] 无法解析结果 '{result}'，降级到 recursive")
        return "recursive"

    except Exception as e:
        print(f"[AutoDetect] 检测失败: {e}，降级到 recursive")
        return "recursive"


# ──────────────────────────────────────────────────────────────
# 文件转换
# ──────────────────────────────────────────────────────────────

def _ocr_pdf_with_vision(pdf_path: str) -> str:
    """
    用 OCR 视觉模型（Ollama）逐页识别纯图片 PDF。

    将每页渲染为图片，base64 编码后调用 Ollama 多模态接口提取文字。
    用于 pdfplumber 无法提取到文字的扫描件 / 图片型 PDF。

    Returns:
        提取到的 Markdown 文本；失败时返回空字符串
    """
    try:
        import pymupdf as fitz  # PyMuPDF (fitz is the legacy alias)
    except ImportError:
        print(f"[Convert] PyMuPDF 未安装，OCR 降级跳过。可运行: pip install pymupdf")
        return ""

    import base64, httpx as _httpx

    print(f"[Convert] 图片型 PDF，启动 OCR 视觉模型: {_dp_cfg.OCR_MODEL}  文件: {Path(pdf_path).name}")
    all_pages_md = []

    doc = fitz.open(pdf_path)
    total = len(doc)
    print(f"[Convert]   共 {total} 页，逐页 OCR...")

    for page_num in range(total):
        page = doc[page_num]
        # 渲染为 2x 分辨率图片，提升 OCR 精度
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        prompt = (
            "请识别图片中的所有文字内容，保持原始格式。"
            "如有表格，用 Markdown 表格格式输出；如有标题，用 # 标记。"
            "只输出识别到的文字内容，不要额外说明。"
        )

        try:
            with _httpx.Client(transport=_httpx.HTTPTransport(), timeout=60) as client:
                resp = client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": _dp_cfg.OCR_MODEL,
                        "prompt": prompt,
                        "images": [img_b64],
                        "stream": False,
                        "options": {"temperature": 0},
                    },
                )
                resp.raise_for_status()
                page_text = resp.json().get("response", "").strip()
                if page_text:
                    all_pages_md.append(f"## Page {page_num + 1}\n\n{page_text}")
                    print(f"[Convert]   第{page_num + 1}页 OCR: {len(page_text)} 字符")
                else:
                    print(f"[Convert]   第{page_num + 1}页 OCR: 未识别到内容")
        except Exception as e:
            print(f"[Convert]   第{page_num + 1}页 OCR 失败: {e}")

    doc.close()
    result = "\n\n".join(all_pages_md)
    print(f"[Convert]   OCR 完成: {len(result)} 字符")
    return result


def _convert_pdf_smart(pdf_path: str) -> str:
    """
    用 pdfplumber 智能转换 PDF：
    - 表格：精确提取，正确处理合并单元格，转为标准 Markdown 表格
    - 文字页：直接提取文本
    - 图片页（扫描件）：自动降级到 OCR 视觉模型处理
    """
    try:
        import pdfplumber as _plumber
    except ImportError:
        # pdfplumber 不可用，降级为 markitdown 普通转换
        from markitdown import MarkItDown
        print(f"[Convert] pdfplumber 不可用，使用普通转换: {Path(pdf_path).name}")
        result = MarkItDown().convert(pdf_path)
        return result.text_content or ""

    print(f"[Convert] pdfplumber 智能转换: {Path(pdf_path).name} → {Path(pdf_path).parent.name}/{Path(pdf_path).name}")

    all_pages_md = []
    text_page_count = 0

    with _plumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"[Convert]   共 {total} 页")

        for page_num, page in enumerate(pdf.pages, 1):
            page_md_parts = []

            # 提取表格
            tables = page.extract_tables()
            table_bboxes = []

            for table_obj in page.find_tables():
                table_bboxes.append(table_obj.bbox)

            if tables:
                table_count = len(tables)
                for table in tables:
                    if not table or len(table) < 1:
                        continue
                    # 展开合并单元格（None 继承同列上一行的值）
                    expanded = []
                    prev_row = ['' ] * max(len(r) for r in table)
                    for row in table:
                        new_row = []
                        for j in range(len(prev_row)):
                            cell = row[j] if j < len(row) else None
                            if cell is None and prev_row[j]:
                                new_row.append(prev_row[j])
                            else:
                                new_row.append(cell or '')
                        expanded.append(new_row)
                        prev_row = new_row

                    def cell_md(c):
                        """将单元格内容转为 Markdown 安全文本：换行转 <br>，去首尾空白"""
                        return str(c).replace('\n', '<br>').strip() if c else ''

                    if len(expanded) >= 1:
                        header = expanded[0]
                        data = expanded[1:] if len(expanded) > 1 else []
                        md_table = '| ' + ' | '.join(cell_md(h) for h in header) + ' |\n'
                        md_table += '| ' + ' | '.join('---' for _ in header) + ' |\n'
                        for row in data:
                            md_table += '| ' + ' | '.join(cell_md(c) for c in row) + ' |\n'
                        page_md_parts.append(md_table.strip())
                print(f"[Convert]   第{page_num}页: {table_count}张表格, {sum(len(t) for t in tables)}行数据")

            # 提取非表格区域的文字
            if table_bboxes:
                # 过滤掉表格区域，只提取非表格文字
                text_outside = page.filter(
                    lambda obj: obj.get('object_type') == 'char' and
                    not any(
                        bbox[0] <= obj['x0'] <= bbox[2] and
                        bbox[1] <= obj['top'] <= bbox[3]
                        for bbox in table_bboxes
                    )
                ).extract_text()
                if text_outside and text_outside.strip():
                    page_md_parts.insert(0, text_outside.strip())
            else:
                text = page.extract_text()
                if text and text.strip():
                    page_md_parts.append(text.strip())

            if page_md_parts:
                all_pages_md.append(f"## Page {page_num}\n\n" + "\n\n".join(page_md_parts))
                text_page_count += 1
            elif _dp_cfg.OCR_MODEL:
                # ── 逐页 OCR 降级：本页 pdfplumber 未提取到内容，单独 OCR ──
                # 失败时自动重试 3 次（间隔 30 秒），应对模型被占用导致的超时
                print(f"[Convert]   第{page_num}页无文字内容，启动单页 OCR（模型: {_dp_cfg.OCR_MODEL}）...")
                import pymupdf as _fitz, base64 as _b64, httpx as _httpx2, time as _time
                _doc = _fitz.open(pdf_path)
                _page = _doc[page_num - 1]
                _mat = _fitz.Matrix(2, 2)
                _pix = _page.get_pixmap(matrix=_mat)
                _img_b64 = _b64.b64encode(_pix.tobytes("png")).decode("utf-8")
                _doc.close()

                _ocr_prompt = (
                    "请识别图片中的所有文字内容，保持原始格式。"
                    "如有表格，用 Markdown 表格格式输出；如有标题，用 # 标记。"
                    "只输出识别到的文字内容，不要额外说明。"
                )

                _page_text = ""
                try:
                    with _httpx2.Client(transport=_httpx2.HTTPTransport(), timeout=60) as _client:
                        _resp = _client.post(
                            f"{OLLAMA_BASE_URL}/api/generate",
                            json={
                                "model": _dp_cfg.OCR_MODEL,
                                "prompt": _ocr_prompt,
                                "images": [_img_b64],
                                "stream": False,
                                "options": {"temperature": 0},
                            },
                        )
                        _resp.raise_for_status()
                        _page_text = _resp.json().get("response", "").strip()
                except Exception as _ocr_e:
                    print(f"[Convert]   第{page_num}页 OCR 失败: {_ocr_e}")

                if _page_text:
                    all_pages_md.append(f"## Page {page_num}\n\n{_page_text}")
                    print(f"[Convert]   第{page_num}页 OCR: {len(_page_text)} 字符")
                else:
                    print(f"[Convert]   第{page_num}页 OCR: 未识别到内容")

    result = "\n\n".join(all_pages_md)
    print(f"[Convert]   转换完成: {len(result)} 字符，文字页={text_page_count}/{total}")

    # 注意：图片页已在逐页处理阶段单独 OCR，无需整体降级
    return result




def _fix_broken_tables(md_path, pdf_path: str = None) -> None:
    """
    修复文档转换后表格格式错乱的问题（主要针对非 PDF 文件）。
    PDF 文件已由 _convert_pdf_smart 用 pdfplumber 精确处理，无需此函数修复。

    通用检测策略：找到连续的无 | 分隔符的多列文字行（疑似乱格的表格区域），
    调用 LLM 修复为标准 Markdown 表格格式。
    不针对特定词语，适用于任何格式混乱的对比型表格。
    """
    from pathlib import Path as _Path
    import re as _re

    md_path = _Path(md_path)
    content = md_path.read_text(encoding="utf-8")

    # 通用检测：找连续的、看起来像多列数据但没有 | 的文字块
    # 特征：3行以上连续行，每行有多个空白分隔的"列"，且整块里没有 | 分隔符
    # 同时至少有一行像"标题行"（含有重复的模式，如 A B C / 一 二 三 / 选项1 选项2）
    pattern = _re.compile(
        # 匹配连续 5 行以上的无 | 的文本块
        r'((?:(?!\|).+\n){5,})',
        _re.MULTILINE
    )
    matches = [m for m in pattern.finditer(content)
               # 过滤：块内至少有一行看起来有多列（含 2+ 个多空格分隔）
               if _re.search(r'\S+\s{2,}\S+\s{2,}\S+', m.group(1))]

    if not matches:
        return

    try:
        from config import CHAT_MODEL, OLLAMA_BASE_URL, THINKING
        import httpx as _httpx

        fixed_content = content
        for m in reversed(matches):
            broken_block = m.group(1).strip()
            if not broken_block:
                continue
            print(f"[Convert] LLM 修复疑似混乱表格 ({len(broken_block)} 字符)")
            prompt = (
                "/no_think\n"
                "以下是从文档中提取的文本块，疑似是一张格式混乱的表格。"
                "原文档中可能有合并单元格、跨行内容等，导致提取后列数据错位。\n\n"
                "如果它确实是表格，请修复为标准 Markdown 表格（使用 | 分隔列），"
                "合并单元格的值展开到每一行；\n"
                "如果它不是表格而是普通段落，原样返回。\n\n"
                f"文本块：\n{broken_block}\n\n"
                "只返回修复结果，不要解释："
            )
            resp = _httpx.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": CHAT_MODEL, "prompt": prompt, "stream": False,
                    "think": THINKING, "options": {"temperature": 0, "num_ctx": 8192},
                },
                timeout=120,
            )
            resp.raise_for_status()
            fixed_block = resp.json().get("response", "").strip()
            # 只有返回结果包含 | 且比原文更结构化才替换
            if fixed_block and '|' in fixed_block and fixed_block != broken_block:
                fixed_content = (fixed_content[:m.start()] + fixed_block +
                                 "\n\n" + fixed_content[m.end():])
                print(f"[Convert] LLM 修复表格: {md_path.name}")

        if fixed_content != content:
            md_path.write_text(fixed_content, encoding="utf-8")
            print(f"[Convert] 表格后处理完成: {md_path.name}")

    except Exception as e:
        print(f"[Convert] 表格后处理跳过（{e}）")


def convert_to_md(src_path: str) -> str:
    """
    将原始文件转换为同名 .md 文件，保存在同目录下。

    转换策略：
      1. 若源文件已是 .md，直接返回
      2. 若同名 .md 已存在，直接复用（幂等）
      3. 优先使用 markitdown Python API 转换：
         - 若配置了 _dp_cfg.OCR_MODEL，启用 markitdown-ocr 插件，
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

    # ── 优先：Python API────────────────────────────────────────
    # 策略：
    #   - 非 PDF 文件：普通转换 + 表格后处理
    #   - PDF 文件：逐页判断，图片页用 OCR 视觉模型，文字页直接提取，最后合并 + 表格后处理
    try:
        from markitdown import MarkItDown

        suffix = src.suffix.lower()

        if suffix == ".pdf" and _dp_cfg.OCR_MODEL:
            text = _convert_pdf_smart(str(src))
            if not text.strip():
                # _convert_pdf_smart 内部已尝试 OCR 降级，仍为空则真的无内容
                raise RuntimeError("PDF 转换返回空内容（pdfplumber 和 OCR 均未提取到文字）")
        else:
            md_converter = MarkItDown()
            print(f"[Convert] 转换: {src.name}")
            result = md_converter.convert(str(src))
            text = result.text_content or ""
            if not text.strip():
                raise RuntimeError("markitdown Python API 返回空内容")

        md_path.write_text(text, encoding="utf-8")
        print(f"[Convert] 转换成功: {src.name} → {md_path.name}")
        # 后处理：用 pdfplumber 精确修复表格（降级用 LLM）
        if src.suffix.lower() == ".pdf":
            _fix_broken_tables(md_path, pdf_path=str(src))
        else:
            _fix_broken_tables(md_path)
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
        if src.suffix.lower() == ".pdf":
            _fix_broken_tables(md_path, pdf_path=str(src))
        else:
            _fix_broken_tables(md_path)
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

def chunk_texts(
    texts: List[str],
    is_markdown: bool = True,
    method: str = None,
    chunk_size: int = None,
    chunk_overlap: int = None,
) -> List[str]:
    """
    将文本列表切分为固定大小的语义块，供向量化存储。

    参数优先级：显式传入 > config.CHUNK_METHOD / CHUNK_SIZE / CHUNK_OVERLAP

    切分策略（method）：
      fixed     — 严格按字符数截断，块大小最均匀
      recursive — 递归字符切分（默认），优先按标点/空行逐级细分
      markdown  — 按 Markdown 标题树切分，保留章节上下文
      semantic  — 语义相似度切分，块大小不固定（较慢）

    Args:
        texts:        待切分的文本字符串列表
        is_markdown:  是否为 Markdown 格式（影响 recursive 的分隔符）
        method:       切分方式，None 则读 config.CHUNK_METHOD
        chunk_size:   分块大小，None 则读 config.CHUNK_SIZE
        chunk_overlap:重叠大小，None 则读 config.CHUNK_OVERLAP

    Returns:
        切分后的文本块列表
    """
    from config import CHUNK_METHOD, CHUNK_SIZE, CHUNK_OVERLAP
    _method  = (method        or CHUNK_METHOD).strip().lower()
    _size    = chunk_size    if chunk_size    is not None else CHUNK_SIZE
    _overlap = chunk_overlap if chunk_overlap is not None else CHUNK_OVERLAP

    print(f"[Chunker] method={_method}, chunk_size={_size}, chunk_overlap={_overlap}, texts={len(texts)}")

    if _method == "fixed":
        return _chunk_fixed(texts, _size, _overlap)
    elif _method == "markdown":
        return _chunk_by_markdown_headers(texts, _size, _overlap)
    elif _method == "semantic":
        return _chunk_by_semantic(texts, _size, _overlap)
    else:
        return _chunk_recursive(texts, is_markdown, _size, _overlap)


def _chunk_fixed(texts: List[str], chunk_size: int = None, chunk_overlap: int = None) -> List[str]:
    """固定大小切分，严格按字符数，不寻找语义边界。"""
    from config import CHUNK_SIZE, CHUNK_OVERLAP
    _size    = chunk_size    if chunk_size    is not None else CHUNK_SIZE
    _overlap = chunk_overlap if chunk_overlap is not None else CHUNK_OVERLAP
    from langchain_text_splitters import CharacterTextSplitter
    splitter = CharacterTextSplitter(
        separator="",
        chunk_size=_size * 3,
        chunk_overlap=_overlap * 3,
        length_function=len,
    )
    chunks = []
    for text in texts:
        chunks.extend(splitter.split_text(text))
    return chunks


def _chunk_recursive(texts: List[str], is_markdown: bool = True, chunk_size: int = None, chunk_overlap: int = None) -> List[str]:
    """递归字符切分，优先按标点/空行逐级细分。"""
    from config import CHUNK_SIZE, CHUNK_OVERLAP
    _size    = chunk_size    if chunk_size    is not None else CHUNK_SIZE
    _overlap = chunk_overlap if chunk_overlap is not None else CHUNK_OVERLAP

    if is_markdown:
        # \n 降到句末标点之后，避免把多行 Markdown 表格（每行一个 \n）切碎
        # 表格行只有 \n 分隔，\n 优先级高会导致表头和数据分进不同 chunk
        separators = ["\n## ", "\n### ", "\n#### ", "\n\n", "。", ".", "\n", " ", ""]
    else:
        separators = ["\n\n", "。", ".", "；", ";", "\n", " ", ""]

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=_size,
        chunk_overlap=_overlap,
        separators=separators,
    )
    chunks = []
    for text in texts:
        chunks.extend(splitter.split_text(text))
    return chunks


def _chunk_by_markdown_headers(texts: List[str], chunk_size: int = None, chunk_overlap: int = None) -> List[str]:
    """
    Markdown 标题树切分。按 #/##/###/#### 切出章节，标题路径拼入块开头，超长章节二次切分。
    """
    from config import CHUNK_SIZE, CHUNK_OVERLAP
    _size    = chunk_size    if chunk_size    is not None else CHUNK_SIZE
    _overlap = chunk_overlap if chunk_overlap is not None else CHUNK_OVERLAP

    from langchain_text_splitters import MarkdownHeaderTextSplitter

    headers_to_split = [
        ("#",    "h1"),
        ("##",   "h2"),
        ("###",  "h3"),
        ("####", "h4"),
    ]
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split,
        strip_headers=True,
    )

    secondary = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=_size,
        chunk_overlap=_overlap,
        separators=["\n\n", "。", ".", "\n", " ", ""],
    )

    chunks = []
    for text in texts:
        md_docs = md_splitter.split_text(text)
        for doc in md_docs:
            meta = doc.metadata
            title_path = " > ".join(v for k, v in sorted(meta.items()) if v) if meta else ""
            content = doc.page_content.strip()
            if not content:
                continue
            full_chunk = f"[{title_path}]\n{content}" if title_path else content
            sub_chunks = secondary.split_text(full_chunk)
            # 二次切分后，除第一块外后续子块不含标题前缀，需补回
            # 使得每个 chunk 都能独立理解其所属章节
            prefix = f"[{title_path}]\n" if title_path else ""
            for j, sub in enumerate(sub_chunks):
                if j == 0 or not prefix:
                    chunks.append(sub)
                else:
                    # 避免重复添加（极端情况下 secondary 可能保留了前缀）
                    if not sub.startswith(prefix):
                        chunks.append(prefix + sub)
                    else:
                        chunks.append(sub)

    if len(chunks) < 2:
        print("[Chunker] markdown 模式切分结果不足，降级到 recursive")
        return _chunk_recursive(texts, is_markdown=True, chunk_size=_size, chunk_overlap=_overlap)

    return chunks


def _chunk_by_semantic(texts: List[str], chunk_size: int = None, chunk_overlap: int = None) -> List[str]:
    """
    语义相似度切分。按句拆分 → Ollama embedding → 余弦相似度找跳变点 → 超长段二次截断。
    """
    from config import CHUNK_SIZE, CHUNK_OVERLAP
    _size    = chunk_size    if chunk_size    is not None else CHUNK_SIZE
    _overlap = chunk_overlap if chunk_overlap is not None else CHUNK_OVERLAP

    # ── 句子分割 ────────────────────────────────────────────────
    # 按中英文句末标点切句；空行（段落分隔）也作为切分点，但单个换行不切（保留列表/表格行完整性）
    all_sentences: List[str] = []
    for text in texts:
        sents = re.split(r'(?<=[。！？\.\!\?])\s*|\n{2,}', text)
        all_sentences.extend([s.strip() for s in sents if s.strip()])

    if not all_sentences:
        return []

    # ── 生成 embedding ──────────────────────────────────────────
    def _embed_batch(batch: List[str]) -> List[List[float]]:
        """调用 Ollama /api/embed 批量生成向量"""
        try:
            with httpx.Client(transport=httpx.HTTPTransport(), timeout=60) as client:
                resp = client.post(
                    f"{OLLAMA_BASE_URL}/api/embed",
                    json={"model": EMBED_MODEL, "input": batch},
                )
                resp.raise_for_status()
                return resp.json().get("embeddings", [])
        except Exception as e:
            print(f"[SemanticChunker] embedding 失败: {e}")
            return []

    # 分批嵌入，每批 32 句，避免请求过大
    BATCH = 32
    embeddings = []
    failed_ranges = []  # 记录失败批次的句子索引范围
    for i in range(0, len(all_sentences), BATCH):
        batch = all_sentences[i:i + BATCH]
        vecs = _embed_batch(batch)
        if not vecs:
            print(f"[SemanticChunker] 第 {i//BATCH+1} 批 embedding 失败，跳过该批句子")
            # 用零向量占位，后续相似度会很低，自然会在该位置切断段落
            failed_ranges.append((i, i + len(batch)))
            embeddings.extend([[0.0] * 1] * len(batch))  # 占位
        else:
            embeddings.extend(vecs)

    # 如果全部批次都失败，降级到 recursive
    if len(failed_ranges) * BATCH >= len(all_sentences):
        print("[SemanticChunker] 所有批次 embedding 均失败，降级到 recursive")
        return _chunk_recursive(texts, is_markdown=True, chunk_size=_size, chunk_overlap=_overlap)

    # ── 计算相邻余弦相似度，找切割点 ──────────────────────────
    import math
    from config import SEMANTIC_THRESHOLD

    def _cosine(a: List[float], b: List[float]) -> float:
        """
        计算两个向量的余弦相似度。

        Returns:
            余弦相似度，范围 [-1, 1]；两向量长度为零时返回 0.0
        """
        dot = sum(x * y for x, y in zip(a, b))
        na  = math.sqrt(sum(x * x for x in a))
        nb  = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na * nb > 0 else 0.0

    segments: List[str] = []
    current: List[str] = [all_sentences[0]]

    for i in range(1, len(all_sentences)):
        sim = _cosine(embeddings[i - 1], embeddings[i])
        if sim < SEMANTIC_THRESHOLD:
            segments.append("".join(current))
            current = [all_sentences[i]]
        else:
            current.append(all_sentences[i])

    if current:
        segments.append("".join(current))

    # ── 二次截断：超过 _size 的段落切小 ──────────────────
    secondary = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=_size,
        chunk_overlap=_overlap,
        separators=["\n\n", "。", ".", "\n", " ", ""],
    )
    chunks = []
    for seg in segments:
        if seg.strip():
            chunks.extend(secondary.split_text(seg))

    if not chunks:
        return _chunk_recursive(texts, is_markdown=True, chunk_size=_size, chunk_overlap=_overlap)

    print(f"[SemanticChunker] 切分完成: {len(all_sentences)} 句 → {len(segments)} 语义段 → {len(chunks)} 块")
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

    # Windows 文件锁处理：如果文件正被其他进程占用（如 _batch_ingest 的 OCR），
    # 等待后重试，最多 3 次
    import time as _time_upload
    for _attempt in range(3):
        try:
            with open(raw_path, "wb") as f:
                f.write(content)
            break  # 写入成功
        except PermissionError:
            if _attempt < 2:
                print(f"[Upload] 文件被占用，等待重试 ({_attempt+1}/3): {filename}")
                _time_upload.sleep(2)
            else:
                raise  # 3 次都失败，向上抛出

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

    Windows 文件锁处理：
      - 先做垃圾回收释放可能的 Python 文件句柄
      - 若 unlink 失败，最多重试 3 次（间隔 0.5 秒）
      - 3 次都失败则只删 .md，原始文件跳过（不抛异常），打印警告

    Args:
        filename:   要删除的文件名（仅文件名，不含目录路径）
        upload_dir: 上传目录路径，默认使用 config.UPLOAD_DIR

    Returns:
        True 表示原始文件已成功删除或不存在，False 表示文件存在但被锁定无法删除
    """
    import gc, time

    if upload_dir is None:
        upload_dir = UPLOAD_DIR

    upload_path = Path(upload_dir)
    doc_path    = upload_path / filename
    deleted     = False

    # 先做一次 GC，释放可能残留的 Python 文件句柄（markitdown 转换后可能未释放）
    gc.collect()

    # 删除原始文件（带重试）
    if doc_path.exists():
        for attempt in range(3):
            try:
                doc_path.unlink()
                deleted = True
                break
            except PermissionError as e:
                if attempt < 2:
                    print(f"[Cleanup] 文件被锁定，等待重试 ({attempt+1}/3): {doc_path.name}")
                    time.sleep(0.5)
                    gc.collect()
                else:
                    print(f"[Cleanup] ⚠️ 无法删除原始文件（文件被其他程序占用），跳过: {doc_path.name} — {e}")
                    # 不抛异常，继续尝试删 .md

    # 若原始文件不是 .md，同步删除自动生成的同名 .md
    if Path(filename).suffix.lower() != ".md":
        md_path = upload_path / (Path(filename).stem + ".md")
        if md_path.exists():
            for attempt in range(3):
                try:
                    md_path.unlink()
                    break
                except PermissionError:
                    if attempt < 2:
                        time.sleep(0.3)
                    else:
                        print(f"[Cleanup] ⚠️ 无法删除 .md 文件: {md_path.name}")

    return deleted


# ──────────────────────────────────────────────────────────────
# 标题后缀自动学习
# ──────────────────────────────────────────────────────────────

def extract_and_update_title_suffixes(chunks: List[str]) -> None:
    """
    从已切分的 chunk 中自动学习标题通用后缀词，合并更新到 word_config.json。

    工作流程：
      1. 扫描所有 chunk 开头的 [标题路径]，提取末级标题词
      2. 统计各词出现频次，取出现 ≥ 2 次的候选
      3. 调用 LLM 判断候选词中哪些是通用后缀（与具体内容无关，如"清单""须知"）
      4. 将新词合并进 word_config.json，并热更新 config 内存值（无需重启）

    设计原则：
      - 静默异步执行，任何异常只打印日志，不影响主流程
      - 幂等：已在配置里的词不会重复添加
      - 保守：对候选词数量设上限（MAX_CANDIDATES=30），避免 LLM 提示过长

    Args:
        chunks: chunk_texts 返回的文本块列表
    """
    import re as _re
    from collections import Counter
    from pathlib import Path as _Path

    # ── 1. 提取所有 chunk 的末级标题词 ─────────────────────────
    tail_words: List[str] = []
    for chunk in chunks:
        m = _re.match(r'^\[([^\]]+)\]', chunk.strip())
        if not m:
            continue
        title_path = m.group(1)
        # 取路径的最后一级（" > " 分隔）
        last_title = title_path.split(" > ")[-1].strip()
        if not last_title:
            continue
        # 只取标题末尾 2~4 个汉字作为候选后缀词
        # 不能取太长（避免把整个短标题当后缀），不能取太短（避免噪音）
        # 例："国内特药药品清单" → 取最后2字"清单"、最后3字"药清单"... 只保留2~4字
        for length in (2, 3, 4):
            suffix = _re.search(r'[\u4e00-\u9fff]{' + str(length) + r'}$', last_title)
            if suffix:
                tail_words.append(suffix.group())
                break  # 只取最短的有效后缀，避免重复

    if not tail_words:
        return

    # ── 2. 统计频次，筛选候选 ───────────────────────────────────
    # 从 word_config.json 文件读取当前词表（而非 config 内存变量，避免默认值干扰）
    import json as _json
    from pathlib import Path as _Path
    _word_cfg_path = _Path(__file__).parent / "word_config.json"
    try:
        with open(_word_cfg_path, "r", encoding="utf-8") as _f:
            _word_cfg = _json.load(_f)
        existing_set = {
            w for w in _word_cfg.get("title_generic_suffixes", [])
            if isinstance(w, str) and w
        }
        print(f"[TitleSuffix][DEBUG] 读取文件: {_word_cfg_path}, existing_set={existing_set}")
    except Exception as _e:
        print(f"[TitleSuffix][DEBUG] 读取文件失败: {_e}，降级到 config 内存变量")
        # 文件不存在或读取失败，降级到 config 内存变量
        from config import TITLE_GENERIC_SUFFIXES as _existing
        existing_set = set(_existing)

    counter = Counter(tail_words)
    total_titles = len(set(
        _re.match(r'^\[([^\]]+)\]', c.strip()).group(1).split(" > ")[-1].strip()
        for c in chunks
        if _re.match(r'^\[([^\]]+)\]', c.strip())
    ))
    # 动态阈值：标题数少时降低要求，多时适当提高
    min_freq = 1 if total_titles < 10 else 2
    MAX_CANDIDATES = 30

    candidates = [
        word for word, cnt in counter.most_common(MAX_CANDIDATES)
        if cnt >= min_freq and word not in existing_set
    ]
    if not candidates:
        print("[TitleSuffix] 无新候选后缀词，跳过")
        return

    print(f"[TitleSuffix] 候选后缀词: {candidates}")

    # ── 3. LLM 判断哪些是通用后缀 ──────────────────────────────
    try:
        from config import CHAT_MODEL, OLLAMA_BASE_URL, THINKING
        import httpx as _httpx

        prompt = (
            "/no_think\n"
            "以下是从文档标题中提取的词语，请判断哪些是与具体业务内容无关的「通用后缀词」。\n\n"
            "通用后缀词的特征：\n"
            "- 出现在标题末尾，描述文档的「类型」或「形式」，而非具体内容\n"
            "- 例如：清单、列表、明细、目录、须知、说明、介绍、规定、条款、规则、流程、方案、模板\n"
            "- 反例（非通用，是具体业务词）：保障、赔付、投保、理赔、费用、病种、药品\n\n"
            f"候选词列表：{candidates}\n\n"
            "请只返回属于通用后缀词的列表，用英文逗号分隔，不要解释。\n"
            "如果全部都不是通用后缀词，返回空字符串。"
        )

        with _httpx.Client(transport=_httpx.HTTPTransport(), timeout=60) as client:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": CHAT_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "think": THINKING,
                    "options": {"temperature": 0, "num_ctx": 2048},
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()

        # 解析 LLM 返回的逗号分隔词列表
        # 只接受在 candidates 里的词（防止 LLM 幻觉），去重
        llm_words = list(dict.fromkeys(
            w.strip() for w in raw.replace("，", ",").split(",") if w.strip()
        ))
        new_suffixes = [w for w in llm_words if w in candidates]
        already_known = [w for w in llm_words if w and w not in candidates]

        if already_known:
            print(f"[TitleSuffix] LLM 返回词中已在词表里的: {already_known}（无需重复添加）")
        if not new_suffixes:
            print(f"[TitleSuffix] 无新词需要添加（LLM 返回: {llm_words}）")
            return

        print(f"[TitleSuffix] LLM 确认新后缀词: {new_suffixes}")

    except Exception as e:
        print(f"[TitleSuffix] LLM 判断失败，跳过自动学习: {e}")
        return

    # ── 4. 合并写回 word_config.json ───────────────────────────
    try:
        from pathlib import Path as _Path
        import json as _json

        word_cfg_path = _Path(__file__).parent / "word_config.json"

        # 读取现有 JSON（保留注释 key 和其他字段）
        if word_cfg_path.exists():
            with open(word_cfg_path, "r", encoding="utf-8") as f:
                word_cfg = _json.load(f)
        else:
            word_cfg = {}

        current_list: list = word_cfg.get("title_generic_suffixes", [])
        # 过滤掉注释 key
        current_set = {w for w in current_list if isinstance(w, str) and not w.startswith("_")}

        merged = sorted(current_set | set(new_suffixes))
        if merged == sorted(current_set):
            print("[TitleSuffix] 词表已是最新，无需更新")
            return

        word_cfg["title_generic_suffixes"] = merged
        with open(word_cfg_path, "w", encoding="utf-8") as f:
            _json.dump(word_cfg, f, ensure_ascii=False, indent=4)

        print(f"[TitleSuffix] 已更新 word_config.json: 新增 {new_suffixes}")

        # 热更新 config 模块的内存值，无需重启即生效
        import config as _cfg
        _cfg.reload_word_config()

    except Exception as e:
        print(f"[TitleSuffix] 写入 word_config.json 失败: {e}")
