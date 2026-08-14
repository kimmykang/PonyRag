# 文档管理功能工作流程图

## 用户操作流程

```
知识库管理页面
    |
    v
[知识库卡片] 
    |
    |-- 点击"管理文档"按钮
    |
    v
┌─────────────────────────────────────────────┐
│        文档管理弹窗 (Modal)                  │
├─────────────────────────────────────────────┤
│  标题: 文档管理 - [知识库名称]       [关闭] │
├─────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────────┐            │
│  │上传文档  │  │批量删除 (0)  │ [禁用]     │
│  └──────────┘  └──────────────┘            │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │ ☐ 📄 example.pdf                    │   │
│  │    上传时间: 2024-08-11 10:30:00    │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │ ☑ 📝 report.docx                    │   │
│  │    上传时间: 2024-08-11 09:15:00    │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │ ☑ 📊 data.xlsx                      │   │
│  │    上传时间: 2024-08-10 14:20:00    │   │
│  └─────────────────────────────────────┘   │
│                                             │
└─────────────────────────────────────────────┘
    |
    |-- 选中文档后
    v
┌─────────────────────────────────────────────┐
│  ┌──────────┐  ┌──────────────┐            │
│  │上传文档  │  │批量删除 (2)  │ [启用]     │
│  └──────────┘  └──────────────┘            │
└─────────────────────────────────────────────┘
```

## 功能调用链

### 1. 打开文档管理弹窗
```
用户点击"管理文档" 
    → manageDocuments(kbId)
    → openDocsModal(kbId)
    → fetch(`/api/documents?kb_id=${kbId}`)
    → renderDocuments()
    → 显示文档列表
```

### 2. 上传文档
```
用户点击"上传文档"
    → 打开文件选择器
    → 用户选择文件
    → handleDocsUpload(event)
    → for each file:
        → FormData + fetch(`/api/upload?kb_id=${kbId}`)
        → 更新进度条
    → loadDocuments(kbId)  // 刷新列表
```

### 3. 批量删除
```
用户勾选文档
    → toggleDocSelection(filename)
    → state.selectedDocs.add(filename)
    → updateBatchDeleteBtn()  // 显示数量

用户点击"批量删除"
    → handleBatchDelete()
    → 弹出确认对话框
    → Promise.all([
        fetch(`/api/documents/${file1}?kb_id=${kbId}`, DELETE),
        fetch(`/api/documents/${file2}?kb_id=${kbId}`, DELETE),
        ...
      ])
    → loadDocuments(kbId)  // 刷新列表
    → state.selectedDocs.clear()
```

### 4. 关闭弹窗
```
用户点击关闭按钮 / 背景
    → closeDocsModal()
    → 隐藏 Modal
    → loadKnowledgeBases()  // 刷新知识库列表（更新文档计数）
```

## 状态管理

### 全局状态 (state)
```javascript
{
    knowledgeBases: [],      // 所有知识库列表
    currentEditingKb: null,  // 当前编辑的知识库
    currentDocsKbId: null,   // 当前管理文档的知识库 ID
    documents: [],           // 当前知识库的文档列表
    selectedDocs: Set(),     // 选中的文档名集合
}
```

### 状态流转
```
初始状态
    ↓
打开弹窗 → currentDocsKbId = kbId
    ↓
加载文档 → documents = [...]
    ↓
用户选择 → selectedDocs.add(filename)
    ↓
删除文档 → selectedDocs.clear()
    ↓
关闭弹窗 → currentDocsKbId = null
           documents = []
           selectedDocs.clear()
```

## API 调用序列图

```
Frontend                Backend                 Vector DB
   |                       |                        |
   |-- GET /api/documents?kb_id=xxx -------------->|
   |                       |                        |
   |                       |-- get_kb(kb_id) ----->|
   |                       |<----------------------|
   |                       |                        |
   |                       |-- list_documents() -->|
   |                       |<----------------------|
   |<-- {documents: [...]}|                        |
   |                       |                        |
   |-- POST /api/upload?kb_id=xxx + FormData ----->|
   |                       |                        |
   |                       |-- upload_file() ------>|
   |                       |-- parse_document() --->|
   |                       |-- chunk_texts() ------>|
   |                       |-- add_documents() ---->|
   |                       |                        |-- insert vectors
   |<-- {status: success} |                        |
   |                       |                        |
   |-- DELETE /api/documents/xxx.pdf?kb_id=xxx --->|
   |                       |                        |
   |                       |-- delete_document() -->|
   |                       |                        |-- delete vectors
   |                       |-- cleanup_document() ->|
   |                       |                        |-- delete files
   |<-- {vectors_removed: 10}                      |
   |                       |                        |
```

## 用户交互时间线

```
T0  用户在知识库列表页面
    ↓
T1  点击某个知识库的"管理文档"按钮
    ↓
T2  [加载中...] 弹窗打开，显示加载提示
    ↓
T3  [文档列表] 显示 5 个文档
    ↓
T4  用户勾选 2 个文档
    → 批量删除按钮: "批量删除 (2)" [启用]
    ↓
T5  用户点击"批量删除"
    → 弹出确认对话框
    ↓
T6  用户确认删除
    → 按钮文字: "删除中..."
    ↓
T7  删除完成
    → 按钮文字: "删除成功！" (2秒后恢复)
    → 文档列表刷新，只剩 3 个文档
    ↓
T8  用户点击"上传文档"
    → 打开文件选择器
    ↓
T9  用户选择 3 个文件
    → 进度条出现
    → "上传中... (1/3) file1.pdf"
    ↓
T10 上传完成
    → "上传完成！"
    → 进度条 2 秒后消失
    → 文档列表刷新，显示 6 个文档
    ↓
T11 用户点击关闭按钮
    → 弹窗关闭
    → 知识库列表刷新（文档计数更新）
```

## 错误处理流程

```
上传失败
    → catch (error)
    → 进度条变红
    → 显示错误消息: "上传失败: [原因]"
    → 3 秒后自动隐藏进度条

删除失败
    → catch (error)
    → alert("批量删除失败: [原因]")
    → 按钮状态恢复

网络错误
    → fetch 失败
    → 捕获异常
    → 显示错误提示
    → 不影响其他功能
```

## 性能优化考虑

### 当前实现
- ✅ 并发删除（Promise.all）
- ✅ 串行上传（避免服务器压力）
- ✅ 实时进度反馈
- ✅ 最小化 DOM 操作（一次性渲染）

### 未来优化
- 🔄 虚拟滚动（>100 个文档）
- 🔄 分页加载
- 🔄 防抖搜索
- 🔄 懒加载图标
- 🔄 上传队列管理

## 安全性考虑

### 当前实现
- ✅ URL 编码文件名（encodeURIComponent）
- ✅ HTML 转义（escapeHtml）
- ✅ 确认对话框（防误删）
- ✅ 后端验证知识库存在性

### 未来增强
- 🔄 文件大小限制提示
- 🔄 文件类型验证（前端）
- 🔄 上传进度取消功能
- 🔄 敏感文件名过滤
