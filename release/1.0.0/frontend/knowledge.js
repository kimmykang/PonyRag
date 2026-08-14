/**
 * ponyrag知识库系统 - 知识库管理页面交互逻辑
 * 
 * 作者: kimikang
 * 
 * 功能：
 *   - 知识库列表展示（名称、描述、文档数、向量数、启用状态）
 *   - 创建新知识库
 *   - 编辑知识库信息（名称、描述）
 *   - 启用/禁用知识库
 *   - 删除知识库
 *   - 跳转到文档上传页面（携带 kb_id）
 */

// API 基础地址
const API_BASE = window.location.origin;

// 全局状态
const state = {
    knowledgeBases: [],
    currentEditingKb: null,
    currentDocsKbId: null, // 当前正在管理文档的知识库 ID
    documents: [], // 当前知识库的文档列表
    selectedDocs: new Set(), // 选中的文档名集合
};

// DOM 元素引用
const dom = {
    sidebar: document.getElementById('sidebar'),
    sidebarToggle: document.getElementById('sidebarToggle'),
    menuBtn: document.getElementById('menuBtn'),
    connectionStatus: document.getElementById('connectionStatus'),
    kbCount: document.getElementById('kbCount'),
    enabledCount: document.getElementById('enabledCount'),
    dbCount: document.getElementById('dbCount'),
    fileCount: document.getElementById('fileCount'),
    kbGrid: document.getElementById('kbGrid'),
    createKbBtn: document.getElementById('createKbBtn'),

    // Modal
    kbModal: document.getElementById('kbModal'),
    kbModalTitle: document.getElementById('kbModalTitle'),
    kbNameInput: document.getElementById('kbNameInput'),
    kbDescInput: document.getElementById('kbDescInput'),
    kbModalHint: document.getElementById('kbModalHint'),
    kbSaveBtn: document.getElementById('kbSaveBtn'),
    kbCancelBtn: document.getElementById('kbCancelBtn'),

    // 删除确认 Modal
    deleteKbModal: document.getElementById('deleteKbModal'),
    deleteKbModalBody: document.getElementById('deleteKbModalBody'),
    deleteKbConfirmBtn: document.getElementById('deleteKbConfirmBtn'),
    deleteKbCancelBtn: document.getElementById('deleteKbCancelBtn'),
};

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    checkConnection();
    loadKnowledgeBases();
});

function initEventListeners() {
    // 侧边栏切换
    dom.menuBtn.addEventListener('click', toggleSidebar);
    dom.sidebarToggle.addEventListener('click', toggleSidebar);

    // 创建知识库按钮
    dom.createKbBtn.addEventListener('click', openCreateKbModal);

    // Modal 事件
    dom.kbCancelBtn.addEventListener('click', closeKbModal);
    dom.kbSaveBtn.addEventListener('click', saveKnowledgeBase);
    dom.kbModal.addEventListener('click', (e) => {
        if (e.target === dom.kbModal) closeKbModal();
    });

    // 删除 Modal 事件
    dom.deleteKbCancelBtn.addEventListener('click', closeDeleteKbModal);

    // 文档管理 Modal 事件
    document.getElementById('docsCloseBtn').addEventListener('click', closeDocsModal);

    const docsModalCloseBtn = document.getElementById('docsModalCloseBtn');
    if (docsModalCloseBtn) {
        docsModalCloseBtn.addEventListener('click', closeDocsModal);
    }

    document.getElementById('docsUploadBtn').addEventListener('click', () => {
        document.getElementById('docsFileInput').click();
    });
    document.getElementById('docsFileInput').addEventListener('change', handleDocsUpload);
    document.getElementById('docsBatchDeleteBtn').addEventListener('click', handleBatchDelete);
    document.getElementById('docsModal').addEventListener('click', (e) => {
        if (e.target.id === 'docsModal') closeDocsModal();
    });
}

function toggleSidebar() {
    const sidebar = dom.sidebar;
    const isMobile = window.innerWidth <= 768;

    if (isMobile) {
        sidebar.classList.toggle('open');
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

// 连接检测
async function checkConnection() {
    try {
        const res = await fetch(`${API_BASE}/api/health`);
        const data = await res.json();
        updateConnectionStatus(data.status === 'ok');
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
        text.textContent = '已连接';
    } else {
        dot.className = 'status-dot disconnected';
        text.textContent = '连接失败';
    }
}

// 加载知识库列表
async function loadKnowledgeBases() {
    try {
        const res = await fetch(`${API_BASE}/api/knowledge-bases`);
        const data = await res.json();
        state.knowledgeBases = data.knowledge_bases || [];
        renderKnowledgeBases();
        updateStats();
    } catch (e) {
        console.error('加载知识库列表失败:', e);
        dom.kbGrid.innerHTML = '<div class="empty-state">加载失败，请刷新页面</div>';
    }
}

function renderKnowledgeBases() {
    const grid = dom.kbGrid;

    if (state.knowledgeBases.length === 0) {
        grid.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 64 64" width="64" height="64" fill="none">
                    <circle cx="32" cy="32" r="30" fill="#6366f1" opacity="0.1" />
                    <path d="M20 28h24M20 36h24M20 44h16" stroke="#6366f1" stroke-width="2" stroke-linecap="round"/>
                </svg>
                <p>暂无知识库</p>
                <p style="font-size: 0.9rem; color: var(--text-secondary);">点击「创建知识库」按钮开始</p>
            </div>
        `;
        return;
    }

    grid.innerHTML = state.knowledgeBases.map(kb => `
        <div class="kb-card ${kb.enabled ? '' : 'kb-disabled'}">
            <div class="kb-card-header">
                <h3 class="kb-card-title">${escapeHtml(kb.name)}</h3>
                <div class="kb-card-actions">
                    ${kb.kb_id === 'knowledge_base' ? '' : `
                        <button class="icon-btn" onclick="toggleKbEnabled('${kb.kb_id}', ${kb.enabled})" title="${kb.enabled ? '禁用' : '启用'}">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                                ${kb.enabled 
                                    ? '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>'
                                    : '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line>'
                                }
                            </svg>
                        </button>
                        <button class="icon-btn" onclick="openEditKbModal('${kb.kb_id}')" title="编辑">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                            </svg>
                        </button>
                        <button class="icon-btn" onclick="openDeleteKbModal('${kb.kb_id}')" title="删除">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
                            </svg>
                        </button>
                    `}
                </div>
            </div>
            
            ${kb.description ? `<p class="kb-card-desc">${escapeHtml(kb.description)}</p>` : ''}
            
            <div class="kb-card-stats">
                <div class="kb-stat-item">
                    <span class="kb-stat-label">文档</span>
                    <span class="kb-stat-value">${kb.document_count || 0}</span>
                </div>
                <div class="kb-stat-item">
                    <span class="kb-stat-label">向量</span>
                    <span class="kb-stat-value">${kb.vector_count || 0}</span>
                </div>
                <div class="kb-stat-item">
                    <span class="kb-stat-label">状态</span>
                    <span class="kb-stat-badge ${kb.enabled ? 'enabled' : 'disabled'}">
                        ${kb.enabled ? '已启用' : '已禁用'}
                    </span>
                </div>
            </div>
            
            <div class="kb-card-footer">
                <button class="btn btn-secondary btn-sm" onclick="goToChat('${kb.kb_id}')">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                    对话
                </button>
                <button class="btn btn-primary btn-sm" onclick="manageDocuments('${kb.kb_id}')">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                    </svg>
                    管理文档
                </button>
            </div>
        </div>
    `).join('');
}

async function updateStats() {
    // 更新知识库数量和启用状态
    dom.kbCount.textContent = state.knowledgeBases.length;
    const enabledCount = state.knowledgeBases.filter(kb => kb.enabled).length;
    dom.enabledCount.textContent = `${enabledCount} / ${state.knowledgeBases.length}`;

    // 加载向量库和文件总数统计
    try {
        const res = await fetch(`${API_BASE}/api/stats?kb_id=all`);
        if (!res.ok) {
            console.error('[updateStats] 加载总统计失败:', res.status);
            dom.dbCount.textContent = '-';
            dom.fileCount.textContent = '-';
            return;
        }
        const data = await res.json();
        dom.dbCount.textContent = data.vector_documents || 0;
        dom.fileCount.textContent = data.uploaded_files || 0;
    } catch (e) {
        console.error('[updateStats] 加载总统计异常:', e);
        dom.dbCount.textContent = '-';
        dom.fileCount.textContent = '-';
    }
}

// 创建知识库 Modal
function openCreateKbModal() {
    state.currentEditingKb = null;
    dom.kbModalTitle.textContent = '创建知识库';
    dom.kbNameInput.value = '';
    dom.kbDescInput.value = '';
    dom.kbModalHint.textContent = '';
    dom.kbModal.style.display = 'flex';
    setTimeout(() => dom.kbNameInput.focus(), 100);
}

// 编辑知识库 Modal
function openEditKbModal(kbId) {
    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    if (!kb) return;

    state.currentEditingKb = kb;
    dom.kbModalTitle.textContent = '编辑知识库';
    dom.kbNameInput.value = kb.name;
    dom.kbDescInput.value = kb.description || '';
    dom.kbModalHint.textContent = '';
    dom.kbModal.style.display = 'flex';
    setTimeout(() => dom.kbNameInput.focus(), 100);
}

function closeKbModal() {
    dom.kbModal.style.display = 'none';
    state.currentEditingKb = null;
}

// 保存知识库
async function saveKnowledgeBase() {
    const name = dom.kbNameInput.value.trim();
    const description = dom.kbDescInput.value.trim();

    if (!name) {
        dom.kbModalHint.textContent = '请输入知识库名称';
        dom.kbModalHint.style.color = 'var(--danger)';
        return;
    }

    dom.kbModalHint.textContent = '保存中...';
    dom.kbModalHint.style.color = 'var(--text-secondary)';
    dom.kbSaveBtn.disabled = true;

    try {
        let res, data;

        if (state.currentEditingKb) {
            // 编辑现有知识库
            res = await fetch(`${API_BASE}/api/knowledge-bases/${state.currentEditingKb.kb_id}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name,
                    description
                }),
            });
        } else {
            // 创建新知识库
            res = await fetch(`${API_BASE}/api/knowledge-bases`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name,
                    description
                }),
            });
        }

        data = await res.json();

        if (res.ok && data.status === 'success') {
            closeKbModal();
            await loadKnowledgeBases();
        } else {
            dom.kbModalHint.textContent = data.detail || data.message || '保存失败';
            dom.kbModalHint.style.color = 'var(--danger)';
        }
    } catch (e) {
        dom.kbModalHint.textContent = '网络错误: ' + e.message;
        dom.kbModalHint.style.color = 'var(--danger)';
    } finally {
        dom.kbSaveBtn.disabled = false;
    }
}

// 切换启用/禁用状态
async function toggleKbEnabled(kbId, currentEnabled) {
    try {
        const res = await fetch(`${API_BASE}/api/knowledge-bases/${kbId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                enabled: currentEnabled ? 0 : 1
            }),
        });

        const data = await res.json();

        if (res.ok && data.status === 'success') {
            await loadKnowledgeBases();
        } else {
            alert('操作失败: ' + (data.detail || data.message));
        }
    } catch (e) {
        alert('网络错误: ' + e.message);
    }
}

// 删除知识库
function openDeleteKbModal(kbId) {
    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    if (!kb) return;

    dom.deleteKbModalBody.textContent = `确定要删除知识库「${kb.name}」吗？`;
    dom.deleteKbModal.style.display = 'flex';

    // 移除旧的事件监听器，绑定新的
    const newConfirmBtn = dom.deleteKbConfirmBtn.cloneNode(true);
    dom.deleteKbConfirmBtn.replaceWith(newConfirmBtn);
    dom.deleteKbConfirmBtn = newConfirmBtn; // 更新 DOM 引用！

    newConfirmBtn.addEventListener('click', async () => {
        closeDeleteKbModal();
        await deleteKnowledgeBase(kbId);
    });
}

function closeDeleteKbModal() {
    dom.deleteKbModal.style.display = 'none';
}

async function deleteKnowledgeBase(kbId) {
    try {
        const res = await fetch(`${API_BASE}/api/knowledge-bases/${kbId}`, {
            method: 'DELETE',
        });

        const data = await res.json();

        if (res.ok && data.status === 'success') {
            await loadKnowledgeBases();
        } else {
            alert('删除失败: ' + (data.detail || data.message));
        }
    } catch (e) {
        alert('网络错误: ' + e.message);
    }
}

// 跳转到聊天页面（带知识库上下文）
function goToChat(kbId) {
    localStorage.setItem('current_kb_id', kbId);
    window.location.href = '/';
}

// 管理文档（打开文档管理 Modal）
function manageDocuments(kbId) {
    console.log('manageDocuments 被调用, kbId:', kbId);
    openDocsModal(kbId);
}

// ========================================
// 文档管理 Modal
// ========================================

// 打开文档管理 Modal
async function openDocsModal(kbId) {
    console.log('openDocsModal 被调用, kbId:', kbId);

    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    console.log('找到的知识库:', kb);

    if (!kb) {
        console.error('知识库不存在:', kbId);
        return;
    }

    state.currentDocsKbId = kbId;
    state.selectedDocs.clear();

    // 设置标题
    const titleEl = document.getElementById('docsModalTitle');
    console.log('标题元素:', titleEl);
    if (titleEl) {
        titleEl.textContent = `文档管理 - ${kb.name}`;
    }

    // 显示 Modal
    const modalEl = document.getElementById('docsModal');
    console.log('Modal 元素:', modalEl);

    if (modalEl) {
        modalEl.style.display = 'flex';
        console.log('Modal display 已设置为 flex');
    } else {
        console.error('找不到 docsModal 元素！');
    }

    // 加载文档列表
    await loadDocuments(kbId);
}

// 关闭文档管理 Modal
function closeDocsModal() {
    document.getElementById('docsModal').style.display = 'none';
    state.currentDocsKbId = null;
    state.documents = [];
    state.selectedDocs.clear();

    // 重新加载知识库列表（更新文档数量）
    loadKnowledgeBases();
}

// 加载文档列表
async function loadDocuments(kbId) {
    const docsList = document.getElementById('docsList');
    docsList.innerHTML = '<div class="empty-state">加载中...</div>';

    try {
        console.log('开始加载文档，kb_id:', kbId);
        const res = await fetch(`${API_BASE}/api/documents?kb_id=${encodeURIComponent(kbId)}`);
        console.log('API 响应状态:', res.status);

        const data = await res.json();
        console.log('API 返回数据:', data);

        if (!res.ok) {
            throw new Error(data.detail || '加载失败');
        }

        // 后端返回的字段是 filename, created，需要转换为 name, upload_time
        state.documents = (data.documents || []).map(doc => ({
            name: doc.filename || doc.name,
            upload_time: doc.upload_time || (doc.created ? new Date(doc.created * 1000).toLocaleString('zh-CN') : '未知'),
            size: doc.size,
            md_ready: doc.md_ready
        }));

        console.log('成功加载文档数量:', state.documents.length);
        console.log('转换后的文档数据:', state.documents[0]);

        renderDocuments();
    } catch (e) {
        console.error('加载文档列表失败:', e);
        docsList.innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
    }
}

// 渲染文档列表（简单表格）
function renderDocuments() {
    const docsList = document.getElementById('docsList');

    if (state.documents.length === 0) {
        docsList.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 64 64" width="48" height="48" fill="none">
                    <circle cx="32" cy="32" r="30" fill="#6366f1" opacity="0.1" />
                    <path d="M24 20h16M24 28h16M24 36h10" stroke="#6366f1" stroke-width="2" stroke-linecap="round"/>
                </svg>
                <p style="margin-top: 8px;">暂无文档</p>
                <p style="font-size: 0.85rem; color: var(--text-secondary);">点击「上传文档」按钮添加</p>
            </div>
        `;
        updateBatchDeleteBtn();
        return;
    }

    // 表格HTML
    let tableHTML = `
        <table class="docs-table">
            <thead>
                <tr>
                    <th style="width: 50px; text-align: center;">
                        <input type="checkbox" id="selectAllDocs" onchange="window.toggleSelectAll()">
                    </th>
                    <th style="width: 60px;"></th>
                    <th>文件名</th>
                    <th style="width: 220px;">上传时间</th>
                    <th style="width: 80px; text-align: center;">操作</th>
                </tr>
            </thead>
            <tbody>`;

    state.documents.forEach(doc => {
        if (!doc || !doc.name) return;

        const isSelected = state.selectedDocs.has(doc.name);
        const fileExt = doc.name.split('.').pop().toLowerCase();
        const fileIcon = getFileIcon(fileExt);
        // 转义HTML字符
        const safeName = doc.name.replace(/[&<>"']/g, char => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        } [char]));

        tableHTML += `
            <tr class="doc-table-row ${isSelected ? 'selected' : ''}">
                <td style="text-align: center;">
                    <input type="checkbox" class="doc-checkbox" ${isSelected ? 'checked' : ''} 
                           onchange="window.toggleDocSelection('${safeName}')">
                </td>
                <td style="text-align: center; font-size: 24px;">
                    ${fileIcon}
                </td>
                <td class="doc-name-cell" title="${safeName}">
                    ${safeName}
                </td>
                <td class="doc-time-cell">
                    ${doc.upload_time || '未知'}
                </td>
                <td style="text-align: center;">
                    <button class="icon-btn doc-delete-btn" onclick="window.deleteSingleDocument('${safeName}')" title="删除">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
                            <path d="M10 11v6M14 11v6"></path>
                        </svg>
                    </button>
                </td>
            </tr>`;
    });

    tableHTML += `
            </tbody>
        </table>`;

    docsList.innerHTML = tableHTML;
    updateBatchDeleteBtn();
    updateSelectAllCheckbox();
}

// 获取文件图标
function getFileIcon(ext) {
    const iconMap = {
        'pdf': '📄',
        'doc': '📝',
        'docx': '📝',
        'txt': '📃',
        'md': '📋',
        'xls': '📊',
        'xlsx': '📊',
        'ppt': '📑',
        'pptx': '📑',
    };
    return iconMap[ext] || '📄';
}

// 切换文档选中状态
function toggleDocSelection(filename) {
    if (state.selectedDocs.has(filename)) {
        state.selectedDocs.delete(filename);
    } else {
        state.selectedDocs.add(filename);
    }
    renderDocuments();
}

// 全选/取消全选
function toggleSelectAll() {
    const selectAllCheckbox = document.getElementById('selectAllDocs');
    if (selectAllCheckbox && selectAllCheckbox.checked) {
        state.documents.forEach(doc => {
            if (doc && doc.name) {
                state.selectedDocs.add(doc.name);
            }
        });
    } else {
        state.selectedDocs.clear();
    }
    renderDocuments();
}

// 更新全选复选框状态
function updateSelectAllCheckbox() {
    const selectAllCheckbox = document.getElementById('selectAllDocs');
    if (!selectAllCheckbox) return;

    const totalDocs = state.documents.filter(doc => doc && doc.name).length;
    const selectedCount = state.selectedDocs.size;

    if (selectedCount === 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
    } else if (selectedCount === totalDocs) {
        selectAllCheckbox.checked = true;
        selectAllCheckbox.indeterminate = false;
    } else {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = true;
    }
}

// 更新批量删除按钮状态
function updateBatchDeleteBtn() {
    const btn = document.getElementById('docsBatchDeleteBtn');
    const text = document.getElementById('docsBatchDeleteText');
    if (!btn || !text) return;

    const count = state.selectedDocs.size;
    btn.disabled = count === 0;
    text.textContent = count > 0 ? `批量删除 (${count})` : '批量删除';
}

// 处理文档上传
async function handleDocsUpload(event) {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    const kbId = state.currentDocsKbId;
    if (!kbId) return;

    const uploadProgress = document.getElementById('docsUploadProgress');
    const progressFill = document.getElementById('docsProgressFill');
    const progressText = document.getElementById('docsProgressText');

    uploadProgress.style.display = 'block';

    try {
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            const formData = new FormData();
            formData.append('file', file);

            progressText.textContent = `上传中... (${i + 1}/${files.length}) ${file.name}`;
            progressFill.style.width = `${((i) / files.length) * 100}%`;

            const res = await fetch(`${API_BASE}/api/upload?kb_id=${encodeURIComponent(kbId)}`, {
                method: 'POST',
                body: formData,
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(`上传 ${file.name} 失败: ${data.detail || data.message}`);
            }

            progressFill.style.width = `${((i + 1) / files.length) * 100}%`;
        }

        progressText.textContent = '上传完成！';

        await loadDocuments(kbId);
        await updateStats(); // 刷新统计数据

        setTimeout(() => {
            uploadProgress.style.display = 'none';
            progressFill.style.width = '0%';
        }, 2000);

    } catch (e) {
        console.error('上传失败:', e);
        progressText.textContent = `上传失败: ${e.message}`;
        progressText.style.color = 'var(--danger)';

        setTimeout(() => {
            uploadProgress.style.display = 'none';
            progressFill.style.width = '0%';
            progressText.style.color = '';
        }, 3000);
    } finally {
        event.target.value = '';
    }
}

// 批量删除文档
async function handleBatchDelete() {
    if (state.selectedDocs.size === 0) return;

    const kbId = state.currentDocsKbId;
    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    if (!kb) return;

    const count = state.selectedDocs.size;
    const fileList = Array.from(state.selectedDocs).map(name => `  • ${name}`).join('\n');

    if (!confirm(`确定要删除知识库「${kb.name}」中的 ${count} 个文档吗？\n\n${fileList}\n\n此操作不可恢复。`)) {
        return;
    }

    const btn = document.getElementById('docsBatchDeleteBtn');
    const text = document.getElementById('docsBatchDeleteText');
    const originalText = text.textContent;

    btn.disabled = true;
    text.textContent = '删除中...';

    try {
        const deletePromises = Array.from(state.selectedDocs).map(filename =>
            fetch(`${API_BASE}/api/documents/${encodeURIComponent(filename)}?kb_id=${encodeURIComponent(kbId)}`, {
                method: 'DELETE',
            })
        );

        const results = await Promise.all(deletePromises);

        const failures = results.filter(res => !res.ok);
        if (failures.length > 0) {
            throw new Error(`${failures.length} 个文档删除失败`);
        }

        state.selectedDocs.clear();
        await loadDocuments(kbId);
        await updateStats(); // 刷新统计数据

        text.textContent = '删除成功！';
        setTimeout(() => {
            text.textContent = originalText;
            btn.disabled = false;
        }, 2000);

    } catch (e) {
        console.error('批量删除失败:', e);
        alert(`批量删除失败: ${e.message}`);
        text.textContent = originalText;
        btn.disabled = false;
    }
}

// 单个删除文档
async function deleteSingleDocument(filename) {
    const kbId = state.currentDocsKbId;
    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    if (!kb) return;

    if (!confirm(`确定要删除文档「${filename}」吗？\n\n此操作不可恢复。`)) {
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/documents/${encodeURIComponent(filename)}?kb_id=${encodeURIComponent(kbId)}`, {
            method: 'DELETE',
        });

        const data = await res.json();

        if (!res.ok) {
            throw new Error(data.detail || data.message || '删除失败');
        }

        console.log(`文档 ${filename} 删除成功，移除了 ${data.vectors_removed} 个向量`);
        await loadDocuments(kbId);
        await updateStats(); // 刷新统计数据

    } catch (e) {
        console.error('删除文档失败:', e);
        alert(`删除失败: ${e.message}`);
    }
}

// 工具函数
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// 暴露到全局作用域供 HTML onclick 使用
window.openEditKbModal = openEditKbModal;
window.openDeleteKbModal = openDeleteKbModal;
window.toggleKbEnabled = toggleKbEnabled;
window.goToChat = goToChat;
window.manageDocuments = manageDocuments;
window.toggleDocSelection = toggleDocSelection;
window.toggleSelectAll = toggleSelectAll;
window.deleteSingleDocument = deleteSingleDocument;

// 测试函数：直接打开弹窗
window.testModalOpen = function() {
    console.log('🧪 测试按钮被点击');
    console.log('🧪 当前知识库数量:', state.knowledgeBases.length);

    if (state.knowledgeBases.length > 0) {
        const testKb = state.knowledgeBases[0];
        console.log('🧪 使用第一个知识库进行测试:', testKb.kb_id, testKb.name);
        manageDocuments(testKb.kb_id);
    } else {
        alert('请先创建一个知识库');
    }
};