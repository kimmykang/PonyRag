/**
 * ponyrag知识库系统 - 前端交互逻辑
 * 
 * 作者: kimikang
 * 
 * 职责：
 *   - 提供用户交互界面：聊天、文档上传、模型管理
 *   - 与后端 FastAPI 服务通信（RESTful API）
 *   - 实时轮询模型加载状态，展示给用户
 *   - 管理会话状态（session_id、chat_history）
 * 
 * 主要功能模块：
 *   1. 连接检测：检查后端服务可用性
 *   2. 模型状态：轮询三个模型的加载进度，显示在侧边栏和顶栏
 *   3. 文档管理：上传、删除、列表展示
 *   4. 聊天对话：发送问题、流式打字效果、Markdown 渲染、来源引用
 *   5. 模型设置：动态切换 Ollama 模型并触发后端重新加载
 */

// ──────────────────────────────────────────────────────────────
// 全局配置与状态
// ──────────────────────────────────────────────────────────────

// API 基础地址（自动根据当前页面 URL 确定，支持任意端口部署）
const API_BASE = window.location.origin;

// 应用全局状态管理（单一数据源）
const state = {
    sessionId: crypto.randomUUID().slice(0, 8), // 会话 ID，用于后端关联多轮对话（前 8 位即可）
    chatHistory: [], // 历史对话记录，格式 [["user", "内容"], ["assistant", "内容"]]
    isProcessing: false, // 是否正在处理聊天请求（防止重复提交）
    documents: [], // 已上传的文档列表（从后端获取）
    connected: false, // 后端连接状态
    currentKbId: 'knowledge_base', // 当前选中的知识库 ID
    knowledgeBases: [], // 知识库列表
    selectedKbIds: null, // 用户选择的知识库ID列表，null表示所有已启用的知识库
};

// DOM 元素引用（集中管理，避免重复 querySelector）
const dom = {
    // 布局相关
    sidebar: document.getElementById('sidebar'), // 侧边栏容器
    sidebarToggle: document.getElementById('sidebarToggle'), // 侧边栏折叠按钮
    menuBtn: document.getElementById('menuBtn'), // 移动端菜单按钮

    // 知识库选择
    currentKbSelect: document.getElementById('currentKbSelect'), // 知识库选择下拉框

    // 文档上传相关
    fileInput: document.getElementById('fileInput'), // 隐藏的文件选择 input
    uploadBtn: document.getElementById('uploadBtn'), // 上传按钮
    uploadArea: document.getElementById('uploadArea'), // 上传区域（拖拽）
    uploadProgress: document.getElementById('uploadProgress'), // 上传进度条容器
    progressFill: document.getElementById('progressFill'), // 进度填充条
    progressText: document.getElementById('progressText'), // 进度提示文字
    documentList: document.getElementById('documentList'), // 文档列表容器

    // 统计与控制
    chatKbSelect: document.getElementById('chatKbSelect'), // 知识库选择下拉框
    dbCount: document.getElementById('dbCount'), // 向量数统计
    fileCount: document.getElementById('fileCount'), // 文件数统计

    // 聊天相关
    chatContainer: document.getElementById('chatContainer'), // 聊天消息滚动容器
    messages: document.getElementById('messages'), // 消息列表
    welcomeMessage: document.getElementById('welcomeMessage'), // 欢迎消息（首次进入显示）
    chatForm: document.getElementById('chatForm'), // 聊天输入表单
    questionInput: document.getElementById('questionInput'), // 问题输入框
    sendBtn: document.getElementById('sendBtn'), // 发送按钮

    // 连接状态
    connectionStatus: document.getElementById('connectionStatus'), // 后端连接状态指示器

    // 模型状态指示器
    modelLoadStatus: document.getElementById('modelLoadStatus'), // 顶栏模型加载汇总指示器
    modelLoadDot: document.querySelector('#modelLoadStatus .model-load-dot'), // 顶栏状态点
    modelLoadText: document.querySelector('#modelLoadStatus .model-load-text'), // 顶栏状态文字
    msChat: document.getElementById('ms-chat'), // 侧边栏：对话模型状态行
    msEmbed: document.getElementById('ms-embed'), // 侧边栏：嵌入模型状态行
    msRerank: document.getElementById('ms-rerank'), // 侧边栏：Rerank 模型状态行

    // 设置
    settingsBtn: document.getElementById('settingsBtn'), // 设置按钮（齿轮图标）
    clearChatBtn: document.getElementById('clearChatBtn'), // 清空聊天记录按钮
};

// ──────────────────────────────────────────────────────────────
// 应用初始化
// ──────────────────────────────────────────────────────────────

/**
 * 页面加载完成后自动执行的初始化流程
 * 
 * 执行顺序：
 *   1. 绑定所有事件监听器（用户交互）
 *   2. 检查后端服务连接状态
 *   3. 加载已上传的文档列表
 *   4. 加载统计数据（文档数、向量数）
 *   5. 从后端恢复聊天历史记录
 *   6. 启动模型状态轮询（每 3 秒检查一次）
 */
document.addEventListener('DOMContentLoaded', async () => {
    initTheme(); // 先应用主题，避免样式跳变
    applyLang(); // 应用当前语言
    _updateLangToggleBtn(); // 初始化语言切换按钮
    initEventListeners();
    checkConnection();

    // 检查是否从知识库管理页面跳转过来
    const savedKbId = localStorage.getItem('current_kb_id');
    if (savedKbId) {
        state.currentKbId = savedKbId;
        state.selectedKbIds = [savedKbId]; // 同步到聊天用的知识库选择
        localStorage.removeItem('current_kb_id');
    }

    // 检查是否需要打开文档面板
    const openDocsPanel = localStorage.getItem('open_documents_panel');
    if (openDocsPanel === 'true') {
        localStorage.removeItem('open_documents_panel');
        // 文档面板默认就是展开的，无需额外操作
    }

    // 先加载知识库列表，等待完成后再加载文档和统计
    await loadKnowledgeBases();
    await loadDocuments();
    await loadStats();
    loadChatHistory(); // 恢复历史聊天记录
    pollModelStatus();
    updateOcrModelStatus(); // 初始显示 OCR 模型状态
});

/**
 * 绑定所有 DOM 事件监听器
 * 
 * 涵盖功能：
 *   - 侧边栏展开/折叠（移动端/桌面端）
 *   - 模型设置 Modal 打开
 *   - 文件上传（点击按钮 + 文件选择回调）
 *   - 聊天表单提交
 *   - 输入框自动调整高度
 *   - Enter 发送（Shift+Enter 换行）
 *   - 示例问题快捷点击
 *   - 清空向量库（带确认 Modal）
 */
function initEventListeners() {
    // 侧边栏切换（桌面端折叠/移动端滑出）
    dom.menuBtn.addEventListener('click', toggleSidebar);
    dom.sidebarToggle.addEventListener('click', toggleSidebar);

    // 模型设置（点击齿轮打开 Modal）
    dom.settingsBtn.addEventListener('click', openSettingsModal);

    // 清空聊天记录按钮
    dom.clearChatBtn.addEventListener('click', () => {
        showClearChatModal();
    });

    // 知识库选择器（仅在知识库管理页面存在）
    if (dom.currentKbSelect) {
        dom.currentKbSelect.addEventListener('change', async (e) => {
            state.currentKbId = e.target.value;
            await loadDocuments();
            await loadStats();
        });
    }

    // 聊天页面的知识库选择器
    if (dom.chatKbSelect) {
        dom.chatKbSelect.addEventListener('change', (e) => {
            const value = e.target.value;
            if (value === 'all') {
                state.selectedKbIds = null; // null 表示所有已启用的知识库
            } else {
                state.selectedKbIds = [value]; // 选择单个知识库
            }
            console.log('[chatKbSelect] 选择的知识库:', state.selectedKbIds);
            // 切换知识库时刷新统计数字
            loadStats();
        });
    }

    // 文件上传（仅在知识库管理页面存在）
    if (dom.uploadBtn && dom.fileInput) {
        dom.uploadBtn.addEventListener('click', () => dom.fileInput.click());
        dom.fileInput.addEventListener('change', handleFileUpload);
    }

    // 聊天表单提交
    dom.chatForm.addEventListener('submit', handleChatSubmit);

    // 输入框输入时：自动调整高度 + 更新发送按钮状态
    dom.questionInput.addEventListener('input', () => {
        autoResizeTextarea(dom.questionInput);
        toggleSendButton();
    });

    // Enter 发送，Shift+Enter 换行（常见聊天界面交互）
    dom.questionInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!dom.sendBtn.disabled) {
                dom.chatForm.requestSubmit();
            }
        }
    });

    // 示例问题点击：将问题填入输入框并自动提交
    document.querySelectorAll('.example-q').forEach(btn => {
        btn.addEventListener('click', () => {
            const q = btn.dataset.q;
            if (q) {
                dom.questionInput.value = q;
                toggleSendButton();
                dom.chatForm.requestSubmit();
            }
        });
    });

    // 添加 DOM 引用
    dom.reindexProgress = document.getElementById('reindexProgress');
    dom.reindexCount = document.getElementById('reindexCount');
    dom.reindexProgressFill = document.getElementById('reindexProgressFill');
    dom.reindexStatus = document.getElementById('reindexStatus');
}

// ============================================================
// 知识库管理
// ============================================================

async function loadKnowledgeBases() {
    try {
        const res = await fetch(`${API_BASE}/api/knowledge-bases`);
        const data = await res.json();
        state.knowledgeBases = data.knowledge_bases || [];
        console.log('[loadKnowledgeBases] 加载知识库列表:', state.knowledgeBases);

        // 如果当前知识库不存在于列表中，使用第一个知识库或默认值
        if (!state.knowledgeBases.find(kb => kb.kb_id === state.currentKbId)) {
            const defaultKb = state.knowledgeBases.find(kb => kb.kb_id === 'knowledge_base');
            if (defaultKb) {
                state.currentKbId = 'knowledge_base';
            } else if (state.knowledgeBases.length > 0) {
                state.currentKbId = state.knowledgeBases[0].kb_id;
            }
            console.log('[loadKnowledgeBases] 当前知识库ID重置为:', state.currentKbId);
        }

        renderKnowledgeBaseSelector();
        renderChatKbSelector(); // 渲染聊天页面的知识库选择器
    } catch (e) {
        console.error('加载知识库列表失败:', e);
    }
}

function renderKnowledgeBaseSelector() {
    const select = dom.currentKbSelect;
    if (!select) {
        console.log('[renderKnowledgeBaseSelector] 选择器不存在（聊天页面不需要）');
        return;
    }

    select.innerHTML = state.knowledgeBases.map(kb => {
        const enabled = kb.enabled ? '' : ' (已禁用)';
        return `<option value="${kb.kb_id}" ${kb.kb_id === state.currentKbId ? 'selected' : ''}>${escapeHtml(kb.name)}${enabled}</option>`;
    }).join('');

    // 确保当前选中的知识库存在于列表中
    if (!state.knowledgeBases.find(kb => kb.kb_id === state.currentKbId)) {
        state.currentKbId = 'knowledge_base';
        select.value = 'knowledge_base';
    }
}

function renderChatKbSelector() {
    const select = dom.chatKbSelect;
    if (!select) {
        return;
    }

    const enabledKbs = state.knowledgeBases.filter(kb => kb.enabled);

    // "所有已启用的知识库"选项用 t() 翻译
    let options = `<option value="all">${t('sidebar.allKb')}</option>`;

    // 知识库名称：默认知识库走 i18n，其他直接显示
    options += enabledKbs.map(kb => {
        const displayName = kb.kb_id === 'knowledge_base' ? t('kb.defaultName') : escapeHtml(kb.name);
        return `<option value="${kb.kb_id}">${displayName}</option>`;
    }).join('');

    select.innerHTML = options;

    if (state.selectedKbIds && state.selectedKbIds.length === 1) {
        const targetId = state.selectedKbIds[0];
        if (enabledKbs.find(kb => kb.kb_id === targetId)) {
            select.value = targetId;
        }
    }
}

// ============================================================
// 侧边栏
// ============================================================

function toggleSidebar() {
    const sidebar = dom.sidebar;
    const isMobile = window.innerWidth <= 768;

    if (isMobile) {
        sidebar.classList.toggle('open');
        // 添加/移除遮罩
        let overlay = document.querySelector('.sidebar-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'sidebar-overlay';
            document.body.appendChild(overlay);
            overlay.addEventListener('click', toggleSidebar);
        }
        overlay.classList.toggle('active', sidebar.classList.contains('open'));
    } else {
        sidebar.classList.toggle('collapsed');
        const mainContent = document.querySelector('.main-content');
        if (sidebar.classList.contains('collapsed')) {
            mainContent.style.width = '100%';
        } else {
            mainContent.style.width = '';
        }
    }
}

// ============================================================
// 连接检测
// ============================================================

async function checkConnection() {
    try {
        const res = await fetch(`${API_BASE}/api/health`);
        const data = await res.json();

        if (data.status === 'ok') {
            state.connected = true;
            updateConnectionStatus(true);
        } else {
            updateConnectionStatus(false);
        }
    } catch (e) {
        updateConnectionStatus(false);
    }
}

function updateConnectionStatus(connected) {
    const el = dom.connectionStatus;
    const dot = el.querySelector('.status-dot');
    const text = el.querySelector('.status-text');

    if (connected) {
        dot.className = 'status-dot connected';
        text.textContent = t('app.connected');
    } else {
        dot.className = 'status-dot disconnected';
        text.textContent = t('app.disconnected');
    }
}

// ============================================================
// 删除确认 Modal
// ============================================================

function showDeleteModal(filename, onConfirm) {
    const modal = document.getElementById('deleteModal');
    document.getElementById('deleteModalBody').textContent = `确定要删除「${filename}」吗？`;
    modal.style.display = 'flex';

    const confirmBtn = document.getElementById('deleteConfirmBtn');
    const cancelBtn = document.getElementById('deleteCancelBtn');

    function close() {
        modal.style.display = 'none';
        confirmBtn.replaceWith(confirmBtn.cloneNode(true));
        cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    }

    // 重新获取（replaceWith 后旧引用失效）
    document.getElementById('deleteConfirmBtn').addEventListener('click', () => {
        close();
        onConfirm();
    });
    document.getElementById('deleteCancelBtn').addEventListener('click', close);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) close();
    }, {
        once: true
    });
}

// ============================================================
// 模型设置 Modal
// ============================================================

async function openSettingsModal() {
    const modal = document.getElementById('settingsModal');
    const hint = document.getElementById('settingsHint');
    hint.textContent = '';

    // 刷新所有 data-i18n 静态文字
    applyLang();

    // 加载模型列表和参数（并行请求）
    const [statusRes, ollamaRes, paramsRes, modelsRes] = await Promise.all([
        fetch(`${API_BASE}/api/model-status`).then(r => r.json()).catch(() => ({})),
        fetch(`${API_BASE}/api/ollama/models`).then(r => r.json()).catch(() => ({
            models: []
        })),
        fetch(`${API_BASE}/api/config/rag-params`).then(r => r.json()).catch(() => ({})),
        fetch(`${API_BASE}/api/models`).then(r => r.json()).catch(() => ({})),
    ]);

    const currentModels = statusRes.models || {};
    const allModels = ollamaRes.models || [];
    const currentOcrModel = modelsRes.ocr_model || '';

    function fillSelect(id, currentName) {
        const sel = document.getElementById(id);
        sel.innerHTML = '';
        if (allModels.length === 0) {
            sel.innerHTML = '<option value="">（无法获取模型列表）</option>';
            return;
        }
        allModels.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.name;
            opt.textContent = m.name;
            if (m.name === currentName) opt.selected = true;
            sel.appendChild(opt);
        });
        if (!allModels.find(m => m.name === currentName) && currentName) {
            const opt = document.createElement('option');
            opt.value = currentName;
            opt.textContent = currentName + ' (当前)';
            opt.selected = true;
            sel.prepend(opt);
        }
    }

    fillSelect('chatModelSelect', (currentModels.chat && currentModels.chat.model) || '');
    fillSelect('embedModelSelect', (currentModels.embed && currentModels.embed.model) || '');
    fillSelect('rerankModelSelect', (currentModels.rerank && currentModels.rerank.model) || '');

    // OCR 模型下拉：额外加一个"禁用 OCR"选项
    const ocrSel = document.getElementById('ocrModelSelect');
    ocrSel.innerHTML = '<option value="">-- 禁用 OCR --</option>';
    allModels.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.name;
        opt.textContent = m.name;
        if (m.name === currentOcrModel) opt.selected = true;
        ocrSel.appendChild(opt);
    });
    if (!currentOcrModel) ocrSel.value = '';
    else if (!allModels.find(m => m.name === currentOcrModel)) {
        const opt = document.createElement('option');
        opt.value = currentOcrModel;
        opt.textContent = currentOcrModel + ' (当前)';
        opt.selected = true;
        ocrSel.prepend(opt);
    }

    // 填充参数设置的初始值
    if (paramsRes) {
        setParamValue('topK', paramsRes.top_k || 10);
        setParamValue('rerankTopK', paramsRes.rerank_top_k || 5);
        setParamValue('chunkSize', paramsRes.chunk_size || 500);
        setParamValue('chunkOverlap', paramsRes.chunk_overlap || 50);
        setParamValue('numCtx', paramsRes.num_ctx || 4096);
        // 切分方式：选中对应 radio，并初始化分块参数显隐
        const method = paramsRes.chunk_method || 'recursive';
        const radioEl = document.querySelector(`input[name="chunkMethod"][value="${method}"]`);
        if (radioEl) radioEl.checked = true;
        _updateChunkParamVisibility(method);

        // 监听切分方式切换，动态显隐分块参数
        document.querySelectorAll('input[name="chunkMethod"]').forEach(r => {
            r.addEventListener('change', () => _updateChunkParamVisibility(r.value));
        });
    }

    // Tab 切换逻辑
    document.getElementById('tabModelBtn').onclick = () => switchTab('model');
    document.getElementById('tabParamsBtn').onclick = () => switchTab('params');
    const tabGeneralBtn = document.getElementById('tabGeneralBtn');
    if (tabGeneralBtn) tabGeneralBtn.onclick = () => switchTab('general');
    // 默认显示模型设置 Tab
    switchTab('model');

    // 通用设置：读取流式输出开关状态
    const streamingToggle = document.getElementById('streamingToggle');
    if (streamingToggle) streamingToggle.checked = loadGeneralSetting('streaming', false);

    // 通用设置：同步主题选中状态
    const currentTheme = loadGeneralSetting('theme', 'light');
    const lightEl = document.getElementById('themeLight');
    const darkEl = document.getElementById('themeDark');
    if (lightEl) lightEl.classList.toggle('active', currentTheme === 'light');
    if (darkEl) darkEl.classList.toggle('active', currentTheme === 'dark');

    // 通用设置：同步语言选中状态
    const currentLang = getCurrentLang();
    const zhEl = document.getElementById('langZh');
    const enEl = document.getElementById('langEn');
    if (zhEl) zhEl.classList.toggle('active', currentLang === 'zh');
    if (enEl) enEl.classList.toggle('active', currentLang === 'en');

    modal.style.display = 'flex';

    const closeModal = () => {
        modal.style.display = 'none';
    };
    document.getElementById('settingsCloseBtn').onclick = closeModal;
    document.getElementById('settingsCancelBtn').onclick = closeModal;
    document.getElementById('paramsCancelBtn').onclick = closeModal;
    const generalCancelBtn = document.getElementById('generalCancelBtn');
    if (generalCancelBtn) generalCancelBtn.onclick = closeModal;

    // 通用设置保存
    const generalSaveBtn = document.getElementById('generalSaveBtn');
    if (generalSaveBtn) {
        generalSaveBtn.onclick = () => {
            const tog = document.getElementById('streamingToggle');
            if (tog) saveGeneralSetting('streaming', tog.checked);
            closeModal();
        };
    }
    modal.onclick = (e) => {
        if (e.target === modal) closeModal();
    };

    // 参数保存按钮
    document.getElementById('paramsSaveBtn').onclick = async () => {
        const paramsHint = document.getElementById('paramsHint');
        const topK = parseInt(document.getElementById('topKInput').value);
        const rerankTopK = parseInt(document.getElementById('rerankTopKInput').value);
        const chunkSize = parseInt(document.getElementById('chunkSizeInput').value);
        const chunkOverlap = parseInt(document.getElementById('chunkOverlapInput').value);
        const numCtx = parseInt(document.getElementById('numCtxInput').value);
        const chunkMethodEl = document.querySelector('input[name="chunkMethod"]:checked');
        const chunkMethod = chunkMethodEl ? chunkMethodEl.value : 'recursive';

        if (rerankTopK > topK) {
            paramsHint.textContent = '精排数量不能超过召回数量';
            paramsHint.style.color = 'var(--danger)';
            return;
        }

        paramsHint.textContent = '保存中...';
        paramsHint.style.color = 'var(--text-secondary)';
        document.getElementById('paramsSaveBtn').disabled = true;

        try {
            const res = await fetch(`${API_BASE}/api/config/rag-params`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    top_k: topK,
                    rerank_top_k: rerankTopK,
                    chunk_size: chunkSize,
                    chunk_overlap: chunkOverlap,
                    num_ctx: numCtx,
                    chunk_method: chunkMethod,
                }),
            });
            const data = await res.json();
            if (res.ok) {
                paramsHint.textContent = '✅ 参数已保存并立即生效';
                paramsHint.style.color = 'var(--success)';
                setTimeout(() => closeModal(), 1500);
            } else {
                paramsHint.textContent = '保存失败: ' + (data.detail || data.message);
                paramsHint.style.color = 'var(--danger)';
            }
        } catch (e) {
            paramsHint.textContent = '请求失败: ' + e.message;
            paramsHint.style.color = 'var(--danger)';
        } finally {
            document.getElementById('paramsSaveBtn').disabled = false;
        }
    };

    document.getElementById('settingsSaveBtn').onclick = async () => {
        const newChat = document.getElementById('chatModelSelect').value;
        const newEmbed = document.getElementById('embedModelSelect').value;
        const newRerank = document.getElementById('rerankModelSelect').value;
        const newOcr = document.getElementById('ocrModelSelect').value;

        const changed =
            newChat !== ((currentModels.chat && currentModels.chat.model) || '') ||
            newEmbed !== ((currentModels.embed && currentModels.embed.model) || '') ||
            newRerank !== ((currentModels.rerank && currentModels.rerank.model) || '') ||
            newOcr !== currentOcrModel;

        if (!changed) {
            hint.textContent = '模型未变更';
            return;
        }

        // 检测 embedding 模型变更
        const embedChanged = newEmbed !== ((currentModels.embed && currentModels.embed.model) || '');

        // 如果 embedding 模型变更，显示警告对话框
        if (embedChanged) {
            showEmbedWarningModal(() => {
                saveModelConfig(newChat, newEmbed, newRerank, newOcr, hint, closeModal);
            });
            return;
        }

        // 其他模型变更直接保存
        saveModelConfig(newChat, newEmbed, newRerank, newOcr, hint, closeModal);
    };
}

// ============================================================
// 设置 Modal 辅助函数
// ============================================================

/**
 * 切换设置 Modal 中的 Tab
 */
function switchTab(tab) {
    const modelContent = document.getElementById('tabModelContent');
    const paramsContent = document.getElementById('tabParamsContent');
    const generalContent = document.getElementById('tabGeneralContent');
    const modelBtn = document.getElementById('tabModelBtn');
    const paramsBtn = document.getElementById('tabParamsBtn');
    const generalBtn = document.getElementById('tabGeneralBtn');

    modelContent.style.display = tab === 'model' ? 'block' : 'none';
    paramsContent.style.display = tab === 'params' ? 'block' : 'none';
    if (generalContent) generalContent.style.display = tab === 'general' ? 'block' : 'none';

    modelBtn.classList.toggle('active', tab === 'model');
    paramsBtn.classList.toggle('active', tab === 'params');
    if (generalBtn) generalBtn.classList.toggle('active', tab === 'general');
}

/**
 * 设置滑块+数字输入框的值，并绑定联动事件（只绑定一次）
 */
function setParamValue(name, value) {
    const rangeEl = document.getElementById(name + 'Range');
    const inputEl = document.getElementById(name + 'Input');
    if (!rangeEl || !inputEl) return;

    rangeEl.value = value;
    inputEl.value = value;

    // 避免重复绑定
    if (!rangeEl._bound) {
        rangeEl.addEventListener('input', () => {
            inputEl.value = rangeEl.value;
        });
        inputEl.addEventListener('input', () => {
            rangeEl.value = inputEl.value;
        });
        rangeEl._bound = true;
    }
}

/**
 * 手动重新加载指定模型（用于超时或加载失败后重试）
 * @param {string} modelKey - "chat" | "embed" | "rerank"
 */
async function reloadModel(modelKey) {
    // 找到对应的刷新按钮，加旋转动画
    const item = document.getElementById(`ms-${modelKey}`);
    const btn = item && item.querySelector('.model-reload-btn');
    const dot = item && item.querySelector('.model-status-dot');
    const msg = item && item.querySelector('.model-status-msg');

    if (btn) {
        btn.disabled = true;
        btn.classList.add('spinning');
    }
    if (dot) dot.className = 'model-status-dot checking';
    if (msg) msg.textContent = '重新加载中...';

    try {
        const res = await fetch(`${API_BASE}/api/reload-model/${modelKey}`, {
            method: 'POST'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '请求失败');
        if (msg) msg.textContent = data.message || '加载中...';
        // 重置轮询标志，让 pollModelStatus 继续轮询直到就绪
        _allModelsReady = false;
    } catch (e) {
        if (msg) msg.textContent = `重载失败: ${e.message}`;
        if (dot) dot.className = 'model-status-dot error';
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('spinning');
        }
    }
}

/**
 * 显示 Embedding 模型变更警告对话框
 * @param {Function} onConfirm - 用户点击确认后的回调函数
 */
function showEmbedWarningModal(onConfirm) {
    const modal = document.getElementById('embedWarningModal');
    modal.style.display = 'flex';

    const confirmBtn = document.getElementById('embedWarningConfirmBtn');
    const cancelBtn = document.getElementById('embedWarningCancelBtn');

    function close() {
        modal.style.display = 'none';
        // 移除事件监听器，避免重复绑定
        confirmBtn.replaceWith(confirmBtn.cloneNode(true));
        cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    }

    // 重新获取按钮（replaceWith 后旧引用失效）
    document.getElementById('embedWarningConfirmBtn').addEventListener('click', () => {
        close();
        onConfirm();
    });

    document.getElementById('embedWarningCancelBtn').addEventListener('click', close);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) close();
    }, {
        once: true
    });
}

/**
 * 保存模型配置到后端
 */
async function saveModelConfig(chatModel, embedModel, rerankModel, ocrModel, hintElement, closeModalCallback) {
    hintElement.textContent = '正在保存并触发重新加载...';
    document.getElementById('settingsSaveBtn').disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/config/models`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                chat_model: chatModel,
                embed_model: embedModel,
                rerank_model: rerankModel,
                ocr_model: ocrModel,
            }),
        });
        const data = await res.json();
        if (res.ok && data.status === 'success') {
            closeModalCallback();

            // OCR 模型状态立即刷新（不需要轮询，直接读配置）
            updateOcrModelStatus();

            // 只有有模型变更时才启动状态轮询
            if (data.changed_keys && data.changed_keys.length > 0) {
                _allModelsReady = false;
                if (_modelPollTimer) clearTimeout(_modelPollTimer);
                pollModelStatus();
            }

            // embedding 变更：显示重新索引提示 + 启动进度条
            if (data.embed_changed) {
                if (data.reindexing) {
                    showReindexSuccessModal();
                    startReindexPolling();
                }
                loadDocuments();
                loadStats();
            }
        } else {
            hintElement.textContent = '保存失败: ' + (data.detail || data.message || '未知错误');
        }
    } catch (e) {
        hintElement.textContent = '请求失败: ' + e.message;
    } finally {
        document.getElementById('settingsSaveBtn').disabled = false;
    }
}

/**
 * 显示重新索引成功提示模态框
 */
function showReindexSuccessModal() {
    const modal = document.getElementById('reindexSuccessModal');
    modal.style.display = 'flex';

    const okBtn = document.getElementById('reindexSuccessOkBtn');

    function close() {
        modal.style.display = 'none';
        okBtn.replaceWith(okBtn.cloneNode(true));
    }

    // 重新获取按钮（replaceWith 后旧引用失效）
    document.getElementById('reindexSuccessOkBtn').addEventListener('click', close);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) close();
    }, {
        once: true
    });
}


/**
 * 启动重新索引进度轮询
 */
let _reindexPollingTimer = null;

function startReindexPolling() {
    // 清除旧的定时器
    if (_reindexPollingTimer) {
        clearInterval(_reindexPollingTimer);
    }

    // 显示进度条
    dom.reindexProgress.style.display = 'block';

    // 每 1 秒刷新一次进度
    _reindexPollingTimer = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/reindex-status`);
            const data = await res.json();

            // 更新进度条
            dom.reindexCount.textContent = `${data.current}/${data.total}`;
            dom.reindexProgressFill.style.width = `${data.percentage}%`;
            dom.reindexStatus.textContent = data.status;

            // 如果当前文件名存在，显示
            if (data.current_file) {
                dom.reindexStatus.textContent = `${data.status} - ${data.current_file}`;
            }

            // 更新统计数据
            await loadStats();

            // 如果完成，停止轮询
            if (!data.in_progress) {
                clearInterval(_reindexPollingTimer);
                _reindexPollingTimer = null;

                // 显示完成状态
                dom.reindexStatus.textContent = `完成！成功 ${data.success} 个，失败 ${data.failed} 个`;

                // 3 秒后隐藏进度条
                setTimeout(() => {
                    dom.reindexProgress.style.display = 'none';
                    // 最后刷新一次文档列表
                    loadDocuments();
                }, 3000);

                console.log('[ReindexPolling] 重新索引完成');
            }
        } catch (e) {
            console.error('[ReindexPolling] 获取进度失败:', e);
        }
    }, 1000);

    // 最多轮询 10 分钟
    setTimeout(() => {
        if (_reindexPollingTimer) {
            clearInterval(_reindexPollingTimer);
            _reindexPollingTimer = null;
            dom.reindexProgress.style.display = 'none';
            loadDocuments();
            console.log('[ReindexPolling] 轮询超时，停止监控');
        }
    }, 600000);
}


const MODEL_KEY_MAP = {
    chat: {
        el: () => dom.msChat,
        label: '对话模型'
    },
    embed: {
        el: () => dom.msEmbed,
        label: '嵌入模型'
    },
    rerank: {
        el: () => dom.msRerank,
        label: 'Rerank模型'
    },
};

let _modelPollTimer = null;
let _allModelsReady = false;

async function pollModelStatus() {
    if (_allModelsReady) return;
    try {
        const res = await fetch(`${API_BASE}/api/model-status`);
        if (!res.ok) return;
        const data = await res.json();
        const models = data.models || {};

        let anyLoading = false;
        let anyError = false;
        let allReady = true;

        for (const [key, info] of Object.entries(models)) {
            const map = MODEL_KEY_MAP[key];
            if (!map) continue;
            const el = map.el();
            if (!el) continue;

            const dot = el.querySelector('.model-status-dot');
            const msg = el.querySelector('.model-status-msg');
            const shortModel = (info.model || '').split('/').pop();

            dot.className = 'model-status-dot ' + info.status;
            // 用 i18n 翻译状态消息，回退到后端返回的原始消息
            const STATUS_MSG = {
                'checking': t('model.checking'),
                'loading': t('model.loading'),
                'ready': t('model.ready'),
                'error': t('model.error'),
            };
            msg.textContent = STATUS_MSG[info.status] || info.message || '';
            el.title = `${shortModel}\n${msg.textContent}`;

            if (info.status !== 'ready') allReady = false;
            if (info.status === 'loading' || info.status === 'checking') anyLoading = true;
            if (info.status === 'error') anyError = true;
        }

        // 顶栏汇总指示器
        if (anyLoading) {
            dom.modelLoadStatus.style.display = 'inline-flex';
            dom.modelLoadDot.className = 'model-load-dot loading';
            dom.modelLoadText.textContent = t('model.loading.summary');
        } else if (anyError) {
            dom.modelLoadStatus.style.display = 'inline-flex';
            dom.modelLoadDot.className = 'model-load-dot error';
            dom.modelLoadText.textContent = t('model.error.summary');
        } else if (allReady) {
            dom.modelLoadStatus.style.display = 'inline-flex';
            dom.modelLoadDot.className = 'model-load-dot ready';
            dom.modelLoadText.textContent = t('model.ready.summary');
            _allModelsReady = true;
            // 3秒后淡出顶栏提示
            setTimeout(() => {
                dom.modelLoadStatus.style.display = 'none';
            }, 3000);
            return;
        }

        // 同步更新 OCR 模型状态（只需显示是否配置，不需要轮询）
        updateOcrModelStatus();
    } catch (e) {
        // 后端未就绪，继续等待
    }

    _modelPollTimer = setTimeout(pollModelStatus, 3000);
}

// OCR 模型状态：从后端读取当前配置，显示模型名或"未启用"
async function updateOcrModelStatus() {
    const dot = document.getElementById('ms-ocr-dot');
    const msg = document.getElementById('ms-ocr-msg');
    if (!dot || !msg) return;
    try {
        const res = await fetch(`${API_BASE}/api/models`);
        if (!res.ok) return;
        const data = await res.json();
        const ocrModel = data.ocr_model || '';
        if (ocrModel) {
            dot.style.background = 'var(--success)';
            msg.textContent = ocrModel.split('/').pop(); // 只显示模型名短名
        } else {
            dot.style.background = 'var(--text-secondary)';
            msg.textContent = t('model.unconfigured');
        }
    } catch (e) {
        // 忽略
    }
}

// ============================================================
// 文档管理
// ============================================================

async function loadDocuments() {
    // 聊天页面不需要加载文档列表（文档管理在知识库管理页面）
    if (!dom.documentList) {
        console.log('[loadDocuments] 文档列表元素不存在（聊天页面不需要）');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/documents?kb_id=${state.currentKbId}`);
        const data = await res.json();
        state.documents = data.documents || [];
        renderDocuments();
    } catch (e) {
        console.error('加载文档列表失败:', e);
    }
}

function renderDocuments() {
    const list = dom.documentList;
    if (!list) return;

    if (state.documents.length === 0) {
        list.innerHTML = '<div class="empty-state">暂无文档</div>';
        return;
    }

    list.innerHTML = state.documents.map(doc => `
        <div class="doc-item">
            <span class="doc-item-name">${escapeHtml(doc.filename)}</span>
            <span class="doc-item-size">${formatFileSize(doc.size)}</span>
            <button class="doc-item-delete" data-file="${escapeHtml(doc.filename)}" title="删除">×</button>
        </div>
    `).join('');

    // 绑定删除事件
    list.querySelectorAll('.doc-item-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const filename = e.target.dataset.file;
            showDeleteModal(filename, async () => {
                try {
                    const res = await fetch(`${API_BASE}/api/documents/${encodeURIComponent(filename)}?kb_id=${state.currentKbId}`, {
                        method: 'DELETE'
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        console.log(`已删除文档 ${filename}，清除 ${data.vectors_removed || 0} 条向量`);
                    }
                    loadDocuments();
                    loadStats();
                } catch (err) {
                    alert('删除失败: ' + err.message);
                }
            });
        });
    });
}

async function handleFileUpload(e) {
    const files = Array.from(e.target.files);
    if (!files.length) return;

    dom.uploadProgress.style.display = 'block';

    let succeeded = 0;
    let failed = 0;

    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const label = `(${i + 1}/${files.length}) ${file.name}`;

        dom.progressFill.style.background = '';
        dom.progressFill.style.width = '20%';
        dom.progressText.textContent = `上传中 ${label}`;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('kb_id', state.currentKbId); // 添加知识库 ID

        try {
            dom.progressFill.style.width = '60%';
            dom.progressText.textContent = `转换解析 ${label}`;

            const res = await fetch(`${API_BASE}/api/upload`, {
                method: 'POST',
                body: formData,
            });

            dom.progressFill.style.width = '90%';
            dom.progressText.textContent = `向量化 ${label}`;

            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '上传失败');

            dom.progressFill.style.width = '100%';
            dom.progressText.textContent = `完成 ${label}`;
            succeeded++;

        } catch (err) {
            failed++;
            dom.progressFill.style.background = 'var(--danger)';
            dom.progressText.textContent = `失败 ${label}: ${err.message}`;
            await new Promise(r => setTimeout(r, 2000));
            dom.progressFill.style.background = '';
        }
    }

    // 全部完成后统一刷新
    loadDocuments();
    loadStats();
    dom.welcomeMessage.style.display = 'none';

    const summary = failed === 0 ?
        `全部 ${succeeded} 个文件上传完成` :
        `完成 ${succeeded} 个，失败 ${failed} 个`;
    dom.progressText.textContent = summary;

    setTimeout(() => {
        dom.uploadProgress.style.display = 'none';
        dom.progressFill.style.width = '0%';
    }, 2000);

    dom.fileInput.value = '';
}

async function loadStats() {
    try {
        // 根据当前选中的知识库加载对应统计
        // selectedKbIds 为 null 时显示所有知识库总和，为单个 ID 时显示该知识库
        const kbIdParam = (state.selectedKbIds && state.selectedKbIds.length === 1) ?
            state.selectedKbIds[0] :
            'all';
        console.log('[loadStats] 请求统计信息，知识库ID:', kbIdParam);
        const res = await fetch(`${API_BASE}/api/stats?kb_id=${kbIdParam}`);

        if (!res.ok) {
            console.error('[loadStats] API 返回错误:', res.status, res.statusText);
            const errorData = await res.json();
            console.error('[loadStats] 错误详情:', errorData);
            dom.dbCount.textContent = '-';
            dom.fileCount.textContent = '-';
            return;
        }

        const data = await res.json();
        console.log('[loadStats] 收到统计数据:', data);
        dom.dbCount.textContent = data.vector_documents || 0;
        dom.fileCount.textContent = data.uploaded_files || 0;
    } catch (e) {
        console.error('加载统计信息失败:', e);
        dom.dbCount.textContent = '-';
        dom.fileCount.textContent = '-';
    }
}

// ============================================================
// 聊天功能
// ============================================================

async function handleChatSubmit(e) {
    e.preventDefault();

    const question = dom.questionInput.value.trim();
    if (!question || state.isProcessing) return;

    // 隐藏 welcome
    dom.welcomeMessage.style.display = 'none';

    // 添加用户消息（带当前时间）
    addMessage('user', question, [], new Date().toISOString());
    dom.questionInput.value = '';
    autoResizeTextarea(dom.questionInput);
    toggleSendButton();

    // 添加到历史
    state.chatHistory.push(['user', question]);

    // 保持历史长度
    if (state.chatHistory.length > 20) {
        state.chatHistory = state.chatHistory.slice(-20);
    }

    // 显示加载
    state.isProcessing = true;
    const typingEl = addTypingIndicator();

    // 根据通用设置决定使用流式还是非流式接口
    const useStreaming = loadGeneralSetting('streaming', false);

    if (!useStreaming) {
        // ── 非流式：等待完整答案一次性显示 ────────────────────────
        try {
            const res = await fetch(`${API_BASE}/api/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    question: question,
                    session_id: state.sessionId,
                    chat_history: state.chatHistory,
                    kb_ids: state.selectedKbIds,
                }),
            });
            const data = await res.json();
            typingEl.remove();
            if (!res.ok) throw new Error(data.detail || '请求失败');
            addMessage('assistant', data.answer, data.sources, new Date().toISOString());
            state.chatHistory.push(['assistant', data.answer]);
            state.sessionId = data.session_id || state.sessionId;
        } catch (err) {
            typingEl.remove();
            addMessage('assistant', `请求出错: ${err.message}`);
        } finally {
            state.isProcessing = false;
            toggleSendButton();
        }
        return;
    }

    // ── 流式：逐 token 实时渲染 ────────────────────────────────
    try {
        const res = await fetch(`${API_BASE}/api/chat/stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                question: question,
                session_id: state.sessionId,
                chat_history: state.chatHistory,
                kb_ids: state.selectedKbIds,
            }),
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullAnswer = '';
        let sources = [];
        let sessionId = state.sessionId;
        let contentDiv = null; // 收到第一个 token 后才创建

        while (true) {
            const {
                done,
                value
            } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, {
                stream: true
            });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const jsonStr = line.slice(6).trim();
                if (!jsonStr) continue;

                let event;
                try {
                    event = JSON.parse(jsonStr);
                } catch {
                    continue;
                }

                if (event.token) {
                    // 第一个 token：移除 typing indicator，创建真正的消息气泡
                    if (!contentDiv) {
                        typingEl.remove();
                        contentDiv = addStreamingMessage().contentDiv;
                    }
                    fullAnswer += event.token;
                    contentDiv.innerHTML = renderMarkdown(fullAnswer);
                    scrollToBottom();
                } else if (event.done) {
                    sources = event.sources || [];
                    sessionId = event.session_id || sessionId;
                    // 只有有内容时才覆盖（避免 error 后的 done 清空错误消息）
                    if (contentDiv && fullAnswer) {
                        contentDiv.innerHTML = renderMarkdown(fullAnswer);
                        appendSources(contentDiv, sources);
                    } else if (!contentDiv) {
                        // done 但没有任何 token（暂无内容场景）
                        typingEl.remove();
                        const answer = event.answer || '暂无相关内容';
                        addMessage('assistant', answer, sources);
                        fullAnswer = answer;
                    }
                    scrollToBottom();
                } else if (event.error) {
                    // 立即移除 typing indicator，显示错误，不再等后续事件
                    if (!contentDiv) {
                        typingEl.remove();
                        contentDiv = addStreamingMessage().contentDiv;
                    }
                    contentDiv.innerHTML = `<span style="color:var(--warning)">⚠️ ${event.error}</span>`;
                    scrollToBottom();
                    // 跳出内层 for 循环，break 外层 while
                    reader.cancel();
                    break;
                }
            }
        }

        state.sessionId = sessionId;
        state.chatHistory.push(['assistant', fullAnswer]);

    } catch (err) {
        typingEl.remove();
        addMessage('assistant', `请求出错: ${err.message}`);
    } finally {
        state.isProcessing = false;
        toggleSendButton();
    }
}

function addMessage(role, content, sources = [], createdAt = null) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? t('chat.me') : t('chat.ai');

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    // 用户消息直接显示纯文本（无需 Markdown），AI 回复才渲染 Markdown
    if (role === 'user') {
        contentDiv.textContent = content;
    } else {
        contentDiv.innerHTML = renderMarkdown(content);
    }

    // 引用来源（只有 AI 回复才有）
    if (sources && sources.length > 0) {
        const sourcesDiv = document.createElement('div');
        sourcesDiv.className = 'sources';
        sourcesDiv.innerHTML = `
            <div class="source-title">${t('chat.sources')}</div>
            ${sources.map(s => `
                <div class="source-item">
                    <span>#${s.index}</span>
                    <span>${escapeHtml(s.source)}</span>
                    <span class="source-score">${t('chat.score')}${s.score}</span>
                </div>
            `).join('')}
        `;
        contentDiv.appendChild(sourcesDiv);
    }

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentDiv);

    // 时间戳放在气泡外部，不影响气泡高度
    if (createdAt) {
        const timeEl = document.createElement('div');
        timeEl.className = 'message-time';
        const d = new Date(createdAt);
        const hhmm = d.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit'
        });
        timeEl.textContent = hhmm;
        timeEl.title = createdAt;
        msgDiv.appendChild(timeEl);
    }

    dom.messages.appendChild(msgDiv);

    scrollToBottom();
}

function addTypingIndicator() {
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';
    msgDiv.id = 'typing-indicator';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = t('chat.ai');

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = `
        <div class="typing-indicator">
            <span class="typing-label">${t('chat.typing')}</span>
            <span></span><span></span><span></span>
        </div>
    `;

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentDiv);
    dom.messages.appendChild(msgDiv);

    scrollToBottom();
    return msgDiv;
}

// 创建流式输出的 AI 消息气泡（内容为空，后续逐步填入）
function addStreamingMessage() {
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = t('chat.ai');

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentDiv);
    dom.messages.appendChild(msgDiv);
    scrollToBottom();

    return {
        msgDiv,
        contentDiv
    };
}

// 在消息气泡末尾追加参考来源
function appendSources(contentDiv, sources) {
    if (!sources || sources.length === 0) return;
    const sourcesDiv = document.createElement('div');
    sourcesDiv.className = 'sources';
    sourcesDiv.innerHTML = `
        <div class="source-title">${t('chat.sources')}</div>
        ${sources.map(s => `
            <div class="source-item">
                <span>#${s.index}</span>
                <span>${escapeHtml(s.source)}</span>
                <span class="source-score">${t('chat.score')}${s.score}</span>
            </div>
        `).join('')}
    `;
    contentDiv.appendChild(sourcesDiv);
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        dom.chatContainer.scrollTop = dom.chatContainer.scrollHeight;
    });
}

// ============================================================
// 工具函数
// ============================================================

function toggleSendButton() {
    dom.sendBtn.disabled = !dom.questionInput.value.trim() || state.isProcessing;
}

function autoResizeTextarea(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── 通用设置持久化（localStorage）────────────────────────────
function loadGeneralSetting(key, defaultValue) {
    const raw = localStorage.getItem(`general_${key}`);
    if (raw === null) return defaultValue;
    try {
        return JSON.parse(raw);
    } catch {
        return defaultValue;
    }
}

function saveGeneralSetting(key, value) {
    localStorage.setItem(`general_${key}`, JSON.stringify(value));
}

/**
 * 根据切分方式显示/隐藏分块大小和重叠参数。
 * markdown（标题树）和 semantic（语义）不依赖这两个参数，隐藏以避免干扰。
 * @param {'fixed'|'recursive'|'markdown'|'semantic'} method
 */
function _updateChunkParamVisibility(method) {
    const show = method === 'fixed' || method === 'recursive';
    const sizeField = document.getElementById('chunkSizeField');
    const overlapField = document.getElementById('chunkOverlapField');
    if (sizeField) sizeField.style.display = show ? '' : 'none';
    if (overlapField) overlapField.style.display = show ? '' : 'none';
}

// ── 主题管理 ────────────────────────────────────────────────
/**
 * 应用主题：立即切换 data-theme，持久化到 localStorage
 * @param {'light'|'dark'} theme
 */
function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    saveGeneralSetting('theme', theme);
    // 更新主题选择卡片的 active 状态
    const lightEl = document.getElementById('themeLight');
    const darkEl = document.getElementById('themeDark');
    if (lightEl) lightEl.classList.toggle('active', theme === 'light');
    if (darkEl) darkEl.classList.toggle('active', theme === 'dark');
}

/**
 * 页面初始化时应用已保存的主题（CSS 变量覆盖）
 */
function initTheme() {
    const saved = loadGeneralSetting('theme', 'light');
    document.documentElement.setAttribute('data-theme', saved);
}

/**
 * 切换语言并立即生效
 */
function applyLangChoice(lang) {
    setLang(lang);
    // 更新语言卡片 active 状态
    const zhEl = document.getElementById('langZh');
    const enEl = document.getElementById('langEn');
    if (zhEl) zhEl.classList.toggle('active', lang === 'zh');
    if (enEl) enEl.classList.toggle('active', lang === 'en');
    // 示例问题按钮 data-q 也要跟着语言更新
    const q1 = document.getElementById('exampleQ1');
    const q2 = document.getElementById('exampleQ2');
    const q3 = document.getElementById('exampleQ3');
    if (q1) q1.dataset.q = t('welcome.q1');
    if (q2) q2.dataset.q = t('welcome.q2');
    if (q3) q3.dataset.q = t('welcome.q3');
}

/**
 * 顶栏语言快速切换（中/英一键切换）
 */
function toggleLangQuick() {
    const cur = getCurrentLang();
    applyLangChoice(cur === 'zh' ? 'en' : 'zh');
    _updateLangToggleBtn();
}

function _updateLangToggleBtn() {
    const btn = document.getElementById('langToggleBtn');
    if (!btn) return;
    const cur = getCurrentLang();
    btn.textContent = cur === 'zh' ? 'EN' : '中';
    btn.title = cur === 'zh' ? 'Switch to English' : '切换为中文';
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

/**
 * 简易 Markdown 渲染
 * 支持: 粗体、斜体、代码块、行内代码、列表、换行
 */
function renderMarkdown(text) {
    if (!text) return '';

    let html = escapeHtml(text);

    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 粗体
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // 斜体
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // 标题
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');

    // 无序列表
    html = html.replace(/^\- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');

    // 有序列表
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

    // 换行
    html = html.replace(/\n/g, '<br>');

    // 清理多余的 br
    html = html.replace(/<br><br>/g, '</p><p>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p><\/p>/g, '');

    return html;
}

// ============================================================
// 聊天历史持久化
// ============================================================

/**
 * 页面加载时从后端 SQLite 恢复历史聊天记录。
 * 若有历史消息，隐藏欢迎页并渲染所有消息气泡。
 */
async function loadChatHistory() {
    try {
        const res = await fetch(`${API_BASE}/api/chat-history?limit=200`);
        if (!res.ok) return;
        const data = await res.json();
        const messages = data.messages || [];
        if (messages.length === 0) return;

        // 有历史消息，隐藏欢迎页
        dom.welcomeMessage.style.display = 'none';

        // 渲染所有历史消息
        messages.forEach(msg => {
            addMessage(msg.role, msg.content, msg.sources || [], msg.created_at);
        });

        // 恢复 chatHistory 用于 RAG 上下文（取最近 20 条）
        state.chatHistory = messages.slice(-20).map(m => [m.role, m.content]);

    } catch (e) {
        console.error('恢复聊天历史失败:', e);
    }
}

/**
 * 显示清空聊天记录的确认 Modal。
 * 确认后调用后端 DELETE /api/chat-history，清空数据库和界面。
 */
function showClearChatModal() {
    const modal = document.getElementById('deleteModal');
    document.getElementById('deleteModalBody').textContent = '确定要清空所有聊天记录吗？';
    modal.style.display = 'flex';

    const confirmBtn = document.getElementById('deleteConfirmBtn');
    const cancelBtn = document.getElementById('deleteCancelBtn');

    function close() {
        modal.style.display = 'none';
        confirmBtn.replaceWith(confirmBtn.cloneNode(true));
        cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    }

    document.getElementById('deleteConfirmBtn').addEventListener('click', async () => {
        close();
        try {
            const res = await fetch(`${API_BASE}/api/chat-history`, {
                method: 'DELETE'
            });
            if (!res.ok) throw new Error('请求失败');
            // 清空界面消息列表
            dom.messages.innerHTML = '';
            state.chatHistory = [];
            // 恢复欢迎页：移除 inline style，让 CSS 默认 block 布局生效
            dom.welcomeMessage.style.display = '';
        } catch (e) {
            console.error('清空聊天记录失败:', e);
        }
    });
    document.getElementById('deleteCancelBtn').addEventListener('click', close);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) close();
    }, {
        once: true
    });
}

// 语言切换时更新动态 placeholder
document.addEventListener('langchange', () => {
    _updateLangToggleBtn();
    updateOcrModelStatus();
    renderChatKbSelector(); // 刷新知识库下拉框
    // 强制刷新一次模型状态文字
    _allModelsReady = false;
    pollModelStatus();
    const qi = document.getElementById('questionInput');
    if (qi) qi.placeholder = t('chat.placeholder');
    // 刷新切分方式卡片文字（index.html 里的 radio cards）
    const chunkNames = {
        'fixed': 'chunk.fixed',
        'recursive': 'chunk.recursive',
        'markdown': 'chunk.markdown',
        'semantic': 'chunk.semantic',
    };
    const chunkDescs = {
        'fixed': 'chunk.fixed.desc',
        'recursive': 'chunk.recursive.desc',
        'markdown': 'chunk.markdown.desc',
        'semantic': 'chunk.semantic.desc',
    };
    ['fixed', 'recursive', 'markdown', 'semantic'].forEach(function(v) {
        const card = document.querySelector('input[name="chunkMethod"][value="' + v + '"]');
        if (!card) return;
        const nameEl = card.parentElement.querySelector('.chunk-method-name');
        const descEl = card.parentElement.querySelector('.chunk-method-desc');
        if (nameEl) nameEl.textContent = t(chunkNames[v]);
        if (descEl) descEl.innerHTML = t(chunkDescs[v]).replace(/\n/g, '<br>');
    });
});