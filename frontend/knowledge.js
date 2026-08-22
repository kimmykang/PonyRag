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
    refreshChunkMethodSelects();
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
    document.getElementById('docsFolderBtn').addEventListener('click', () => {
        document.getElementById('docsFolderInput').click();
    });
    document.getElementById('docsFolderInput').addEventListener('change', handleDocsUpload);
    document.getElementById('docsBatchDeleteBtn').addEventListener('click', handleBatchDelete);
    document.getElementById('docsModal').addEventListener('click', (e) => {
        if (e.target.id === 'docsModal') closeDocsModal();
    });

    // 切分参数面板：切分方式切换时动态显隐大小/重叠输入框，更新徽章
    const uploadMethodSel = document.getElementById('uploadChunkMethod');
    if (uploadMethodSel) {
        uploadMethodSel.addEventListener('change', _updateUploadChunkPanel);
    }
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
        text.textContent = t('app.connected');
    } else {
        dot.className = 'status-dot disconnected';
        text.textContent = t('app.disconnected');
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
                <p>${t('kb.empty')}</p>
                <p style="font-size: 0.9rem; color: var(--text-secondary);">${t('kb.emptyHint')}</p>
            </div>
        `;
        return;
    }

    grid.innerHTML = state.knowledgeBases.map(kb => {
        // 默认知识库名称国际化
        const displayName = kb.kb_id === 'knowledge_base' ?
            t('kb.defaultName') :
            escapeHtml(kb.name);
        const displayDesc = kb.kb_id === 'knowledge_base' ?
            t('kb.defaultDesc') :
            (kb.description ? escapeHtml(kb.description) : '');
        return `
        <div class="kb-card ${kb.enabled ? '' : 'kb-disabled'}">
            <div class="kb-card-header">
                <h3 class="kb-card-title">${displayName}</h3>
                <div class="kb-card-actions">
                    ${kb.kb_id === 'knowledge_base' ? '' : `
                        <button class="icon-btn" onclick="toggleKbEnabled('${kb.kb_id}', ${kb.enabled})" title="${kb.enabled ? t('kb.disable') : t('kb.enable')}">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                                ${kb.enabled 
                                    ? '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>'
                                    : '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line>'
                                }
                            </svg>
                        </button>
                        <button class="icon-btn" onclick="openEditKbModal('${kb.kb_id}')" title="${t('kb.edit')}">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                            </svg>
                        </button>
                        <button class="icon-btn" onclick="openDeleteKbModal('${kb.kb_id}')" title="${t('kb.deleteKb')}">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
                            </svg>
                        </button>
                    `}
                </div>
            </div>
            
            ${displayDesc ? `<p class="kb-card-desc">${displayDesc}</p>` : ''}
            
            <div class="kb-card-stats">
                <div class="kb-stat-item">
                    <span class="kb-stat-label">${t('kb.docs')}</span>
                    <span class="kb-stat-value">${kb.document_count || 0}</span>
                </div>
                <div class="kb-stat-item">
                    <span class="kb-stat-label">${t('kb.vectors')}</span>
                    <span class="kb-stat-value">${kb.vector_count || 0}</span>
                </div>
                <div class="kb-stat-item">
                    <span class="kb-stat-label">${t('kb.status')}</span>
                    <span class="kb-stat-badge ${kb.enabled ? 'enabled' : 'disabled'}">
                        ${kb.enabled ? t('kb.enabled') : t('kb.disabled')}
                    </span>
                </div>
            </div>
            
            <div class="kb-card-footer">
                <button class="btn btn-secondary btn-sm" onclick="goToChat('${kb.kb_id}')">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                    ${t('kb.chat')}
                </button>
                <button class="btn btn-primary btn-sm" onclick="manageDocuments('${kb.kb_id}')">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                    </svg>
                    ${t('kb.manage')}
                </button>
            </div>
        </div>
    `;
    }).join('');
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
    dom.kbModalTitle.textContent = t('kb.modal.create');
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
    dom.kbModalTitle.textContent = t('kb.modal.edit');
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

    dom.kbModalHint.textContent = t('kb.saving');
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
        titleEl.textContent = `${t('docs.title')} - ${kb.name}`;
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
        const [res, recRes] = await Promise.all([
            fetch(`${API_BASE}/api/documents?kb_id=${encodeURIComponent(kbId)}`),
            fetch(`${API_BASE}/api/documents/chunk-records?kb_id=${encodeURIComponent(kbId)}`),
        ]);

        const data = await res.json();
        const recData = recRes.ok ? await recRes.json() : {
            records: []
        };

        if (!res.ok) throw new Error(data.detail || '加载失败');

        // 构建切分记录 map：filename → record
        const chunkRecMap = {};
        (recData.records || []).forEach(r => {
            chunkRecMap[r.filename] = r;
        });

        state.documents = (data.documents || []).map(doc => {
            const mdName = (doc.filename || doc.name).replace(/\.[^.]+$/, '.md');
            const rec = chunkRecMap[mdName] || null;
            return {
                name: doc.filename || doc.name,
                upload_time: doc.upload_time || (doc.created ? new Date(doc.created * 1000).toLocaleString('zh-CN') : '未知'),
                size: doc.size,
                md_ready: doc.md_ready,
                chunk_method: rec ? rec.chunk_method : null,
                chunk_size: rec ? rec.chunk_size : null,
                chunk_count: rec ? rec.chunk_count : null,
                up_to_date: rec ? rec.up_to_date : null,
            };
        });

        console.log('成功加载文档数量:', state.documents.length);
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
    const METHOD_LABEL = {
        'fixed': `✂️ ${t('chunk.fixed.short')}`,
        'recursive': `🔀 ${t('chunk.recursive.short')}`,
        'markdown': `📑 ${t('chunk.markdown.short')}`,
        'semantic': `🧠 ${t('chunk.semantic.short')}`,
    };

    let tableHTML = `
        <table class="docs-table">
            <thead>
                <tr>
                    <th style="width: 50px; text-align: center;">
                        <input type="checkbox" id="selectAllDocs" onchange="window.toggleSelectAll()">
                    </th>
                    <th style="width: 60px;"></th>
                    <th>${t('docs.colName')}</th>
                    <th style="width: 130px;">${t('docs.colChunk')}</th>
                    <th style="width: 180px;">${t('docs.colTime')}</th>
                    <th style="width: 80px; text-align: center;">${t('docs.colAction')}</th>
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
                    <a href="${API_BASE}/api/document/download?filename=${encodeURIComponent(safeName)}&kb_id=${encodeURIComponent(state.currentDocsKbId || 'knowledge_base')}"
                       target="_blank"
                       style="color: inherit; text-decoration: none;"
                       onmouseover="this.style.textDecoration='underline'"
                       onmouseout="this.style.textDecoration='none'">
                        ${safeName}
                    </a>
                </td>
                <td class="doc-chunk-cell">
                    ${doc.chunk_method
                        ? `<span class="chunk-method-tag ${doc.up_to_date === false ? 'stale' : ''} chunk-tag-clickable"
                               title="${t('docs.rechunk')}"
                               onclick="window.openRechunkPanel('${safeName}', '${doc.chunk_method}', ${doc.chunk_size}, ${doc.chunk_overlap})">
                               ${METHOD_LABEL[doc.chunk_method] || doc.chunk_method}
                               <span class="chunk-count">${doc.chunk_count}${t('chunk.fixed.short') !== 'Fixed' ? '块' : ''}</span>
                               ✏️
                           </span>`
                        : `<span class="chunk-method-tag none chunk-tag-clickable"
                               title="${t('docs.rechunk')}"
                               onclick="window.openRechunkPanel('${safeName}', 'recursive', 500, 50)">
                               ${t('docs.legacy')} ✏️
                           </span>`
                    }
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
    text.textContent = count > 0 ? `${t('docs.batchDelete')} (${count})` : t('docs.batchDelete');
}

// 支持的文件扩展名
const ALLOWED_EXTS = new Set(['.pdf', '.docx', '.doc', '.txt', '.md', '.xlsx', '.xls', '.pptx', '.ppt']);

// 处理文档上传（文件选择 或 目录选择 共用）
async function handleDocsUpload(event) {
    const allFiles = Array.from(event.target.files || []);
    if (allFiles.length === 0) return;

    const kbId = state.currentDocsKbId;
    if (!kbId) return;

    // 过滤出支持的文件类型（目录选择时可能包含图片/隐藏文件等）
    const skippedFiles = []; // { name, reason }
    const files = allFiles.filter(f => {
        const ext = '.' + f.name.split('.').pop().toLowerCase();
        const relPath = f.webkitRelativePath || '';
        const displayName = relPath || f.name;
        // 过滤隐藏文件（文件名以 . 开头）
        if (f.name.startsWith('.')) return false;
        // 过滤 Office 临时锁定文件（~$ 开头）
        if (f.name.startsWith('~$')) return false;
        // 过滤隐藏目录下的文件（路径含以 . 开头的目录段，如 .git/）
        if (relPath && relPath.split('/').some(seg => seg.startsWith('.'))) return false;
        // 过滤不支持的扩展名，并记录文件名
        if (!ALLOWED_EXTS.has(ext)) {
            skippedFiles.push({
                name: displayName,
                reason: `不支持的格式 (${ext || '无扩展名'})`
            });
            return false;
        }
        return true;
    });

    if (files.length === 0) {
        showUploadResult(0, 0, [], skippedFiles);
        event.target.value = '';
        return;
    }

    const uploadProgress = document.getElementById('docsUploadProgress');
    const progressFill = document.getElementById('docsProgressFill');
    const progressText = document.getElementById('docsProgressText');

    uploadProgress.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.style.color = '';

    const failed = []; // { name, reason }
    let succeeded = 0;

    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const pct = Math.round((i / files.length) * 100);
        progressFill.style.width = `${pct}%`;
        progressText.textContent = `(${i + 1}/${files.length}) ${file.name}`;

        try {
            const formData = new FormData();
            formData.append('file', file);

            // 读取上传时指定的切分参数（空则使用全局配置）
            const uploadMethodEl = document.getElementById('uploadChunkMethod');
            const uploadSizeEl = document.getElementById('uploadChunkSize');
            const uploadOverlapEl = document.getElementById('uploadChunkOverlap');
            const chunkMethod = uploadMethodEl ? uploadMethodEl.value : '';
            const chunkSize = uploadSizeEl ? uploadSizeEl.value : '';
            const chunkOverlap = uploadOverlapEl ? uploadOverlapEl.value : '';

            let uploadUrl = `${API_BASE}/api/upload?kb_id=${encodeURIComponent(kbId)}`;
            if (chunkMethod) uploadUrl += `&chunk_method=${encodeURIComponent(chunkMethod)}`;
            if (chunkSize) uploadUrl += `&chunk_size=${encodeURIComponent(chunkSize)}`;
            if (chunkOverlap) uploadUrl += `&chunk_overlap=${encodeURIComponent(chunkOverlap)}`;

            const res = await fetch(uploadUrl, {
                method: 'POST',
                body: formData,
            });

            const data = await res.json();

            if (!res.ok) {
                failed.push({
                    name: file.name,
                    reason: data.detail || data.message || `HTTP ${res.status}`
                });
            } else {
                succeeded++;
            }
        } catch (e) {
            failed.push({
                name: file.name,
                reason: '网络错误: ' + e.message
            });
        }
    }

    progressFill.style.width = '100%';
    progressText.textContent = failed.length === 0 ?
        `上传完成！共 ${succeeded} 个文件` :
        `完成：${succeeded} 成功，${failed.length} 失败`;

    if (failed.length > 0) {
        progressText.style.color = 'var(--warning, #f59e0b)';
    }

    await loadDocuments(kbId);
    await updateStats();

    setTimeout(() => {
        uploadProgress.style.display = 'none';
        progressFill.style.width = '0%';
        progressText.style.color = '';
        // 有失败或有被类型过滤的文件时弹出结果弹窗
        if (failed.length > 0 || skippedFiles.length > 0) {
            showUploadResult(succeeded, files.length, failed, skippedFiles);
        }
    }, 1500);

    event.target.value = '';
}

// 显示上传结果弹窗
function showUploadResult(succeeded, total, failed, skippedFiles) {
    const modal = document.getElementById('uploadResultModal');
    const title = document.getElementById('uploadResultTitle');
    const summary = document.getElementById('uploadResultSummary');
    const failedList = document.getElementById('uploadFailedList');
    const failedItems = document.getElementById('uploadFailedItems');

    if (failed.length === 0 && skippedFiles.length === 0) return;

    const hasIssues = failed.length > 0 || skippedFiles.length > 0;
    title.textContent = failed.length > 0 ? '上传完成（部分失败）' : '上传完成';

    // 摘要行
    let summaryParts = [];
    if (total > 0) summaryParts.push(`✅ 成功 ${succeeded} 个`);
    if (failed.length > 0) summaryParts.push(`❌ 失败 ${failed.length} 个`);
    if (skippedFiles.length > 0) summaryParts.push(`⏭️ 跳过 ${skippedFiles.length} 个`);
    summary.textContent = summaryParts.join('，');

    // 合并失败列表和跳过列表
    const allIssues = [
        ...failed.map(f => ({
            ...f,
            type: 'failed'
        })),
        ...skippedFiles.map(f => ({
            ...f,
            type: 'skipped'
        })),
    ];

    if (allIssues.length > 0) {
        failedItems.innerHTML = allIssues.map(f => `
            <div style="padding: 6px 0; border-bottom: 1px solid var(--border-color, #eee); display:flex; gap:8px; align-items:flex-start;">
                <span style="flex-shrink:0; font-size:0.9rem;">${f.type === 'failed' ? '❌' : '⏭️'}</span>
                <div style="min-width:0;">
                    <div style="font-weight:500; word-break:break-all; font-size:0.875rem;">${escapeHtml(f.name)}</div>
                    <div style="color: var(--text-secondary); font-size:0.8rem;">${escapeHtml(f.reason)}</div>
                </div>
            </div>
        `).join('');
        failedList.style.display = 'block';
    } else {
        failedList.style.display = 'none';
    }

    modal.style.display = 'flex';
}

// 删除确认 Modal 辅助
function closeDeleteDocModal() {
    document.getElementById('deleteDocModal').style.display = 'none';
}

function showDeleteDocModal(bodyText, onConfirm) {
    document.getElementById('deleteDocModalBody').textContent = bodyText;
    applyLang(); // 更新 data-i18n 文字（标题、按钮等）

    // 重新绑定确认按钮，避免重复监听
    const btn = document.getElementById('deleteDocConfirmBtn');
    const newBtn = btn.cloneNode(true);
    btn.replaceWith(newBtn);
    newBtn.addEventListener('click', () => {
        closeDeleteDocModal();
        onConfirm(); // 直接用闭包里的 onConfirm，不依赖 _deleteDocCallback
    });

    document.getElementById('deleteDocModal').style.display = 'flex';
}

// 批量删除文档
async function handleBatchDelete() {
    if (state.selectedDocs.size === 0) return;

    const kbId = state.currentDocsKbId;
    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    if (!kb) return;

    const count = state.selectedDocs.size;
    const fileList = Array.from(state.selectedDocs).map(name => `• ${name}`).join('\n');
    const bodyText = t('docs.batchDelete.confirm', {
        kb: kb.name,
        count: count
    }) + `\n\n${fileList}`;

    showDeleteDocModal(bodyText, async () => {
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
            await updateStats();

            text.textContent = '删除成功！';
            setTimeout(() => {
                text.textContent = originalText;
                btn.disabled = false;
            }, 2000);

        } catch (e) {
            console.error('批量删除失败:', e);
            text.textContent = originalText;
            btn.disabled = false;
        }
    });
}

// 单个删除文档
async function deleteSingleDocument(filename) {
    const kbId = state.currentDocsKbId;
    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    if (!kb) return;

    showDeleteDocModal(t('docs.delete.confirm', {
        name: filename
    }), async () => {
        try {
            const res = await fetch(`${API_BASE}/api/documents/${encodeURIComponent(filename)}?kb_id=${encodeURIComponent(kbId)}`, {
                method: 'DELETE',
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || data.message || '删除失败');
            }
            await loadDocuments(kbId);
            await updateStats();
        } catch (e) {
            console.error('删除文档失败:', e);
        }
    });
}

// 关闭上传结果弹窗，并刷新文档列表
function closeUploadResult() {
    document.getElementById('uploadResultModal').style.display = 'none';
    // 关闭时再刷新一次，确保后端索引完成后列表是最新的
    if (state.currentDocsKbId) {
        loadDocuments(state.currentDocsKbId);
        updateStats();
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
window.closeUploadResult = closeUploadResult;
window.closeDeleteDocModal = closeDeleteDocModal;

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

// ── 上传切分参数面板 ─────────────────────────────────────────

/**
 * 切分方式变化时：更新徽章文字、显隐大小/重叠输入框
 */
function _updateUploadChunkPanel() {
    const methodEl = document.getElementById('uploadChunkMethod');
    const method = methodEl ? methodEl.value : '';
    const badge = document.getElementById('uploadChunkBadge');
    const sizeRow = document.getElementById('uploadSizeRow');
    const overRow = document.getElementById('uploadOverlapRow');

    const METHOD_NAMES = {
        '': t('docs.chunkGlobal'),
        'fixed': t('chunk.fixed.short'),
        'recursive': t('chunk.recursive.short'),
        'markdown': t('chunk.markdown.short'),
        'semantic': t('chunk.semantic.short'),
    };

    if (badge) badge.textContent = METHOD_NAMES[method] || method;

    const showSize = method === '' || method === 'fixed' || method === 'recursive';
    if (sizeRow) sizeRow.style.display = showSize ? '' : 'none';
    if (overRow) overRow.style.display = showSize ? '' : 'none';
}

// ── 重新切分文档 ─────────────────────────────────────────────

let _rechunkFilename = null;

/**
 * 打开重切分面板
 */
window.openRechunkPanel = function(filename, method, size, overlap) {
    _rechunkFilename = filename;
    document.getElementById('rechunkFilename').textContent = '文件：' + filename;
    document.getElementById('rechunkMethod').value = method || 'recursive';
    document.getElementById('rechunkSize').value = size || 500;
    document.getElementById('rechunkOverlap').value = overlap || 50;
    document.getElementById('rechunkHint').textContent = '';
    document.getElementById('rechunkConfirmBtn').disabled = false;
    updateRechunkSizeVisibility();
    document.getElementById('rechunkModal').style.display = 'flex';
};

function closeRechunkModal() {
    document.getElementById('rechunkModal').style.display = 'none';
    _rechunkFilename = null;
}

function updateRechunkSizeVisibility() {
    const method = document.getElementById('rechunkMethod').value;
    const show = method === 'fixed' || method === 'recursive';
    document.getElementById('rechunkSizeFields').style.display = show ? '' : 'none';
}

async function confirmRechunk() {
    if (!_rechunkFilename) return;

    const method = document.getElementById('rechunkMethod').value;
    const size = parseInt(document.getElementById('rechunkSize').value) || 500;
    const overlap = parseInt(document.getElementById('rechunkOverlap').value) || 50;
    const hint = document.getElementById('rechunkHint');
    const btn = document.getElementById('rechunkConfirmBtn');

    hint.style.color = 'var(--text-secondary)';
    hint.textContent = t('docs.rechunkDoing');
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/document/rechunk`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                filename: _rechunkFilename,
                kb_id: state.currentDocsKbId || 'knowledge_base',
                chunk_method: method,
                chunk_size: size,
                chunk_overlap: overlap,
            }),
        });
        const data = await res.json();
        if (res.ok) {
            hint.style.color = 'var(--success)';
            hint.textContent = `✅ ${data.message}`;
            setTimeout(() => {
                closeRechunkModal();
                loadDocuments(state.currentDocsKbId);
                updateStats();
            }, 1200);
        } else {
            hint.style.color = 'var(--danger)';
            hint.textContent = '失败: ' + (data.detail || data.message);
            btn.disabled = false;
        }
    } catch (e) {
        hint.style.color = 'var(--danger)';
        hint.textContent = '请求失败: ' + e.message;
        btn.disabled = false;
    }
}

// ── 切分方式下拉框国际化 ─────────────────────────────────────

function refreshChunkMethodSelects() {
    var globalLabel = '— ' + t('docs.chunkGlobal') + ' —';
    var methods = [{
            value: 'fixed',
            text: function() {
                return t('chunk.fixed') + ' - ' + t('chunk.fixed.hint');
            }
        },
        {
            value: 'recursive',
            text: function() {
                return t('chunk.recursive') + ' (' + t('chunk.recursive.tag') + ') - ' + t('chunk.recursive.hint');
            }
        },
        {
            value: 'markdown',
            text: function() {
                return t('chunk.markdown') + ' - ' + t('chunk.markdown.hint');
            }
        },
        {
            value: 'semantic',
            text: function() {
                return t('chunk.semantic') + ' (' + t('chunk.semantic.tag') + ') - ' + t('chunk.semantic.hint');
            }
        },
    ];

    var sel1 = document.getElementById('uploadChunkMethod');
    if (sel1) {
        var cur1 = sel1.value;
        sel1.innerHTML = '';
        var opt0 = document.createElement('option');
        opt0.value = '';
        opt0.textContent = globalLabel;
        if (cur1 === '') opt0.selected = true;
        sel1.appendChild(opt0);
        methods.forEach(function(m) {
            var opt = document.createElement('option');
            opt.value = m.value;
            opt.textContent = m.text();
            if (m.value === cur1) opt.selected = true;
            sel1.appendChild(opt);
        });
    }

    var sel2 = document.getElementById('rechunkMethod');
    if (sel2) {
        var cur2 = sel2.value;
        sel2.innerHTML = '';
        methods.forEach(function(m) {
            var opt = document.createElement('option');
            opt.value = m.value;
            opt.textContent = m.text();
            if (m.value === cur2) opt.selected = true;
            sel2.appendChild(opt);
        });
    }
}

// ── loadDocuments 增强版（含切分记录 + 下载链接）─────────────

async function loadDocuments(kbId) {
    const docsList = document.getElementById('docsList');
    docsList.innerHTML = `<div class="empty-state">${t('kb.loading')}</div>`;

    try {
        const [res, recRes] = await Promise.all([
            fetch(`${API_BASE}/api/documents?kb_id=${encodeURIComponent(kbId)}`),
            fetch(`${API_BASE}/api/documents/chunk-records?kb_id=${encodeURIComponent(kbId)}`),
        ]);

        const data = await res.json();
        const recData = recRes.ok ? await recRes.json() : {
            records: []
        };
        if (!res.ok) throw new Error(data.detail || t('loading'));

        const chunkRecMap = {};
        (recData.records || []).forEach(r => {
            chunkRecMap[r.filename] = r;
        });

        state.documents = (data.documents || []).map(doc => {
            const mdName = (doc.filename || doc.name).replace(/\.[^.]+$/, '.md');
            const rec = chunkRecMap[mdName] || null;
            return {
                name: doc.filename || doc.name,
                upload_time: doc.upload_time || (doc.created ? new Date(doc.created * 1000).toLocaleString('zh-CN') : t('unknown')),
                size: doc.size,
                md_ready: doc.md_ready,
                chunk_method: rec ? rec.chunk_method : null,
                chunk_size: rec ? rec.chunk_size : null,
                chunk_count: rec ? rec.chunk_count : null,
                up_to_date: rec ? rec.up_to_date : null,
            };
        });

        // 加载参数填入 placeholder
        try {
            const paramsRes = await fetch(`${API_BASE}/api/config/rag-params`);
            if (paramsRes.ok) {
                const params = await paramsRes.json();
                const sizeEl = document.getElementById('uploadChunkSize');
                const overlapEl = document.getElementById('uploadChunkOverlap');
                if (sizeEl) sizeEl.placeholder = String(params.chunk_size || 500);
                if (overlapEl) overlapEl.placeholder = String(params.chunk_overlap || 50);
            }
        } catch (e) {
            /* 忽略 */
        }

        renderDocuments();
    } catch (e) {
        console.error('加载文档列表失败:', e);
        docsList.innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
    }
}

// renderDocuments 覆盖版（含下载链接 + i18n）
function renderDocuments() {
    const docsList = document.getElementById('docsList');

    if (state.documents.length === 0) {
        docsList.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 64 64" width="48" height="48" fill="none">
                    <circle cx="32" cy="32" r="30" fill="#6366f1" opacity="0.1" />
                    <path d="M24 20h16M24 28h16M24 36h10" stroke="#6366f1" stroke-width="2" stroke-linecap="round"/>
                </svg>
                <p style="margin-top: 8px;">${t('docs.empty')}</p>
                <p style="font-size: 0.85rem; color: var(--text-secondary);">${t('docs.emptyHint')}</p>
            </div>
        `;
        updateBatchDeleteBtn();
        return;
    }

    const METHOD_LABEL = {
        'fixed': `✂️ ${t('chunk.fixed.short')}`,
        'recursive': `🔀 ${t('chunk.recursive.short')}`,
        'markdown': `📑 ${t('chunk.markdown.short')}`,
        'semantic': `🧠 ${t('chunk.semantic.short')}`,
    };

    let tableHTML = `
        <table class="docs-table">
            <thead>
                <tr>
                    <th style="width: 50px; text-align: center;">
                        <input type="checkbox" id="selectAllDocs" onchange="window.toggleSelectAll()">
                    </th>
                    <th style="width: 60px;"></th>
                    <th>${t('docs.colName')}</th>
                    <th style="width: 130px;">${t('docs.colChunk')}</th>
                    <th style="width: 180px;">${t('docs.colTime')}</th>
                    <th style="width: 80px; text-align: center;">${t('docs.colAction')}</th>
                </tr>
            </thead>
            <tbody>`;

    state.documents.forEach(doc => {
        if (!doc || !doc.name) return;

        const isSelected = state.selectedDocs.has(doc.name);
        const fileExt = doc.name.split('.').pop().toLowerCase();
        const fileIcon = getFileIcon(fileExt);
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
                <td style="text-align: center; font-size: 24px;">${fileIcon}</td>
                <td class="doc-name-cell" title="${safeName}">
                    <a href="${API_BASE}/api/document/download?filename=${encodeURIComponent(safeName)}&kb_id=${encodeURIComponent(state.currentDocsKbId || 'knowledge_base')}"
                       target="_blank" style="color:inherit;text-decoration:none;"
                       onmouseover="this.style.textDecoration='underline'"
                       onmouseout="this.style.textDecoration='none'">${safeName}</a>
                </td>
                <td class="doc-chunk-cell">
                    ${doc.chunk_method
                        ? `<span class="chunk-method-tag ${doc.up_to_date === false ? 'stale' : ''} chunk-tag-clickable"
                               title="${t('docs.rechunk')}"
                               onclick="window.openRechunkPanel('${safeName}', '${doc.chunk_method}', ${doc.chunk_size}, ${doc.chunk_overlap})">
                               ${METHOD_LABEL[doc.chunk_method] || doc.chunk_method}
                               <span class="chunk-count">${doc.chunk_count}${getCurrentLang() === 'en' ? '' : '块'}</span>
                               ✏️
                           </span>`
                        : `<span class="chunk-method-tag none chunk-tag-clickable"
                               title="${t('docs.rechunk')}"
                               onclick="window.openRechunkPanel('${safeName}', 'recursive', 500, 50)">
                               ${t('docs.legacy')} ✏️
                           </span>`
                    }
                </td>
                <td class="doc-time-cell">${doc.upload_time || t('unknown')}</td>
                <td style="text-align: center;">
                    <button class="icon-btn doc-delete-btn" onclick="window.deleteSingleDocument('${safeName}')" title="${t('btn.delete')}">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
                            <path d="M10 11v6M14 11v6"></path>
                        </svg>
                    </button>
                </td>
            </tr>`;
    });

    tableHTML += '</tbody></table>';
    docsList.innerHTML = tableHTML;
    updateBatchDeleteBtn();
    updateSelectAllCheckbox();
}

// ── langchange 事件监听 ──────────────────────────────────────

document.addEventListener('langchange', function() {
    renderKnowledgeBases();
    refreshChunkMethodSelects();
    if (state.currentDocsKbId) renderDocuments();
});