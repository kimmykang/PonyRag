// 渲染文档列表
function renderDocuments() {
    const docsList = document.getElementById('docsList');

    console.log('renderDocuments 被调用，文档数量:', state.documents.length);
    console.log('文档数据示例:', state.documents[0]);

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

    // 表格形式
    const tableRows = state.documents.map(doc => {
        if (!doc || !doc.name) {
            console.warn('无效的文档对象:', doc);
            return '';
        }

        const isSelected = state.selectedDocs.has(doc.name);
        const fileExt = doc.name.split('.').pop().toLowerCase();
        const fileIcon = getFileIcon(fileExt);
        const escapedName = escapeHtml(doc.name);

        return `
            <tr class="doc-table-row ${isSelected ? 'selected' : ''}">
                <td style="text-align: center;">
                    <input type="checkbox" class="doc-checkbox" ${isSelected ? 'checked' : ''} 
                           onchange="toggleDocSelection('${escapedName}')">
                </td>
                <td style="text-align: center;">
                    <div class="doc-icon-small">${fileIcon}</div>
                </td>
                <td class="doc-name-cell" title="${escapedName}">
                    ${escapedName}
                </td>
                <td class="doc-time-cell">
                    ${doc.upload_time || '未知'}
                </td>
                <td style="text-align: center;">
                    <button class="icon-btn doc-delete-btn" onclick="deleteSingleDocument('${escapedName}')" title="删除">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
                            <path d="M10 11v6M14 11v6"></path>
                        </svg>
                    </button>
                </td>
            </tr>
        `;
    }).filter(html => html !== '').join('');

    docsList.innerHTML = `
        <table class="docs-table">
            <thead>
                <tr>
                    <th style="width: 40px; text-align: center;">
                        <input type="checkbox" id="selectAllDocs" onchange="toggleSelectAll()">
                    </th>
                    <th style="width: 50px;"></th>
                    <th>文件名</th>
                    <th style="width: 180px;">上传时间</th>
                    <th style="width: 60px; text-align: center;">操作</th>
                </tr>
            </thead>
            <tbody>
                ${tableRows}
            </tbody>
        </table>
    `;

    updateBatchDeleteBtn();
    updateSelectAllCheckbox();
}