# DocxTool 架构 DAG

本文只记录现有调用链和协议边界，不引入新的运行时 DAG 调度器。当前 Web
服务仍使用内存队列、daemon worker 线程和 spawn 子进程；SDK 仍使用
`RecognitionRequest -> RecognitionPlan -> HostSnapshot -> RecognitionBinding`
的只读识别与绑定合同。

## DAG A：Web 文档处理链

```mermaid
flowchart TD
    A["HTTP PUT /upload 或 /api/upload"] --> B["Handler 鉴权与请求限制"]
    B --> C["读取请求体到 RUNTIME_TMP_DIR/task-id/input.docx"]
    C --> D["validate_docx_upload 安全检查"]
    D --> E["detect_docx_complexity 兼容性提示"]
    E --> F["_ensure_workers_started"]
    F --> G["_enqueue_task 写 tasks queued 并入 TASK_QUEUE"]
    G --> H["HTTP 返回 task_id/status=queued"]
    G --> I["_worker_loop 取出任务"]
    I --> J["_mark_task_processing 写 processing"]
    J --> K["_process_task 选择执行边界"]
    K --> L["_task_process_subprocess spawn 子进程"]
    L --> M["_task_process_body"]
    M --> N["DocxImporter.load 导入与识别"]
    N --> O["export_doc 生成 DOCX"]
    O --> P["validate_docx_integrity 输出完整性校验"]
    P --> Q["_record_task_result 写数据库和内存终态"]
    Q --> R["GET /status/task_id 查询状态"]
    Q --> S["GET /download/task_id 下载结果"]

    B --> B1["鉴权/限流失败：JSON error"]
    C --> C1["上传超时或不完整：清理半成品并失败"]
    D --> D1["DOCX 校验失败：清理半成品并失败"]
    G --> G1["队列满：清理半成品并失败"]
    L --> L1["PROCESS_TIMEOUT：终止子进程并清理本轮输出"]
    M --> M1["导入/识别/导出异常：脱敏错误结果"]
    P --> P1["输出损坏：脱敏错误结果"]
    M1 --> Q
    P1 --> Q
    L1 --> Q
```

### 边界说明

- Web 进程执行：HTTP 路由、鉴权、限流、上传读取、DOCX 上传安全检查、
  任务入队、状态查询和下载响应。
- worker 线程执行：从 `TASK_QUEUE` 取任务、写入 `processing`、调用
  `_process_task` 并把结果收口到 `_record_task_result`。
- 子进程执行：真实 DOCX 导入、识别、导出和输出完整性校验。子进程通过
  `multiprocessing.Queue` 返回可序列化字典，不把 traceback 或正文传给普通用户。
- 持久化边界：上传文件先落到 `RUNTIME_TMP_DIR`；入队时写 SQLite `tasks`
  queued 记录；处理完成后写 `var/outputs`、任务日志和 SQLite 终态。
- 不可交换顺序：必须先完成上传安全检查再入队；必须先写 queued 记录再通知
  worker；必须先导出并通过完整性校验再写 `done` 和下载路径。
- 可跳过或提前失败：鉴权、限流、上传读取、DOCX 校验、队列容量和子进程
  超时都会提前结束。仓库没有独立重试或取消接口；启动恢复只把
  `queued/processing` 旧记录标记为 `interrupted`，不自动重跑。

## DAG B：SDK/宿主适配链

```mermaid
flowchart TD
    A["RecognitionRequest JSON 或 Python 参数"] --> B["JSON Schema 验证"]
    B --> C["跨字段语义验证"]
    C --> D["recognition_request_from_dict"]
    D --> E["recognize_docx"]
    E --> F["DocxImporter.load 识别 DOCX"]
    F --> G["RecognitionPlan"]
    G --> H["validate_recognition_plan"]

    I["HostSnapshot JSON"] --> J["JSON Schema 验证"]
    J --> K["跨字段语义验证"]
    K --> L["host_snapshot_from_dict"]
    L --> M["bind_recognition_plan"]
    H --> M
    M --> N["协议/版本/offset/text contract 前置检查"]
    N --> O["source-locator-v2 与 Host raw_text 对齐"]
    O --> P["RecognitionBinding"]
    P --> Q["confirmed: verify_host_range"]
    P --> R["review: preview_only"]
    P --> S["unresolved: skip"]
    Q --> T["宿主再次校验 preconditions 后自行 apply"]
    R --> U["宿主只预览或人工复核"]
    S --> V["宿主不生成可执行 Range"]
```

### 协议说明

- 公共类型名称来自 `docxtool.sdk`：`RecognitionRequest`、
  `RecognitionPlan`、`HostSnapshot`、`RecognitionBinding`、
  `ValidationReport` 和 `HostSnapshotSummary`。
- Mapping 输入的顺序是 Schema 验证、语义验证、反序列化、执行。CLI 与
  Python API 共享 `validation.py`，因此错误码和 JSON path 保持一致。
- 稳定 ID 边界：`plan_id` 绑定源文件哈希、协议版本、识别引擎、包版本、
  locator 版本、宿主文本契约和请求摘要；`binding_id` 绑定 plan、snapshot、
  文档版本、目标段落、span、状态和写入前置条件。
- 隐私边界：默认 `RecognitionPlan` 不包含正文；`HostSnapshotSummary`
  是无正文摘要，只能用于诊断，不能传给 `bind_recognition_plan`。
- 宿主边界：SDK 不调用 WPS、Office.js 或 VSTO API，也不产生编辑 Range。
  `confirmed` 只表示文本快照可定位；宿主在写入前仍必须验证
  `recommended_action == "verify_host_range"` 和全部 preconditions。

## 调查结论

- I-001：没有发现仓库要求把现有队列、worker、状态机或 importer 改造成
  运行时 DAG 引擎的 ADR、测试或需求。现有测试覆盖了队列可见性、任务中断
  恢复、子进程启动和超时路径；本轮只补文档 DAG。
- I-002：`AGENTS.md` 和现有代码风格没有逐物理行注释要求。仓库已有模块
  docstring 和关键逻辑注释，本轮按高价值注释策略补充职责、边界、不变量和
  失败语义，不给显而易见的语句添加机械注释。
