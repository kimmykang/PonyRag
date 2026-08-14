# 🤖 ponyrag — 企业或者私人的本地知识库系统

> 基于本地大模型（Ollama）的 RAG 智能问答系统，专为企业或私人知识库场景设计。支持多知识库管理、文档上传、语义检索与多轮对话。

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.138-green?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-1.5-purple)](https://www.trychroma.com/)
[![Ollama](https://img.shields.io/badge/Ollama-Local-orange?logo=ollama&logoColor=white)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey)](LICENSE)

[快速开始](#-快速开始) • [功能特性](#-功能特性) • [技术架构](#-技术架构) • [API 文档](#-api-文档) • [常见问题](#-常见问题)

---

## 📸 界面预览

### 聊天界面
- 左侧：系统状态、知识库选择、聊天历史
- 中间：对话区域、AI 回答附带参考来源
- 右上角：模型设置与参数调整

### 知识库管理
- 创建/编辑/启用/禁用知识库
- 上传文档（自动解析为 Markdown）
- 查看向量库条目统计和文件列表
- 删除文档（自动清理向量数据）

---

## ✨ 功能特性

- **多知识库管理** — 创建、编辑、启用/禁用多个独立知识库，每库独立向量空间
- **文档上传与解析** — 支持 PDF、DOCX、XLSX、PPTX、TXT、MD 等格式，自动转 Markdown 后索引
- **语义检索 + Rerank** — ChromaDB 向量检索召回，Rerank 模型精排，提升答案相关性
- **多轮对话** — 保留聊天历史，支持上下文关联问答
- **模型热切换** — 前端界面直接切换 Chat / Embed / Rerank 模型，无需修改配置文件
- **Embedding 一致性保护** — 切换 Embed 模型时自动清空旧向量库并重新索引，避免维度冲突
- **参数可调** — 前端参数设置页面实时调整 TOP_K、RERANK_TOP_K、CHUNK_SIZE 等 RAG 参数
- **完全本地运行** — 所有模型通过 Ollama 在本地推理，数据不出本机

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────┐
│                    Browser (前端)                    │
│  index.html + knowledge.html + app.js + style.css   │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP REST API
┌──────────────────────▼──────────────────────────────┐
│              FastAPI 后端 (app.py)                   │
│                                                     │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────┐  │
│  │ RAG Engine   │  │ Doc Processor │  │ KB管理   │  │
│  │ rag_engine   │  │ doc_processor │  │ knowledge│  │
│  │ vector_store │  │ (markitdown)  │  │ _base    │  │
│  └──────┬───────┘  └───────────────┘  └──────────┘  │
│         │                                            │
│  ┌──────▼──────────────────────────────────────┐    │
│  │           ChromaDB (向量数据库)              │    │
│  │   每个知识库一个 Collection，持久化存储      │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │              SQLite (聊天历史)               │   │
│  └──────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP (localhost:11434)
┌──────────────────────▼──────────────────────────────┐
│                  Ollama 本地推理                     │
│   Chat Model │ Embedding Model │ Rerank Model        │
└─────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 环境要求

- Python 3.11+
- [Ollama](https://ollama.com/) 已安装并运行
- 推荐 16GB+ 内存，有独立显卡效果更佳

### 1. 拉取模型

```bash
# 对话模型（按需选择）
ollama pull qwen3.6:27b        # 推荐，中文效果好
# ollama pull qwen2.5:7b       # 轻量替代

# 嵌入模型
ollama pull qwen3-embedding:4b  # 2560维，速度快
# ollama pull qwen3-embedding:8b # 4096维，精度更高

# Rerank 模型
ollama pull qllama/bge-reranker-v2-m3:f16  # 推荐，中英文均衡
```

### 2. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 3. 配置参数（可选）

复制并编辑配置文件：

```bash
cp backend/.env.example backend/.env
```

或直接编辑 `backend/.env`：

```env
CHAT_MODEL=qwen3.6:27b
EMBED_MODEL=qwen3-embedding:4b
RERANK_MODEL=qllama/bge-reranker-v2-m3:f16
TOP_K=6
RERANK_TOP_K=4
```

### 4. 启动服务

**Windows：**
```bash
start.bat
```

**Windows（Conda 环境）：**
```bash
"start for conda.bat"
```

**Linux / macOS：**
```bash
chmod +x start.sh && ./start.sh
```

**手动启动：**
```bash
cd backend && python app.py
```

服务启动后浏览器会自动打开 [http://localhost:8001](http://localhost:8001)

---

## 📁 项目结构

```
insureai/
├── backend/
│   ├── app.py                # FastAPI 主应用，所有 API 路由
│   ├── rag_engine.py         # RAG 引擎：检索 → Rerank → LLM 生成
│   ├── vector_store.py       # ChromaDB 向量库封装
│   ├── document_processor.py # 文档解析、分块
│   ├── knowledge_base.py     # 知识库元数据管理（SQLite）
│   ├── chat_history.py       # 聊天历史存储
│   ├── config.py             # 配置加载（读取 .env）
│   ├── requirements.txt      # Python 依赖
│   ├── .env                  # 环境配置（模型、路径、参数）
│   ├── uploads/              # 上传文件存储（按知识库分目录）
│   └── vector_db/            # ChromaDB 持久化数据
├── frontend/
│   ├── index.html            # 聊天主页面
│   ├── knowledge.html        # 知识库管理页面
│   ├── app.js                # 聊天页面逻辑
│   ├── knowledge.js          # 知识库管理逻辑
│   └── style.css             # 全局样式
├── start.bat                 # Windows 启动脚本
├── start for conda.bat       # Windows Conda 环境启动
└── start.sh                  # Linux/macOS 启动脚本
```

---

## ⚙️ 配置说明

### `.env` 完整参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 服务地址 |
| `CHAT_MODEL` | `qwen3.6:27b` | 对话生成模型 |
| `EMBED_MODEL` | `qwen3-embedding:4b` | 文本向量化模型 |
| `RERANK_MODEL` | `qllama/bge-reranker-v2-m3:f16` | 检索结果精排模型 |
| `VECTOR_DB_PATH` | `./vector_db` | ChromaDB 数据目录 |
| `UPLOAD_DIR` | `./uploads` | 文件上传目录 |
| `HOST` | `0.0.0.0` | 服务监听地址 |
| `PORT` | `8001` | 服务监听端口 |
| `TOP_K` | `6` | 向量检索召回数量 |
| `RERANK_TOP_K` | `4` | Rerank 后保留数量（送入 LLM） |
| `CHUNK_SIZE` | `500` | 文档分块大小（token） |
| `CHUNK_OVERLAP` | `50` | 分块重叠大小（token） |

> **⚠️ 注意：** 修改 `EMBED_MODEL` 后，已有向量库与新模型维度不兼容。系统会在重启时自动检测并清空旧向量库，重新索引所有文档。也可通过前端「设置 → 模型设置」切换，系统会自动处理。

---

## 📖 使用指南

### 知识库管理

1. 点击顶栏「知识库管理」图标或左侧导航进入管理页面
2. 点击「创建知识库」，填写名称和描述
3. 点击知识库卡片上的「管理文档」，上传 PDF/DOCX/XLSX 等文件
4. 文档上传后自动解析并向量化，可立即用于问答

### 聊天问答

1. 在左侧「系统状态」区域选择要检索的知识库（默认检索全部已启用的）
2. 在输入框输入问题，按 Enter 发送
3. AI 回答会附带「参考来源」，显示来自哪个文档的哪一段

### 模型与参数设置

点击右上角⚙️ 图标打开设置面板：

- **模型设置** — 切换 Chat / Embed / Rerank 模型（从本地 Ollama 已安装的模型中选择）
- **参数设置** — 调整 TOP_K、RERANK_TOP_K、CHUNK_SIZE 等 RAG 参数，实时生效

---

## 🔌 API 文档

启动后访问 [http://localhost:8001/docs](http://localhost:8001/docs) 查看完整 Swagger 文档。

主要接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 聊天问答 |
| `GET` | `/api/knowledge-bases` | 获取知识库列表 |
| `POST` | `/api/knowledge-bases` | 创建知识库 |
| `POST` | `/api/upload` | 上传文档 |
| `GET` | `/api/documents` | 获取文档列表 |
| `DELETE` | `/api/documents/{filename}` | 删除文档 |
| `GET` | `/api/stats` | 获取统计信息 |
| `GET` | `/api/model-status` | 获取模型加载状态 |
| `POST` | `/api/config/models` | 切换模型 |
| `GET/POST` | `/api/config/rag-params` | 读取/保存 RAG 参数 |

---

## 🛠️ 常见问题

**Q: 启动后模型一直显示「加载中」？**

Ollama 首次加载大模型需要将权重载入显存，耗时 30 秒到几分钟不等，请耐心等待。可在 Ollama 终端查看加载进度。

**Q: 提问返回「知识库中暂无相关内容」？**

- 确认知识库中已上传文档，且向量库条目数 > 0
- 检查所选知识库是否已启用
- 若刚换过 Embed 模型，等待重新索引完成

**Q: Windows 下请求 Ollama 返回 502？**

系统代理可能拦截了 localhost 请求。项目已内置代理绕过逻辑，若仍有问题，请在系统代理设置中将 `127.0.0.1` 和 `localhost` 加入排除列表。

**Q: 上传 XLSX/PPTX 文件失败？**

确保安装了 `markitdown` 依赖：
```bash
pip install markitdown
```

**Q: 切换 Embedding 模型后提示维度不匹配？**

不同的 Embedding 模型输出维度不同（如 `qwen3-embedding:4b` 是 2560 维，`:8b` 是 4096 维）。系统会自动检测并提示重建向量库。点击确认后会自动删除旧向量数据并重新索引所有文档。

**Q: 如何提升检索速度？**

1. 降低 `TOP_K` 和 `RERANK_TOP_K`（设置 → 参数设置）
2. 使用更小的 Embedding 模型（如 `:4b` 而非 `:8b`）
3. 减小文档分块大小 `CHUNK_SIZE`
4. 有条件的话使用 GPU 运行 Ollama

**Q: 支持哪些文档格式？**

目前支持：
- 文本类：TXT, MD, CSV
- 文档类：PDF, DOCX, PPTX, XLSX
- 未来计划支持：HTML, JSON, 图片（OCR）

---

## ⚡ 性能优化建议

### 推荐配置

| 内存 | 推荐模型组合 | 预期速度 |
|------|-------------|---------|
| 16GB | qwen2.5:7b + qwen3-embedding:4b | 中等，适合个人使用 |
| 32GB | qwen3.6:27b + qwen3-embedding:4b | 快速，生产可用 |
| 64GB+ | qwen3.6:27b + qwen3-embedding:8b | 最佳精度和速度 |

### TOP_K 参数调优

- **准确度优先**：`TOP_K=10`, `RERANK_TOP_K=6`（检索更全面，但慢 30%）
- **平衡**（默认）：`TOP_K=6`, `RERANK_TOP_K=4`（推荐）
- **速度优先**：`TOP_K=3`, `RERANK_TOP_K=2`（快 50%，但可能漏召回）

### GPU 加速

如有 NVIDIA 显卡，确保 Ollama 使用 GPU：

```bash
# Windows 检查
ollama run qwen3.6:27b "test"  # 观察输出是否显示 GPU

# Linux 检查
nvidia-smi  # 运行模型时观察显存占用
```

---

## 🚧 开发路线

- [x] 多知识库管理
- [x] 文档上传与自动解析
- [x] 向量检索 + Rerank
- [x] 多轮对话历史
- [x] 模型热切换
- [x] 参数动态调整
- [ ] 文档在线预览
- [ ] 导出聊天记录
- [ ] 多用户权限管理
- [ ] Docker 一键部署
- [ ] 知识库版本管理

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

## 📄 License

MIT License — 自由使用、修改和分发。
