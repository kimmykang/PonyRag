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
from pathlib import Path
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────
# 加载 .env 文件
# 使用绝对路径定位，避免工作目录不同导致找不到文件
# ──────────────────────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# ──────────────────────────────────────────────────────────────
# Ollama 服务配置
# ──────────────────────────────────────────────────────────────
# Ollama HTTP 服务地址，默认本地 11434 端口
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# 对话模型：用于生成最终回答，推荐使用支持中文的大模型
CHAT_MODEL: str = os.getenv("CHAT_MODEL", "qwen3.6:27b")

# 嵌入模型：将文本转为向量，用于语义检索；维度需与已建库的维度一致
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "qwen3-embedding:4b")

# Rerank 模型：对检索结果精排，提升最终上下文质量
RERANK_MODEL: str = os.getenv("RERANK_MODEL", "MedAIBase/Qwen3-VL-Reranker:2b")

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
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))

# 相邻分块的重叠 token 数，防止语义断裂
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))

# ──────────────────────────────────────────────────────────────
# 初始化：确保必要目录存在
# ──────────────────────────────────────────────────────────────
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
Path(VECTOR_DB_PATH).mkdir(parents=True, exist_ok=True)
