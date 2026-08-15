# PonyRAG 知识库系统

<div align="center">

**PonyRAG Knowledge Base System**

*🐴 A lightweight, production-ready RAG knowledge base system powered by LangChain, Ollama, and ChromaDB*

[中文](#中文文档) | [English](#english-documentation)

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.138-green?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-1.5-purple)](https://www.trychroma.com/)
[![Ollama](https://img.shields.io/badge/Ollama-Local-orange)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

</div>

---

<div id="中文文档"></div>

## � 项目简介

**PonyRAG** 是一个基于 RAG（检索增强生成）技术的本地知识库问答系统，专为企业和个人知识管理场景设计。系统完全本地部署，保护数据隐私，支持多种文档格式，提供智能问答和知识检索服务。

### ✨ 核心特性

- 🚀 **开箱即用** — 本地部署，无需云服务，保护数据隐私
- 📚 **多格式支持** — PDF、Word、Excel、PowerPoint、Markdown、TXT 自动解析
- 🧠 **智能检索** — 向量检索 + Rerank 精排，确保答案准确性
- 💬 **多轮对话** — 支持上下文记忆的连续对话
- 🗄️ **多知识库管理** — 创建、启用/禁用多个独立知识库
- 🎨 **现代界面** — 响应式 Web UI，支持移动端和桌面端
- ⚡ **高性能** — ChromaDB 向量存储，毫秒级检索响应
- 🔄 **模型热切换** — 在线更换 LLM/Embedding/Rerank 模型

### 🏗️ 技术架构

```
用户交互
  ↓
┌─────────────────────────────────────────┐
│  前端 (Vanilla JavaScript)              │
│  - 聊天界面 (index.html)                │
│  - 知识库管理 (knowledge.html)          │
└───────────────┬─────────────────────────┘
                │ REST API
┌───────────────▼─────────────────────────┐
│  后端 (FastAPI + Python)                │
│  ┌─────────────────────────────────┐    │
│  │  RAG Engine (rag_engine.py)    │    │
│  │  - 向量检索                      │    │
│  │  - Rerank 精排                   │    │
│  │  - LLM 生成回答                  │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │  文档处理 (document_processor)  │    │
│  │  - Markitdown 解析              │    │
│  │  - 文本分块                      │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │  知识库管理 (knowledge_base)    │    │
│  │  - 多知识库元数据管理            │    │
│  │  - SQLite 存储                   │    │
│  └─────────────────────────────────┘    │
└───────────────┬─────────────────────────┘
                │
┌───────────────▼─────────────────────────┐
│  ChromaDB (向量数据库)                  │
│  - 每个知识库独立 Collection            │
│  - 本地持久化存储                        │
└─────────────────────────────────────────┘
                │
┌───────────────▼─────────────────────────┐
│  Ollama (本地大模型推理)                │
│  - 对话模型 (Chat Model)                │
│  - 嵌入模型 (Embedding Model)           │
│  - 精排模型 (Rerank Model)              │
└─────────────────────────────────────────┘
```

**技术栈：**
- **后端**: FastAPI + LangChain + Python 3.11+
- **向量数据库**: ChromaDB (本地持久化)
- **大语言模型**: Ollama (支持 Qwen、Llama 等开源模型)
- **文档解析**: Markitdown (支持多种文档格式)
- **前端**: Vanilla JavaScript + Marked.js
- **数据存储**: SQLite (聊天历史 + 知识库元数据)

### 🎯 主要功能

#### 1. 知识库管理
- ✅ 创建/编辑/删除知识库
- ✅ 启用/禁用知识库
- ✅ 查看文档数和向量数统计
- ✅ 每个知识库独立的向量空间

#### 2. 文档管理
- ✅ 拖拽上传或点击上传
- ✅ 自动格式转换（PDF/Word → Markdown）
- ✅ 批量删除文档
- ✅ 实时索引进度显示
- ✅ 支持格式：PDF、DOCX、XLSX、PPTX、TXT、MD

#### 3. 智能问答
- ✅ 基于知识库的精准回答
- ✅ 显示参考来源和相关度评分
- ✅ 选择特定知识库或全库检索
- ✅ Markdown 格式渲染（代码高亮、表格等）
- ✅ 多轮对话上下文记忆

#### 4. 模型管理
- ✅ 在线切换对话模型
- ✅ 在线切换 Embedding 模型（自动重建索引）
- ✅ 在线切换 OCR 视觉模型（用于图片型 PDF / 扫描件）
- ✅ 调整检索参数（TOP-K、Rerank-TOP-K 等）
- ✅ 实时显示模型加载状态

### 📦 快速开始

#### 前置要求

- **Python 3.11+**
- **Ollama** ([安装指南](https://ollama.com/))
- **推荐配置**: 16GB+ 内存，NVIDIA GPU（可选）

#### 安装步骤

**1. 克隆项目**
```bash
git clone https://github.com/kimikang/ponyrag.git
cd ponyrag
```

**2. 安装依赖**
```bash
cd backend
pip install -r requirements.txt
pip install markitdown
```

**2.1 可选：安装 OCR 支持**（用于图片型 PDF / 扫描件文字提取）
```bash
pip install markitdown-ocr openai
```

**3. 安装 Ollama 并下载模型**

访问 [https://ollama.com](https://ollama.com) 下载并安装 Ollama

下载推荐模型（约 15GB）：
```bash
# 对话模型
ollama pull qwen3.6:27b

# 嵌入模型
ollama pull qwen3-embedding:4b

# Rerank 模型
ollama pull qllama/bge-reranker-v2-m3:f16

# OCR 视觉模型（可选，用于图片型 PDF / 扫描件）
ollama pull qwen2.5vl:7b
```

**4. 启动服务**

**Windows:**
```bash
start.bat
```

**Windows (Conda):**
```bash
"start for conda.bat"
```

**Linux/macOS:**
```bash
chmod +x start.sh
./start.sh
```

**5. 访问应用**

浏览器会自动打开 [http://localhost:8001](http://localhost:8001)

### 📝 使用说明

#### 创建知识库并上传文档

1. 点击顶部导航「知识库管理」
2. 点击「创建知识库」按钮，填写名称和描述
3. 在知识库卡片上点击「管理文档」
4. 拖拽或点击上传 PDF/Word/Excel 等文件
5. 等待文档自动解析和索引完成

#### 开始提问

1. 返回主页（聊天界面）
2. 在左侧「检索知识库」下拉框选择知识库（或选择「所有已启用的知识库」）
3. 在输入框输入问题，按 Enter 发送
4. AI 会基于知识库内容生成回答，并显示参考来源

#### 模型和参数设置

点击右上角 ⚙️ 图标打开设置面板：

- **模型设置**：切换 Chat/Embed/Rerank 模型
- **参数设置**：调整 TOP-K、Rerank-TOP-K、分块大小等

### ⚙️ 配置说明

编辑 `backend/.env` 文件自定义配置：

```env
# Ollama 服务地址
OLLAMA_BASE_URL=http://localhost:11434

# 模型配置
CHAT_MODEL=qwen3.6:27b                      # 对话模型
EMBED_MODEL=qwen3-embedding:4b               # 嵌入模型（⚠️ 切换后需重建向量库）
RERANK_MODEL=qllama/bge-reranker-v2-m3:f16  # Rerank 模型
OCR_MODEL=qwen2.5vl:7b                                   # OCR 视觉模型（留空禁用，如 qwen2.5vl:7b）

# RAG 参数
TOP_K=6                # 向量检索召回数量
RERANK_TOP_K=4         # Rerank 精排后保留数量
CHUNK_SIZE=500         # 文档分块大小（token）
CHUNK_OVERLAP=50       # 分块重叠大小（token）

# 服务配置
HOST=0.0.0.0
PORT=8001
```

### � 项目结构

```
ponyrag/
├── backend/                    # 后端服务
│   ├── app.py                 # FastAPI 主应用
│   ├── rag_engine.py          # RAG 核心引擎
│   ├── vector_store.py        # 向量数据库管理
│   ├── document_processor.py  # 文档处理模块
│   ├── knowledge_base.py      # 知识库管理
│   ├── chat_history.py        # 聊天历史存储
│   ├── config.py              # 配置管理
│   ├── requirements.txt       # Python 依赖
│   ├── .env                   # 环境配置
│   ├── uploads/               # 文档上传目录
│   └── vector_db/             # ChromaDB 数据目录
├── frontend/                   # 前端界面
│   ├── index.html             # 聊天界面
│   ├── knowledge.html         # 知识库管理界面
│   ├── app.js                 # 聊天页面逻辑
│   ├── knowledge.js           # 知识库管理逻辑
│   └── style.css              # 全局样式
├── start.bat                   # Windows 启动脚本
├── start for conda.bat         # Conda 环境启动脚本
├── start.sh                    # Linux/macOS 启动脚本
└── README.md                   # 项目文档
```

### 🔌 API 文档

启动服务后访问 [http://localhost:8001/docs](http://localhost:8001/docs) 查看完整的 Swagger API 文档。

主要接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 发送问题并获取回答 |
| `GET` | `/api/knowledge-bases` | 获取知识库列表 |
| `POST` | `/api/knowledge-bases` | 创建新知识库 |
| `PUT` | `/api/knowledge-bases/{kb_id}` | 更新知识库信息 |
| `DELETE` | `/api/knowledge-bases/{kb_id}` | 删除知识库 |
| `POST` | `/api/upload` | 上传文档 |
| `GET` | `/api/documents` | 获取文档列表 |
| `DELETE` | `/api/documents/{filename}` | 删除文档 |
| `GET` | `/api/stats` | 获取统计信息 |
| `GET` | `/api/model-status` | 获取模型加载状态 |
| `POST` | `/api/config/models` | 切换模型配置 |

### 🛠️ 常见问题

**Q: 启动后模型一直显示「加载中」？**

Ollama 首次加载大模型需要时间（30秒-几分钟），请耐心等待。可在 Ollama 终端查看加载进度。侧边栏每个模型旁有刷新按钮，超时后可手动重试。

**Q: 提问返回「知识库中暂无相关内容」？**

- 确认知识库已上传文档且向量库条目数 > 0
- 检查知识库是否已启用
- 若刚切换 Embedding 模型，等待重新索引完成

**Q: 如何处理图片型 PDF / 扫描件？**

1. 安装 OCR 依赖：`pip install markitdown-ocr openai`
2. 在 Ollama 中拉取支持视觉输入的模型，如 `ollama pull qwen2.5vl:7b`
3. 在前端设置页面「OCR 模型」下拉框选择该模型并保存
4. 再次上传 PDF，系统会自动识别图片文字

**Q: 如何提升检索速度？**

1. 降低 TOP_K 和 RERANK_TOP_K 参数
2. 使用更小的模型（如 qwen2.5:7b）
3. 使用 GPU 运行 Ollama

**Q: 支持哪些文档格式？**

目前支持：PDF、DOCX、XLSX、PPTX、TXT、MD

**Q: 切换 Embedding 模型后提示维度不匹配？**

不同模型输出维度不同。系统会自动检测并清空旧向量库，重启后自动重新索引。⚠️ 建议不要频繁切换 Embedding 模型。

### ⚡ 性能优化建议

| 内存 | 推荐模型组合 | 适用场景 |
|------|-------------|---------|
| 16GB | qwen2.5:7b + qwen3-embedding:4b | 个人使用 |
| 32GB | qwen3.6:27b + qwen3-embedding:4b | 生产环境 |
| 64GB+ | qwen3.6:27b + qwen3-embedding:8b | 最佳性能 |

**TOP_K 参数调优：**
- 准确度优先：`TOP_K=10, RERANK_TOP_K=6`
- 平衡（推荐）：`TOP_K=6, RERANK_TOP_K=4`
- 速度优先：`TOP_K=3, RERANK_TOP_K=2`

### 🚧 开发路线

- [x] 多知识库管理
- [x] 文档上传与自动解析
- [x] 向量检索 + Rerank
- [x] 多轮对话历史
- [x] 模型热切换
- [x] 参数动态调整
- [x] 图片型 PDF OCR 支持（基于 Ollama 视觉模型）
- [ ] 文档在线预览
- [ ] 导出聊天记录
- [ ] 多用户权限管理
- [ ] Docker 一键部署
- [ ] 知识库版本管理

### 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 📄 开源协议

本项目采用 [Apache License 2.0](LICENSE) 开源协议。

### 👨‍💻 作者

**kimikang**

📧 86941737@qq.com

---

<div id="english-documentation"></div>

## 📖 About

**PonyRAG** is a local knowledge base Q&A system based on RAG (Retrieval-Augmented Generation) technology, designed for enterprise and personal knowledge management scenarios. The system is fully deployed locally, protects data privacy, supports multiple document formats, and provides intelligent Q&A and knowledge retrieval services.

### ✨ Key Features

- 🚀 **Ready to Use** — Local deployment, no cloud services required, data privacy protected
- 📚 **Multi-format Support** — Auto-parsing for PDF, Word, Excel, PowerPoint, Markdown, TXT
- 🧠 **Smart Retrieval** — Vector search + Rerank for accurate answers
- 💬 **Multi-turn Dialogue** — Context-aware conversations with memory
- 🗄️ **Multiple Knowledge Bases** — Create, enable/disable multiple independent knowledge bases
- 🎨 **Modern UI** — Responsive web interface for mobile and desktop
- ⚡ **High Performance** — ChromaDB vector storage with millisecond-level response
- 🔄 **Hot Model Swapping** — Switch LLM/Embedding/Rerank/OCR models on-the-fly

### 🏗️ Tech Stack

- **Backend**: FastAPI + LangChain + Python 3.11+
- **Vector Database**: ChromaDB (local persistence)
- **LLM**: Ollama (supports Qwen, Llama, etc.)
- **Document Parser**: Markitdown
- **Frontend**: Vanilla JavaScript + Marked.js
- **Data Storage**: SQLite (chat history + knowledge base metadata)

### � Quick Start

#### Prerequisites

- **Python 3.11+**
- **Ollama** ([Installation Guide](https://ollama.com/))
- **Recommended**: 16GB+ RAM, NVIDIA GPU (optional)

#### Installation

**1. Clone the repository**
```bash
git clone https://github.com/kimikang/ponyrag.git
cd ponyrag
```

**2. Install dependencies**
```bash
cd backend
pip install -r requirements.txt
pip install markitdown
```

**2.1 Optional: Install OCR support** (for scanned PDFs / image-only documents)
```bash
pip install markitdown-ocr openai
```

**3. Install Ollama and download models**

Visit [https://ollama.com](https://ollama.com) to download and install Ollama

Download recommended models (~15GB):
```bash
# Chat model
ollama pull qwen3.6:27b

# Embedding model
ollama pull qwen3-embedding:4b

# Rerank model
ollama pull qllama/bge-reranker-v2-m3:f16

# OCR vision model (optional, for scanned PDFs)
ollama pull qwen2.5vl:7b
```

**4. Start the service**

**Windows:**
```bash
start.bat
```

**Linux/macOS:**
```bash
chmod +x start.sh
./start.sh
```

**5. Access the application**

Browser will automatically open [http://localhost:8001](http://localhost:8001)

### 📝 Usage

#### Create Knowledge Base and Upload Documents

1. Click "Knowledge Base Management" in the top navigation
2. Click "Create Knowledge Base" button, fill in name and description
3. Click "Manage Documents" on the knowledge base card
4. Drag and drop or click to upload PDF/Word/Excel files
5. Wait for automatic document parsing and indexing

#### Start Asking Questions

1. Return to the home page (chat interface)
2. Select a knowledge base in the left sidebar (or "All Enabled Knowledge Bases")
3. Type your question in the input box and press Enter
4. AI will generate answers based on knowledge base content and show references

### ⚙️ Configuration

Edit `backend/.env` file to customize configuration:

```env
# Ollama service URL
OLLAMA_BASE_URL=http://localhost:11434

# Model configuration
CHAT_MODEL=qwen3.6:27b                      # Chat model
EMBED_MODEL=qwen3-embedding:4b               # Embedding model (⚠️ rebuild index on change)
RERANK_MODEL=qllama/bge-reranker-v2-m3:f16  # Rerank model
OCR_MODEL=qwen2.5vl:7b                                   # OCR vision model (leave empty to disable, e.g. qwen2.5vl:7b)

# RAG parameters
TOP_K=6                # Vector search recall count
RERANK_TOP_K=4         # Top results after reranking
CHUNK_SIZE=500         # Document chunk size (tokens)
CHUNK_OVERLAP=50       # Chunk overlap size (tokens)

# Service configuration
HOST=0.0.0.0
PORT=8001
```

### 🔌 API Documentation

Visit [http://localhost:8001/docs](http://localhost:8001/docs) after starting the service to view the complete Swagger API documentation.

### 🤝 Contributing

Issues and Pull Requests are welcome!

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

### 👨‍💻 Author

**kimikang**

📧 86941737@qq.com

---

<div align="center">

**⭐ Star this repository if you find it helpful!**

Made with ❤️ by kimikang

</div>
