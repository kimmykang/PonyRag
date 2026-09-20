"""
智能客服系统 - 配置模块

作者: kimikang

职责：
  - 从项目根目录的 .env 文件加载所有环境变量
  - 提供全局统一的配置常量，供其他模块 import 使用
  - 确保必要的目录（uploads、vector_db）在启动时存在

修改配置的方式：
  1. 直接编辑 backend/.env 文件（推荐）
  2. 通过前端「模型设置」界面动态修改（运行时生效）
"""
import os
import json as _json
from pathlib import Path
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────
# 加载 .env 文件
# 使用绝对路径定位，避免工作目录不同导致找不到文件
# ──────────────────────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# HuggingFace Hub 离线模式：模型已本地缓存时禁止联网检查，消除 unauthenticated 警告
# .env 中设置 HF_HUB_OFFLINE=1 即可；此处读取后写回环境变量确保 sentence_transformers 能感知
if os.getenv("HF_HUB_OFFLINE", "").strip() == "1":
    os.environ["HF_HUB_OFFLINE"] = "1"

# ──────────────────────────────────────────────────────────────
# Ollama 服务配置
# ──────────────────────────────────────────────────────────────
# Ollama HTTP 服务地址，默认本地 11434 端口
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# 对话模型：用于生成最终回答，推荐使用支持中文的大模型
CHAT_MODEL: str = os.getenv("CHAT_MODEL", "qwen3.6:27b")

# 问题改写模型：用于多轮对话中补全省略指代（建议用小模型加速）
# 留空则使用 CHAT_MODEL；推荐配置一个 1~4B 的小模型，如 qwen3:1.7b
REWRITE_MODEL: str = os.getenv("REWRITE_MODEL", "")

# 嵌入模型：将文本转为向量，用于语义检索；维度需与已建库的维度一致
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "qwen3-embedding:4b")

# Rerank 模型：对检索结果精排，提升最终上下文质量
RERANK_MODEL: str = os.getenv("RERANK_MODEL", "MedAIBase/Qwen3-VL-Reranker:2b")

# Rerank 方式：ollama | cross_encoder | listwise
# - ollama:        通过 Ollama 推理（embed 或 generate+logprob，自动判断 model family）
# - cross_encoder: 本地 HuggingFace CrossEncoder（推荐，GPU 加速约 0.1s/6doc）
# - listwise:      用 CHAT_MODEL 做 Listwise 批量排序（精度高但大模型速度慢）
# 以上三种方法失败后均自动降级到向量相似度排序（不中断请求）
RERANK_METHOD: str = os.getenv("RERANK_METHOD", "cross_encoder")

# CrossEncoder 本地模型名（RERANK_METHOD=cross_encoder 时生效）
CROSS_ENCODER_MODEL: str = os.getenv("CROSS_ENCODER_MODEL", "BAAI/bge-reranker-v2-m3")

# CrossEncoder 运行设备（RERANK_METHOD=cross_encoder 时生效）
# auto — 有 CUDA 则用 GPU，否则自动降到 CPU（默认）
# gpu  — 强制 GPU（显卡显存充足时推荐，~500MB，推理约 0.1s/6doc）
# cpu  — 强制 CPU（与 Ollama 大模型共享显存时避免竞争，推理约 0.5~2s/6doc）
CROSS_ENCODER_DEVICE: str = os.getenv("CROSS_ENCODER_DEVICE", "auto")

# Ollama 模型显存保留时间：模型推理完成后在显存中保留多久
# 所有调用 Ollama 的地方（rewrite_query / answer / stream）统一使用此值
# -1 表示永久保留；0 表示立即卸载；默认 30m
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

# OCR 视觉模型：用于提取图片型 PDF / 扫描件中的文字（需支持视觉输入）
# 留空则禁用 OCR，markitdown 退回普通文本提取
OCR_MODEL: str = os.getenv("OCR_MODEL", "qwen3.6:27b")

# ──────────────────────────────────────────────────────────────
# 存储路径配置
# ──────────────────────────────────────────────────────────────
# ChromaDB 持久化目录，存储向量数据
VECTOR_DB_PATH: str = os.getenv("VECTOR_DB_PATH", "./vector_db")

# 用户上传文件的保存目录（原始文件 + markitdown 转换后的 .md 文件）
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")

# ──────────────────────────────────────────────────────────────
# FastAPI 服务器配置
# ──────────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")   # 监听地址，0.0.0.0 表示允许外部访问
PORT: int = int(os.getenv("PORT", "8001"))  # 监听端口

# ──────────────────────────────────────────────────────────────
# RAG 检索参数
# ──────────────────────────────────────────────────────────────
# 向量检索阶段返回的候选文档数（召回池大小）
TOP_K: int = int(os.getenv("TOP_K", "10"))

# Rerank 精排后保留的最终文档数（送入 LLM 的上下文条数）
RERANK_TOP_K: int = int(os.getenv("RERANK_TOP_K", "5"))

# 文档分块大小（token 数），影响每块携带的信息密度
# 推荐值随嵌入模型调整：
#   qwen3-embedding:0.6b / 1.7b  →  500~800
#   qwen3-embedding:4b            →  800~1200
#   qwen3-embedding:8b            →  1000~1500
#   nomic-embed-text / bge-m3    →  400~600
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))

# 相邻分块的重叠 token 数，防止语义断裂
# 建议为 CHUNK_SIZE 的 15%，默认 150（对应 CHUNK_SIZE=1000）
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "150"))

# 文档分块方式：
#   recursive  — 递归字符切分（默认，按标点/空行逐级细分）
#   markdown   — 按 Markdown 标题树结构切分（适合结构化文档）
#   semantic   — 语义相似度切分（用 embedding 判断段落边界，适合叙事型文档）
CHUNK_METHOD: str = os.getenv("CHUNK_METHOD", "recursive")

# 送入 LLM 的最大参考知识字符数
CONTEXT_LIMIT: int = int(os.getenv("CONTEXT_LIMIT", "20000"))

# Ollama 模型的上下文窗口大小（token 数）
# 所有调用 Ollama 的地方（rewrite_query / answer / stream）统一使用此值
# 必须保持一致：同一模型不同 num_ctx 会触发 Ollama 完整卸载重载，导致显存抖动
# qwen3.6:27b 支持最大 131072；普通场景 32768 已足够，可节省显存
NUM_CTX: int = int(os.getenv("NUM_CTX", "131072"))

# 召回文档的最低相似度门槛：低于此值的文档在进入 rerank 前被过滤
# 取值 0~1，设为 0 表示不过滤；ChromaDB 的余弦距离转换后通常在 0.2~1.0
SIM_THRESHOLD: float = float(os.getenv("SIM_THRESHOLD", "0.3"))

# 模型思考模式：True 开启 thinking，False 关闭（默认关闭）
THINKING: bool = os.getenv("THINKING", "false").lower() == "true"

# 上下文截断最小填充字符数：剩余空间小于此值时不做截断填充，直接停止
# 避免把一两个字的碎片追加到上下文里
CONTEXT_TRUNCATE_MIN: int = int(os.getenv("CONTEXT_TRUNCATE_MIN", "100"))

# 启动时自动索引：True 表示启动时自动将未入库的 .md 文件向量化入库
# 默认关闭，避免重启时与正在进行的上传任务竞争资源
# 需要断点续传功能时可设为 true
STARTUP_INGEST: bool = os.getenv("STARTUP_INGEST", "false").lower() == "true"

# 语义切分的相似度跳变阈值：相邻句子余弦相似度低于此值时切断
# 不同嵌入模型的相似度范围差异较大，建议根据实际模型调整：
#   qwen3-embedding 系列：推荐 0.60~0.70
#   nomic-embed-text：    推荐 0.70~0.78
#   bge-m3：              推荐 0.65~0.75
SEMANTIC_THRESHOLD: float = float(os.getenv("SEMANTIC_THRESHOLD", "0.65"))

# 标题核心词提取的通用尾部词表：标题末尾出现这些词时，去掉后用核心部分做问题匹配
# 从 word_config.json 加载，.env 中的 TITLE_GENERIC_SUFFIXES 作为兜底覆盖（向后兼容）
# 标题扩展时的问题停用词表：从 word_config.json 加载，.env 中的 QUERY_STOPWORDS 作为兜底覆盖
# 两个配置均在 load_word_config() 中统一管理

_WORD_CONFIG_PATH = Path(__file__).parent / "word_config.json"

# 内置默认词表，word_config.json 缺失时使用
_WORD_CONFIG_DEFAULTS: dict = {
    "title_generic_suffixes": [
        "清单", "列表", "明细", "目录",
        "说明", "介绍", "概述", "详情", "内容", "信息",
        "规定", "条款", "须知", "规则",
        "流程", "方案", "模板", "指南", "手册",
    ],
    "query_stopwords": {
        "zh": [
            "有哪些", "哪些", "是什么", "什么是", "怎么样", "怎么", "如何", "为什么", "为啥",
            "多少", "多少钱", "多久", "多大", "几个", "几种",
            "有没有", "有什么", "是否", "能否", "可以", "可不可以",
            "请问", "告诉我", "帮我", "给我", "查一下", "介绍一下", "说说",
            "关于", "包括", "涵盖", "属于", "针对", "对于",
            "所有", "全部", "详细", "具体", "相关",
            "的是", "是啥", "在哪", "在哪里", "怎么办", "咋办",
            "费用",
        ],
        "en": [
            "what", "which", "who", "where", "when", "why", "how",
            "the", "a", "an", "of", "in", "for", "on", "about", "with", "all", "any",
            "tell me", "show me", "give me", "list all", "find me", "help me",
            "what is", "what are", "how to", "how do", "how does", "how many", "how much",
            "is there", "are there", "do you have", "can i", "can you",
        ],
    },
}


def load_word_config() -> dict:
    """
    读取 word_config.json，返回完整词表配置字典。
    - key 不存在：从默认值补全
    - key 存在但值为空（空列表/空dict）：视为用户有意清空，使用空值，不报错
    - 文件不存在：全部使用默认值
    修改 JSON 文件后无需重启，下次请求时自动生效。
    """
    result = _json.loads(_json.dumps(_WORD_CONFIG_DEFAULTS))  # 深拷贝默认值
    try:
        with open(_WORD_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = _json.load(f)
        for k, v in data.items():
            if k.startswith("_"):
                continue
            result[k] = v  # 文件中存在的 key 直接覆盖，包括空列表/空dict
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[Config] word_config.json 读取失败: {e}，使用内置默认值")
    return result


def _load_title_suffixes() -> tuple:
    """从 word_config.json 加载标题通用后缀词表，返回 tuple。空值或异常时返回空 tuple。"""
    try:
        cfg = load_word_config()
        raw = cfg.get("title_generic_suffixes", [])
        if not isinstance(raw, list):
            return ()
        return tuple(s for s in raw if isinstance(s, str) and s and not s.startswith("_"))
    except Exception as e:
        print(f"[Config] 加载 title_generic_suffixes 失败: {e}")
        return ()


def _load_query_stopwords() -> frozenset:
    """从 word_config.json 加载问题停用词表，中英文合并，返回 frozenset。空值或异常时返回空 frozenset。"""
    try:
        cfg = load_word_config()
        sw = cfg.get("query_stopwords", {})
        words = []
        if isinstance(sw, dict):
            for k, v in sw.items():
                if not k.startswith("_") and isinstance(v, list):
                    words.extend(v)
        elif isinstance(sw, list):
            words = sw
        return frozenset(w for w in words if isinstance(w, str) and w)
    except Exception as e:
        print(f"[Config] 加载 query_stopwords 失败: {e}")
        return frozenset()


# 模块级全局变量：启动时加载，自动学习后通过 reload_word_config() 热更新
TITLE_GENERIC_SUFFIXES: tuple    = _load_title_suffixes()
QUERY_STOPWORDS:        frozenset = _load_query_stopwords()


def reload_word_config():
    """
    热更新词表全局变量（无需重启）。
    自动学习写入 word_config.json 后调用此函数，使新词立即生效。
    """
    global TITLE_GENERIC_SUFFIXES, QUERY_STOPWORDS
    TITLE_GENERIC_SUFFIXES = _load_title_suffixes()
    QUERY_STOPWORDS        = _load_query_stopwords()
    print(f"[Config] 词表已热更新: suffixes={len(TITLE_GENERIC_SUFFIXES)}, stopwords={len(QUERY_STOPWORDS)}")

# ──────────────────────────────────────────────────────────────
# 初始化：确保必要目录存在
# ──────────────────────────────────────────────────────────────
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
Path(VECTOR_DB_PATH).mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────
# Prompt 配置（从 prompt_config.json 加载）
# 修改 prompt_config.json 后无需重启，下次请求时自动生效
# ──────────────────────────────────────────────────────────────

_PROMPT_CONFIG_PATH = Path(__file__).parent / "prompt_config.json"

# 内置默认 prompt 配置，prompt_config.json 缺失时使用
_PROMPT_CONFIG_DEFAULTS: dict = {
    "system_role": "你是一个智能客服助手。请根据以下参考知识回答用户的问题。",
    "list_keywords": [
        "有哪些", "列出", "所有", "清单", "包括", "全部", "列表", "都有",
        "list all", "list the", "what are", "what is the list",
        "all the", "enumerate", "show all", "give me all",
    ],
    "instructions_list": [
        "如果参考知识中有相关信息，请完整列出参考内容中的所有项目，不要省略任何条目",
        "如果参考知识只包含部分条目，请列出所有已提供的条目，并在末尾注明完整清单请以官方文件为准",
        "如果参考知识中没有相关信息，请如实告知用户无法回答",
        "回答要结构清晰，保留表格格式",
    ],
    "instructions_default": [
        "如果参考知识中有相关信息，请基于参考内容回答问题",
        "如果参考知识中没有相关信息，请如实告知用户无法回答",
        "回答要专业、准确、有条理",
    ],
    "prompt_template": "要求：\n{instructions}\n参考知识：\n{context}\n\n用户问题：{question}\n\n请回答：",
}


def load_prompt_config() -> dict:
    """
    读取 prompt_config.json，返回完整配置字典。
    文件中缺失的 key 自动从默认值补全，文件不存在时全部使用默认值。
    修改 JSON 文件后无需重启，下次请求时自动生效。
    """
    result = dict(_PROMPT_CONFIG_DEFAULTS)  # 从默认值开始
    try:
        with open(_PROMPT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = _json.load(f)
        result.update(data)  # JSON 中的值覆盖默认值（仅覆盖存在的 key）
    except FileNotFoundError:
        pass  # 文件不存在，使用全部默认值
    except Exception as e:
        print(f"[Config] prompt_config.json 读取失败: {e}，使用内置默认值")
    return result
