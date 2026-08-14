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