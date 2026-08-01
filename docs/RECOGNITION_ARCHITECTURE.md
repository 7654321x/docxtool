# 文档识别架构

导入流程现在按以下顺序工作：

```text
DOCX 块抽取 -> 统一特征 -> 文档模式 -> 候选提供器 -> 硬约束 -> Beam Search
-> 结构树 -> 结构校验 -> 兼容 type_id -> 现有渲染器
```

## Web 边界

`src/docxtool/web/app.py` 仍是 HTTP 兼容入口；纯环境解析和 CORS 响应头生成已迁移到
`src/docxtool/web/config.py`。该模块只消费配置值并返回解析结果，不读写数据库、不启动
worker，也不触碰 DOCX 识别链路。

管理员 session 创建、刷新、删除、legacy 管理 token 提取、管理员请求上下文和 CSRF 校验
已迁移到 `src/docxtool/web/admin_auth.py`。该模块通过调用方注入的 SQLite 连接器、锁和
密钥配置工作，不处理 HTTP 路由、不生成页面，也不触碰 DOCX 识别链路。

匿名用户 owner cookie 的签名、解析、Set-Cookie 头和匿名模板接口 Origin 校验已迁移到
`src/docxtool/web/anonymous_identity.py`。该模块只处理传入的 headers、cookie 字符串、
时间函数和密钥配置，不访问用户表、任务表或 DOCX 识别链路。

普通用户登录 session 哈希、登录 Cookie、用户 session 查询/刷新/删除、统一 principal 和
CSRF 校验已迁移到 `src/docxtool/web/user_auth.py`。该模块通过调用方注入的 SQLite 连接器、
锁、cookie 名和匿名身份解析函数工作，不处理 HTTP 路由、不迁移匿名资源，也不触碰 DOCX
识别链路。

可信代理来源、代理 IP 头解析、IPv4/IPv6 校验和常量时间密钥比较已迁移到
`src/docxtool/web/client_ip.py`。该模块只根据调用方传入的 headers、socket 地址和代理配置
返回客户端 IP 或布尔判断，不访问请求处理器、数据库、任务队列或 DOCX 识别链路。

健康检查、readiness、版本信息和启动 URL payload 已迁移到 `src/docxtool/web/health.py`。
`web.app` 只注入当前数据库检查、运行目录、队列计数和版本配置，继续保留旧私有入口。

后台维护线程的定时唤醒逻辑已迁移到 `src/docxtool/web/maintenance.py`。在永久保留策略下，
该模块只负责兼容既有维护线程入口，不删除用户原件、输出、日志或任务记录，也不触碰 DOCX
识别链路。

Web SQLite 建表、旧表补列、兼容索引和默认模板 seed 编排已迁移到
`src/docxtool/web/database_schema.py`。该模块通过调用方注入的连接工厂、线程锁和 seed
函数工作，不持有 HTTP 处理器、不维护任务队列，也不触碰 DOCX 识别、规范化或渲染链路。

监控页的分页查询、页数计算和链接生成已迁移到 `src/docxtool/web/monitoring.py`。
该模块只处理 query dict、URL 和 SQL 片段字符串，不读取任务表，也不生成监控页面 HTML。

管理员监控页面中的分页、状态标签、IP 明细和任务日志 HTML 渲染已迁移到
`src/docxtool/web/monitoring_pages.py`。该模块只消费调用方传入的统计数据、CSRF 片段和
IP 查询回调，不直接访问数据库、任务队列、HTTP handler 或 DOCX 识别链路。

任务执行边界选择和后台 worker 线程启动已迁移到 `src/docxtool/web/task_worker.py`。该模块
只根据调用方传入的主线程判断、direct/subprocess runner 和记录回调编排任务执行，不导入、
识别或导出 DOCX，也不持有数据库连接。

匿名 owner 的任务归属、私人模板归属和重名模板导入改名已迁移到
`src/docxtool/web/owner_migration.py`。该模块只处理调用方传入的 SQLite 连接或连接器，
不创建用户、不校验密码、不处理 HTTP 路由，也不读取或修改 DOCX 识别链路。

预设模板名称、模板 ID、格式配置归一化和 preset 行数据脱敏已迁移到
`src/docxtool/web/preset_config.py`。该模块只校验配置对象并返回 API 结构，不直接读写数据库、
不执行任务，也不改变 DOCX 识别和排版规则。

默认公文模板配置、默认功能开关和 `official_document` seed 逻辑已迁移到
`src/docxtool/web/preset_defaults.py`。该模块只消费调用方传入的样式规则、页面设置、连接和时间函数，
不处理 HTTP 请求，也不改变 DOCX 识别候选、状态机或渲染规则。

预设模板列表、详情、创建、更新和删除的数据库读写已迁移到
`src/docxtool/web/preset_store.py`。该模块通过调用方注入的 SQLite 连接器、锁、配置校验函数和
JSON 序列化函数工作，不处理 HTTP 路由、不解析请求体，也不参与 DOCX 识别或渲染。

上传限流、认证限流、IP 封禁、IP 活动查询和上传次数限制设置已迁移到
`src/docxtool/web/rate_limits.py`。该模块通过调用方注入的 SQLite 连接器和锁访问任务、
设置与封禁表，不处理 HTTP 响应，也不触碰 DOCX 导入、识别或渲染链路。

文件名清理、排版结果下载名、`Content-Disposition` 和内部错误脱敏已迁移到
`src/docxtool/web/file_utils.py`。该模块只处理字符串，不读取或写入用户文件。

上传接口的 `X-Format-Config` 解码、格式配置校验、预设元数据读取和处理模式冲突检查
已迁移到 `src/docxtool/web/format_request.py`。该模块只处理 headers 和配置对象，
复用现有格式配置校验规则，不读取任务表、不入队，也不执行 DOCX 识别。

HTTP 路径归一、Cookie 取值、CSRF 头读取、管理页隐藏字段、紧凑 JSON 和 HTML 转义
已迁移到 `src/docxtool/web/request_utils.py`。该模块只处理请求头、字节和字符串，
不访问数据库、不读取运行目录，也不参与识别或排版。

Web 管理密钥、代理密钥的环境读取和弱密钥启动校验已迁移到
`src/docxtool/web/secrets.py`。该模块只处理环境映射和密钥字符串，不访问数据库、不处理 HTTP
路由，也不触碰 DOCX 识别链路。

HTTP 请求体定长读取、上传内容写入文件和结果文件流输出已迁移到
`src/docxtool/web/stream_io.py`。该模块只处理调用方传入的流、路径和 writer，
不判断任务状态、不生成文件名，也不参与 DOCX 导入、识别或渲染。

内存任务缓存容量裁剪已迁移到 `src/docxtool/web/task_cache.py`。该模块只处理调用方传入的
任务有序映射和容量配置，不访问数据库、不处理 HTTP 路由，也不执行 DOCX 识别或渲染。

任务临时目录、上传原件目录、输出目录、路径越界校验和永久保留清理钩子已迁移到
`src/docxtool/web/task_paths.py`。该模块只计算路径和删除未完成上传或无效输出，
不读取任务表、不改变已接收原件/成功结果/任务记录的永久保留策略。

任务排队记录、处理中状态和终态字段写入已迁移到 `src/docxtool/web/task_records.py`。
该模块通过调用方注入的 SQLite 连接器、锁、当前时间函数和下载文件名生成函数工作，
不维护内存队列、不启动 worker，也不执行 DOCX 导入、识别或渲染。

启动时 queued/processing 任务恢复为 interrupted 的逻辑已迁移到
`src/docxtool/web/task_recovery.py`。该模块通过调用方注入的连接器、锁和时间函数工作，
只处理任务终态补记，不启动 worker、不重新排队，也不执行 DOCX 识别或渲染。

终态任务结果的数据库统计写入、失败输出清理、内存任务状态同步和脱敏日志记录已迁移到
`src/docxtool/web/task_result.py`。该模块通过调用方注入的任务映射、锁、写库回调、清理回调和
logger 工作，不执行 DOCX 导入、识别或渲染，也不改变处理结果本身。

任务结果统计写入、按日汇总、监控页计数和 IP 聚合查询已迁移到
`src/docxtool/web/task_statistics.py`。该模块通过调用方注入的连接器、锁、时间函数和分页函数
工作，不维护内存任务状态、不生成监控 HTML，也不执行 DOCX 识别或渲染。

任务计数、队列位置、公开任务状态脱敏、识别审核摘要和任务处理选项 JSON 已迁移到
`src/docxtool/web/task_state.py`。该模块只消费调用方传入的任务字典、队列容器和数据库加载器，
不直接连接数据库、不处理 HTTP 路由，也不读取 DOCX 正文。

启动时区提示、HTTP Date 解析和北京网络时间校验已迁移到
`src/docxtool/web/time_check.py`。`web.app` 仅保留旧私有入口，主启动流程继续使用相同提示行。

## 共享文档模型

`src/docxtool/document/models/` 提供导入后的稳定数据契约：

- `source.py`：源 run 格式事实和逻辑段边界候选。
- `paragraph.py`：物理段特征、行内 token 和逻辑段落数据。
- `document.py`：整篇文档数据、body 顺序块和规范化审计记录。

旧的 `docxtool.document.importer` 仍 re-export 这些类型，保持现有测试、SDK 和渲染器导入路径兼容。

## 逻辑分段边界

`src/docxtool/document/segmentation/` 开始承接物理段到逻辑段的守恒职责：

- `source_locator.py`：根据源物理段 raw span 写入 UTF-16 locator、canonical locator 和段内格式特征。旧的 importer 私有函数名仍作为兼容入口转发到该模块。

当前软换行、标题正文粘连和尾部软换行拆分规则仍保留在 importer 编排中，后续迁移时必须继续保持文字覆盖、不重叠和不丢失。

## 目录

`src/docxtool/document/recognition/` 包含识别层：

- `features.py`：保留原文的块模型和共享特征。表格、图片、空段和分页标记不会被静默丢弃。
- `colon.py`：共享冒号结构分析，只输出标签、值、称呼形态、机构形态、解释性正文等事实，不直接返回最终类型。
- `model.py`：`DocumentMode`、`SectionKind`、`ParagraphType` 三层模型。
- `candidates.py`：结构、键值、编号、语义、旧分类器和样式候选提供器。旧分类结果只作为兼容候选。
- `global_context.py`：文首结构、正文边界和同级标题族的全文只读分析。
- `decoder.py`：硬结构否决、标题序列冲突复核和宽度可配置的确定性 Beam Search；默认宽度为 12。
- `compatibility.py`：内部段落类型到旧渲染 `type_id` 的唯一映射边界。
- `validators.py`：有限结构序列校验。
- `diagnostics.py`：只输出结构信息，不输出源文档正文、OOXML 或敏感字段。
- `config.py` / `version.py`：集中管理 Beam 宽度、候选上限、诊断开关和引擎/schema 版本。

`src/docxtool/document/normalization/` 位于识别层之后：

- `tail.py`：消费最终 `type_id`，整理已确认的附件说明、落款单位、成文日期和附件正文页标记，并同步识别诊断。它不重新生成候选、不重新判定正文或标题，也不改变候选分数。

## 关键规则

- 结构化发文字号优先于标题续行；`dispatch_number` 不会被标题视觉样式覆盖。
- 会议纪要通过标题、会议元数据和正文信号联合判断；带可选编号的 `出席/缺席/列席` 仍属于会议元数据。
- 签发日期或来源说明后的独立规划、方案、报告等标题可识别为被印发文件标题。
- 非 `REPORT` 模式不会设置 `report_first_sentence_bold`。
- Docxtool 自身样式不能单独否决文本结构，幂等复跑保留相同类型和诊断结果。
- 冒号结构统一由 `colon.py` 生成证据；文首可形成主送机关或称呼候选，正文区的机构标签优先作为正文标签，解释性冒号正文不会被键值字段规则吞掉。
- 行内“称呼：正文”可在结构拆分层拆成 `addressing + body`；“机构名称：正文内容”保持一个正文段，避免仅凭冒号拆段。
- 标题编号会结合全文标题族判断重复、倒序、跳号、缺失父标题等冲突；最可能类型仍可应用，但必须进入 `review` 并输出 `HEADING_SEQUENCE_CONFLICT`。
- 附件说明不再由“附件”关键词直接 hard 决定；必须由正文已开始、尾部邻接、附件项/附件页/落款日期等全文上下文共同确认。
- 落款单位不维护具体机关、地区或人员名单；只使用文尾位置、后接日期、独立短行、无正文标点和通用组织后缀等组合证据。
- 标题族按最近活动父标题作用域分组，不同一级标题下的同级子标题序号可以重置，同一父标题内重复或缺父标题才进入复核。

## 诊断

导入后的 `DocumentData.recognition_diagnostics` 可用于日志或测试；通过
`diagnostics_to_json()` 序列化时只保留模式、块索引、类型、板块、候选来源和校验结果，
不会包含原文。

诊断结构版本为 `1.0`，识别引擎版本为 `3.0`。关闭诊断只省略候选轨迹，
不会改变候选、排序或最终类型；文本预览使用 SHA-256 短哈希。

## 性能

执行 `python scripts/benchmark_recognition.py` 可获得 25、200、800 段文档的
块抽取、特征提取、模式识别、解码/校验/结构树和总耗时 JSON。脚本只使用内存对象，
不会写入 DOCX 或修改仓库文件。

## 回归

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
node --test tests/worker-routing.test.mjs
node --test tests/frontend-format-config.test.mjs
```
