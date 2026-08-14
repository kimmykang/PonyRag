/**
 * 鐭ヨ瘑搴撶鐞嗛〉闈?- 鍓嶇浜や簰閫昏緫
 * 
 * 鍔熻兘锛?
 *   - 鐭ヨ瘑搴撳垪琛ㄥ睍绀猴紙鍚嶇О銆佹弿杩般€佹枃妗ｆ暟銆佸悜閲忔暟銆佸惎鐢ㄧ姸鎬侊級
 *   - 鍒涘缓鏂扮煡璇嗗簱
 *   - 缂栬緫鐭ヨ瘑搴撲俊鎭紙鍚嶇О銆佹弿杩帮級
 *   - 鍚敤/绂佺敤鐭ヨ瘑搴?
 *   - 鍒犻櫎鐭ヨ瘑搴?
 *   - 璺宠浆鍒版枃妗ｄ笂浼犻〉闈紙鎼哄甫 kb_id锛?
 */

// API 鍩虹鍦板潃
const API_BASE = window.location.origin;

// 鍏ㄥ眬鐘舵€?
const state = {
    knowledgeBases: [],
    currentEditingKb: null,
    currentDocsKbId: null, // 褰撳墠姝ｅ湪绠＄悊鏂囨。鐨勭煡璇嗗簱 ID
    documents: [], // 褰撳墠鐭ヨ瘑搴撶殑鏂囨。鍒楄〃
    selectedDocs: new Set(), // 閫変腑鐨勬枃妗ｅ悕闆嗗悎
};

// DOM 鍏冪礌寮曠敤
const dom = {
    sidebar: document.getElementById('sidebar'),
    sidebarToggle: document.getElementById('sidebarToggle'),
    menuBtn: document.getElementById('menuBtn'),
    connectionStatus: document.getElementById('connectionStatus'),
    kbCount: document.getElementById('kbCount'),
    enabledCount: document.getElementById('enabledCount'),
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

    // 鍒犻櫎纭 Modal
    deleteKbModal: document.getElementById('deleteKbModal'),
    deleteKbModalBody: document.getElementById('deleteKbModalBody'),
    deleteKbConfirmBtn: document.getElementById('deleteKbConfirmBtn'),
    deleteKbCancelBtn: document.getElementById('deleteKbCancelBtn'),
};

// 鍒濆鍖?
document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    checkConnection();
    loadKnowledgeBases();
});

function initEventListeners() {
    // 渚ц竟鏍忓垏鎹?
    dom.menuBtn.addEventListener('click', toggleSidebar);
    dom.sidebarToggle.addEventListener('click', toggleSidebar);

    // 鍒涘缓鐭ヨ瘑搴撴寜閽?
    dom.createKbBtn.addEventListener('click', openCreateKbModal);

    // Modal 浜嬩欢
    dom.kbCancelBtn.addEventListener('click', closeKbModal);
    dom.kbSaveBtn.addEventListener('click', saveKnowledgeBase);
    dom.kbModal.addEventListener('click', (e) => {
        if (e.target === dom.kbModal) closeKbModal();
    });

    // 鍒犻櫎 Modal 浜嬩欢
    dom.deleteKbCancelBtn.addEventListener('click', closeDeleteKbModal);

    // 鏂囨。绠＄悊 Modal 浜嬩欢
    document.getElementById('docsCloseBtn').addEventListener('click', closeDocsModal);
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

// 杩炴帴妫€娴?
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
        text.textContent = '宸茶繛鎺?;
    } else {
        dot.className = 'status-dot disconnected';
        text.textContent = '杩炴帴澶辫触';
    }
}

// 鍔犺浇鐭ヨ瘑搴撳垪琛?
async function loadKnowledgeBases() {
    try {
        const res = await fetch(`${API_BASE}/api/knowledge-bases`);
        const data = await res.json();
        state.knowledgeBases = data.knowledge_bases || [];
        renderKnowledgeBases();
        updateStats();
    } catch (e) {
        console.error('鍔犺浇鐭ヨ瘑搴撳垪琛ㄥけ璐?', e);
        dom.kbGrid.innerHTML = '<div class="empty-state">鍔犺浇澶辫触锛岃鍒锋柊椤甸潰</div>';
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
                <p>鏆傛棤鐭ヨ瘑搴?/p>
                <p style="font-size: 0.9rem; color: var(--text-secondary);">鐐瑰嚮銆屽垱寤虹煡璇嗗簱銆嶆寜閽紑濮?/p>
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
                        <button class="icon-btn" onclick="toggleKbEnabled('${kb.kb_id}', ${kb.enabled})" title="${kb.enabled ? '绂佺敤' : '鍚敤'}">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                                ${kb.enabled 
                                    ? '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>'
                                    : '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line>'
                                }
                            </svg>
                        </button>
                        <button class="icon-btn" onclick="openEditKbModal('${kb.kb_id}')" title="缂栬緫">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                            </svg>
                        </button>
                        <button class="icon-btn" onclick="openDeleteKbModal('${kb.kb_id}')" title="鍒犻櫎">
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
                    <span class="kb-stat-label">鏂囨。</span>
                    <span class="kb-stat-value">${kb.document_count || 0}</span>
                </div>
                <div class="kb-stat-item">
                    <span class="kb-stat-label">鍚戦噺</span>
                    <span class="kb-stat-value">${kb.vector_count || 0}</span>
                </div>
                <div class="kb-stat-item">
                    <span class="kb-stat-label">鐘舵€?/span>
                    <span class="kb-stat-badge ${kb.enabled ? 'enabled' : 'disabled'}">
                        ${kb.enabled ? '宸插惎鐢? : '宸茬鐢?}
                    </span>
                </div>
            </div>
            
            <div class="kb-card-footer">
                <button class="btn btn-secondary btn-sm" onclick="goToChat('${kb.kb_id}')">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                    瀵硅瘽
                </button>
                <button class="btn btn-primary btn-sm" onclick="manageDocuments('${kb.kb_id}')">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                    </svg>
                    绠＄悊鏂囨。
                </button>
            </div>
        </div>
    `).join('');
}

function updateStats() {
    dom.kbCount.textContent = state.knowledgeBases.length;
    const enabledCount = state.knowledgeBases.filter(kb => kb.enabled).length;
    dom.enabledCount.textContent = `${enabledCount} / ${state.knowledgeBases.length}`;
}

// 鍒涘缓鐭ヨ瘑搴?Modal
function openCreateKbModal() {
    state.currentEditingKb = null;
    dom.kbModalTitle.textContent = '鍒涘缓鐭ヨ瘑搴?;
    dom.kbNameInput.value = '';
    dom.kbDescInput.value = '';
    dom.kbModalHint.textContent = '';
    dom.kbModal.style.display = 'flex';
    setTimeout(() => dom.kbNameInput.focus(), 100);
}

// 缂栬緫鐭ヨ瘑搴?Modal
function openEditKbModal(kbId) {
    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    if (!kb) return;

    state.currentEditingKb = kb;
    dom.kbModalTitle.textContent = '缂栬緫鐭ヨ瘑搴?;
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

// 淇濆瓨鐭ヨ瘑搴?
async function saveKnowledgeBase() {
    const name = dom.kbNameInput.value.trim();
    const description = dom.kbDescInput.value.trim();

    if (!name) {
        dom.kbModalHint.textContent = '璇疯緭鍏ョ煡璇嗗簱鍚嶇О';
        dom.kbModalHint.style.color = 'var(--danger)';
        return;
    }

    dom.kbModalHint.textContent = '淇濆瓨涓?..';
    dom.kbModalHint.style.color = 'var(--text-secondary)';
    dom.kbSaveBtn.disabled = true;

    try {
        let res, data;

        if (state.currentEditingKb) {
            // 缂栬緫鐜版湁鐭ヨ瘑搴?
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
            // 鍒涘缓鏂扮煡璇嗗簱
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
            dom.kbModalHint.textContent = data.detail || data.message || '淇濆瓨澶辫触';
            dom.kbModalHint.style.color = 'var(--danger)';
        }
    } catch (e) {
        dom.kbModalHint.textContent = '缃戠粶閿欒: ' + e.message;
        dom.kbModalHint.style.color = 'var(--danger)';
    } finally {
        dom.kbSaveBtn.disabled = false;
    }
}

// 鍒囨崲鍚敤/绂佺敤鐘舵€?
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
            alert('鎿嶄綔澶辫触: ' + (data.detail || data.message));
        }
    } catch (e) {
        alert('缃戠粶閿欒: ' + e.message);
    }
}

// 鍒犻櫎鐭ヨ瘑搴?
function openDeleteKbModal(kbId) {
    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    if (!kb) return;

    dom.deleteKbModalBody.textContent = `纭畾瑕佸垹闄ょ煡璇嗗簱銆?{kb.name}銆嶅悧锛焋;
    dom.deleteKbModal.style.display = 'flex';

    // 绉婚櫎鏃х殑浜嬩欢鐩戝惉鍣紝缁戝畾鏂扮殑
    const newConfirmBtn = dom.deleteKbConfirmBtn.cloneNode(true);
    dom.deleteKbConfirmBtn.replaceWith(newConfirmBtn);

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
            alert('鍒犻櫎澶辫触: ' + (data.detail || data.message));
        }
    } catch (e) {
        alert('缃戠粶閿欒: ' + e.message);
    }
}

// 璺宠浆鍒拌亰澶╅〉闈紙甯︾煡璇嗗簱涓婁笅鏂囷級
function goToChat(kbId) {
    localStorage.setItem('current_kb_id', kbId);
    window.location.href = '/';
}

// 绠＄悊鏂囨。锛堟墦寮€鏂囨。绠＄悊 Modal锛?
function manageDocuments(kbId) {
    console.log('manageDocuments 琚皟鐢? kbId:', kbId);
    openDocsModal(kbId);
}

// ========================================
// 鏂囨。绠＄悊 Modal
// ========================================

// 鎵撳紑鏂囨。绠＄悊 Modal
async function openDocsModal(kbId) {
    console.log('openDocsModal 琚皟鐢? kbId:', kbId);

    const kb = state.knowledgeBases.find(k => k.kb_id === kbId);
    console.log('鎵惧埌鐨勭煡璇嗗簱:', kb);

    if (!kb) {
        console.error('鐭ヨ瘑搴撲笉瀛樺湪:', kbId);
        return;
    }

    state.currentDocsKbId = kbId;
    state.selectedDocs.clear();

    // 璁剧疆鏍囬
    const titleEl = document.getElementById('docsModalTitle');
    console.log('鏍囬鍏冪礌:', titleEl);
    if (titleEl) {
        titleEl.textContent = `鏂囨。绠＄悊 - ${kb.name}`;
    }

    // 鏄剧ず Modal
    const modalEl = document.getElementById('docsModal');
    console.log('Modal 鍏冪礌:', modalEl);

    if (modalEl) {
        modalEl.style.display = 'flex';
        console.log('Modal display 宸茶缃负 flex');
    } else {
        console.error('鎵句笉鍒?docsModal 鍏冪礌锛?);
    }

    // 鍔犺浇鏂囨。鍒楄〃
    await loadDocuments(kbId);
}

// 鍏抽棴鏂囨。绠＄悊 Modal
function closeDocsModal() {
    document.getElementById('docsModal').style.display = 'none';
    state.currentDocsKbId = null;
    state.documents = [];
    state.selectedDocs.clear();

    // 閲嶆柊鍔犺浇鐭ヨ瘑搴撳垪琛紙鏇存柊鏂囨。鏁伴噺锛?
    loadKnowledgeBases();
}

// 鍔犺浇鏂囨。鍒楄〃
async function loadDocuments(kbId) {
    const docsList = document.getElementById('docsList');
    docsList.innerHTML = '<div class="empty-state">鍔犺浇涓?..</div>';

    try {
        console.log('寮€濮嬪姞杞芥枃妗ｏ紝kb_id:', kbId);
        const res = await fetch(`${API_BASE}/api/documents?kb_id=${encodeURIComponent(kbId)}`);
        console.log('API 鍝嶅簲鐘舵€?', res.status);

        const data = await res.json();
        console.log('API 杩斿洖鏁版嵁:', data);

        if (!res.ok) {
            throw new Error(data.detail || '鍔犺浇澶辫触');
        }

        // 鍚庣杩斿洖鐨勫瓧娈垫槸 filename, created锛岄渶瑕佽浆鎹负 name, upload_time
        state.documents = (data.documents || []).map(doc => ({
            name: doc.filename || doc.name, // 鍏煎涓ょ瀛楁鍚?
            upload_time: doc.upload_time || (doc.created ? new Date(doc.created * 1000).toLocaleString('zh-CN') : '鏈煡'),
            size: doc.size,
            md_ready: doc.md_ready
        }));

        console.log('鎴愬姛鍔犺浇鏂囨。鏁伴噺:', state.documents.length);
        console.log('杞崲鍚庣殑鏂囨。鏁版嵁:', state.documents[0]);

        renderDocuments();
    } catch (e) {
        console.error('鍔犺浇鏂囨。鍒楄〃澶辫触:', e);
        docsList.innerHTML = `<div class="empty-state">鍔犺浇澶辫触: ${e.message}</div>`;
    }
}

// 娓叉煋鏂囨。鍒楄〃
