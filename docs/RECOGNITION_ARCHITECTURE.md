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

管理员登录表单字段解析已迁移到 `src/docxtool/web/admin_forms.py`。该模块只处理已经读取
到内存中的 URL 编码表单 bytes，不读取 HTTP 流、不校验密钥，也不创建管理员 session。

管理员登录页 HTML 渲染已迁移到 `src/docxtool/web/admin_pages.py`。该模块只返回静态页面
字符串，不读取请求体、不校验管理员密钥，也不访问任务、数据库或 DOCX。

管理员监控页 IP 详情、封禁、解封、上传限额和兼容清理动作处理已迁移到
`src/docxtool/web/admin_route_handlers.py`。该模块只消费 handler facade、已解析 URL 和调用方
注入的 IP 校验/存储回调，不直接连接数据库、不处理 DOCX，也不改变永久保留策略。

管理员 session 查询、登录和退出路由处理已迁移到 `src/docxtool/web/admin_session_routes.py`。
该模块只消费 handler facade、表单读取、session 查询/创建/删除和 Cookie 构造回调，不直接访问
SQLite、不渲染页面，也不触碰 DOCX 识别链路。

管理员请求上下文默认值、页面 CSRF token 提取和管理员 POST CSRF 校验已迁移到
`src/docxtool/web/admin_access.py`。该模块只消费调用方已解析出的管理员上下文、请求参数和
请求头，不创建管理员 session、不读取数据库、不处理 HTTP 路由，也不触碰 DOCX 识别链路。

管理员监控页 IP 查询、封禁原因和上传限制表单参数解析已迁移到
`src/docxtool/web/admin_actions.py`。该模块只处理 URL query 和已解析参数字典，不读写封禁表、
设置表或任务表，也不生成 HTTP 响应。

匿名用户 owner cookie 的签名、解析、Set-Cookie 头和匿名模板接口 Origin 校验已迁移到
`src/docxtool/web/anonymous_identity.py`。该模块只处理传入的 headers、cookie 字符串、
时间函数和密钥配置，不访问用户表、任务表或 DOCX 识别链路。

用户认证接口的 JSON Content-Type 判断、公开用户 data、`/auth/me` data 和附加 Cookie 头组装
已迁移到 `src/docxtool/web/auth_payloads.py`。该模块只消费调用方传入的 headers、principal、
用户字段和 cookie 字符串，不访问数据库、不校验密码，也不处理 HTTP 路由。

普通用户 `/auth/me`、注册、登录和退出路由处理已迁移到
`src/docxtool/web/auth_route_handlers.py`。该模块通过调用方注入的校验、限流、数据库连接、
密码、session 和迁移回调工作，不直接导入 DOCX 识别或渲染链路。

普通用户登录 session 哈希、登录 Cookie、用户 session 查询/刷新/删除、统一 principal 和
CSRF 校验已迁移到 `src/docxtool/web/user_auth.py`。该模块通过调用方注入的 SQLite 连接器、
锁、cookie 名和匿名身份解析函数工作，不处理 HTTP 路由、不迁移匿名资源，也不触碰 DOCX
识别链路。

可信代理来源、代理 IP 头解析、IPv4/IPv6 校验和常量时间密钥比较已迁移到
`src/docxtool/web/client_ip.py`。该模块只根据调用方传入的 headers、socket 地址和代理配置
返回客户端 IP 或布尔判断，不访问请求处理器、数据库、任务队列或 DOCX 识别链路。

健康检查、readiness、版本信息和启动 URL payload 已迁移到 `src/docxtool/web/health.py`。
`web.app` 只注入当前数据库检查、运行目录、队列计数和版本配置，继续保留旧私有入口。

健康检查、readiness 和版本路由响应发送已迁移到 `src/docxtool/web/health_route_handlers.py`。
该模块只消费 handler facade 和 payload 构造回调，不执行实际 readiness 检查、不访问任务或 DOCX。

前端首页和管理员登录页的路由响应发送已迁移到 `src/docxtool/web/page_route_handlers.py`。
该模块只消费 handler facade、首页读取回调和登录页渲染回调，不校验管理员、不读取数据库，
也不触碰 DOCX 识别链路。

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

管理员监控仪表盘整页 HTML 拼装已迁移到 `src/docxtool/web/monitor_dashboard_page.py`。
该模块只消费调用方传入的统计数据、运行状态和局部 HTML 片段，不查询数据库、不读取
任务表，也不触碰 DOCX 识别链路。

管理员监控首页和统计 JSON 路由响应已迁移到 `src/docxtool/web/monitor_route_handlers.py`。
该模块只消费 handler facade、管理员鉴权回调、统计查询回调和 HTML 渲染回调，不直接
访问 SQLite、不读取任务表，也不触碰 DOCX 识别链路。

后台 worker 一次性启动、队列消费、内存处理中状态写入、任务执行边界选择和子进程入口已迁移到
`src/docxtool/web/task_worker.py`。该模块只根据调用方传入的队列、锁、状态容器、
direct/subprocess runner、子进程 target、结果队列、清理回调和记录回调编排任务执行，
不导入、识别或导出 DOCX，也不持有数据库连接。

已校验上传任务的 queued 记录写入、内存队列写入和 worker 通知顺序已迁移到
`src/docxtool/web/task_queue.py`。该模块只消费任务容器、锁、记录写入和队列信息回调，
不执行 DOCX 识别、排版或导出。

DOCX 上传请求的限流、请求配置解析、临时落盘、安全校验、复杂度提示和任务入队编排已
迁移到 `src/docxtool/web/upload_route_handlers.py`。该模块只消费 handler facade 和调用方注入的
路径、校验、队列、响应构造回调，不直接执行 DOCX 识别、规范化或渲染。

上传 DOCX 任务的应用层处理编排已迁移到 `src/docxtool/application/process_document.py`。该模块
只串联调用方注入的 Importer、Renderer、完整性校验、路径、日志和脱敏辅助，负责生成 Web
任务结果字典；具体段落拆分、识别候选、状态机、规范化和 DOCX 输出规则仍由原有文档层模块负责。

旧 importer 评分链路的 `ScoreDetail`、`ScoreBoard` 和 `DetectionContext` 已迁移到
`src/docxtool/document/recognition/legacy/scoring.py`。`document/importer.py` 继续 re-export
这些类型以保持旧导入路径兼容；本次只移动数据模型，不改变 legacy scorer 的分数、状态推进或最终类型判断。

段落物理格式特征提取、图片可见性、表/图题注判断、行内 token 提取、字面编号前缀提取、Word 自动编号事实判断、分节属性、页眉页脚关系收集和损坏关系副本修复已迁移到
`src/docxtool/document/importing/`。这些模块只读取 python-docx 段落对象和 OOXML 物理事实，
不决定最终段落类型；`document/importer.py` 继续作为兼容编排入口调用它们。

表格、图片、题注、已有版头和页眉页脚关系的导出期源对象保留已迁移到
`src/docxtool/document/engine/preservation.py`。该模块只消费 Renderer 已确认需要透传的
源 OOXML 对象、关系复制器和样式复制器，负责关系迁移、外部关系净化和题注间距归零；
不读取 Importer 状态、不参与段落识别，也不改变最终 `type_id`。

分节页面尺寸、横向页边距旋转、`docGrid` 计算、段落/正文 `sectPr` 替换和奇偶页不同设置保留
已迁移到 `src/docxtool/document/engine/sections.py`。该模块只消费页面配置、源分节 XML 和
Renderer 关系复制器，不读取文档识别上下文，也不改变段落顺序或最终类型。

全局页面设置、documentDefaults、Normal 样式、Word 兼容网格开关也收口在
`src/docxtool/document/engine/sections.py`；旧页脚 PAGE 域兼容写入迁移到
`src/docxtool/document/engine/header_footer.py`。这些模块只修改输出 DOCX 的页面和页脚 XML，
不参与识别、规范化或结构重排。

段落内部 run 样式复制、片段写入、inline token 恢复和普通正文冗余分页符清理已迁移到
`src/docxtool/document/engine/inline.py`。该模块只处理 Renderer 已决定输出的行内内容，
不执行软换行拆段、不判断结构类型，也不改写可见文字顺序。

可靠的“一级标题。正文”输出拆分和最终相邻完整性校验已迁移到
`src/docxtool/document/engine/heading_body_split.py`。该模块不判断是否应该拆段，只消费
Segmenter/Recognition 已确认的拆分事实，把正文写入紧邻段落并在导出末尾校验未丢失。

特殊加粗、冒号标签、责任单位行、键值行、名词解释、报告首句和行内标题正文粗细分离
已迁移到 `src/docxtool/document/engine/inline_effects.py`。该模块只重写已生成输出段落的
run 样式和必要手动换行，不判断段落类型、不新增逻辑段，也不改变识别结果。

中英文字体写入、数字/拉丁字母字体拆分和上标格式化后处理已迁移到
`src/docxtool/document/engine/typography.py`。该模块只处理已生成段落 run 的显示属性，
不参与段落类型判断、编号规范化或文字重排。

字体、对齐、缩进、段前段后、网格对齐和孤行控制等段落直接格式执行已迁移到
`src/docxtool/document/engine/paragraph_format.py`。该模块只消费最终样式规则
`StyleRule` 和已创建的输出段落，负责写入 OOXML 段落格式；不读取 importer、
segmentation 或 recognition 状态，也不修改可见文字。

最终段落类型到 `DCT-*` 样式 ID 的映射、附件标题 keepNext 标记和导出后正文样式不变量
检查已迁移到 `src/docxtool/document/engine/paragraph_styles.py`。该模块只把已经确定的
`type_id` 转换为输出样式并清理 Word 原生编号残留，不重新分类段落。

标题编号计数和段首编号 run 写入已迁移到
`src/docxtool/document/engine/render_numbering.py`。该模块只消费 Recognition/Normalizer
已经确认的最终 `type_id`、样式规则和当前计数器状态，负责在输出段落前插入可见编号；
字面编号识别、损坏编号修复和标题层级裁决仍保留在导入、识别和规范化层，不由 Renderer
反向决定。

渲染阶段功能开关解析已迁移到 `src/docxtool/document/engine/render_options.py`，附件回行列计算
和段首旧标题编号清理已迁移到 `src/docxtool/document/engine/render_text.py`。这两个模块均为
无副作用纯辅助，不访问 DOCX、识别候选或 Normalizer 状态。

最终 `type_id` 到样式规则行的映射、头部留白分组和正文流分组已迁移到
`src/docxtool/document/engine/render_types.py`。该模块只服务 Renderer 查表，不生成或修改
最终类型。

导出前的附件说明、落款单位和成文日期尾部顺序整理及连续性校验已收口到
`src/docxtool/document/engine/signature_block.py`。该逻辑只消费既有最终 `type_id`，
用于阻止不安全的落款/日期分离和保持合法尾部输出顺序，不重新识别 BODY，也不修改
recognition diagnostics。

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

预设模板列表、详情、创建、更新和删除的路由处理已迁移到
`src/docxtool/web/preset_route_handlers.py`。该模块只消费 handler facade、principal 回调和
preset store 回调，不直接访问 SQLite、不解析底层请求流，也不参与 DOCX 识别或渲染。

管理员、文件 API 和模板修改路由中的“先鉴权、再转发动作”逻辑已迁移到
`src/docxtool/web/protected_route_handlers.py`。该模块只消费调用方传入的鉴权回调和动作回调，
不直接读取请求体、不访问数据库，也不触碰 DOCX 识别链路。

管理员、文件 API 和 preset 修改路由的鉴权响应、错误写回和兼容上下文保存已迁移到
`src/docxtool/web/route_authorization.py`。该模块只消费 handler facade、已解析 URL、鉴权回调
和错误构造回调，不直接访问数据库、不读取请求流，也不触碰 DOCX 识别链路。

上传限流、认证限流、IP 封禁、IP 活动查询和上传次数限制设置已迁移到
`src/docxtool/web/rate_limits.py`。该模块通过调用方注入的 SQLite 连接器和锁访问任务、
设置与封禁表，不处理 HTTP 响应，也不触碰 DOCX 导入、识别或渲染链路。

文件 API 的代理密钥和本机调试访问授权已迁移到 `src/docxtool/web/file_api_auth.py`。该模块
只根据调用方传入的 headers、socket client_address、生产模式和密钥比较函数返回布尔值，
不读取文件、不访问数据库，也不使用 Host 头证明本机来源。

文件名清理、排版结果下载名、`Content-Disposition` 和内部错误脱敏已迁移到
`src/docxtool/web/file_utils.py`。该模块只处理字符串，不读取或写入用户文件。

管理员日志展示前的敏感字段脱敏已迁移到 `src/docxtool/web/log_redaction.py`。该模块只处理
调用方传入的日志文本，不读取日志文件、不接触 Cookie 对象，也不访问任务表或 DOCX 内容。

上传接口的 `X-Format-Config` 解码、格式配置校验、预设元数据读取和处理模式冲突检查
已迁移到 `src/docxtool/web/format_request.py`。该模块只处理 headers 和配置对象，
复用现有格式配置校验规则，不读取任务表、不入队，也不执行 DOCX 识别。

前端首页 HTML 的资源定位和读取已迁移到 `src/docxtool/web/frontend_pages.py`。该模块只读取
打包后的 `resources/frontend/pages/index.html` 文本，不处理 HTTP 响应、不访问任务队列，
也不参与 DOCX 识别或导出。

HTTP handler 的 GET/POST/PUT/DELETE 路由动作分派已迁移到
`src/docxtool/web/handler_dispatch.py`。该模块只根据路由匹配结果调用 handler facade 方法，
不直接连接数据库、不读取请求体，也不触碰 DOCX 识别链路。

HTTP handler 的安全响应头、CORS 响应头、OPTIONS 预检响应和方法入口分派已迁移到
`src/docxtool/web/handler_lifecycle.py`。该模块只消费 handler facade、路径规范化回调和
路由分派回调，不处理具体业务、数据库或 DOCX。

HTTP handler 的文本、JSON、跳转和错误响应发送已迁移到
`src/docxtool/web/handler_responses.py`。该模块只消费 handler 对象、响应内容和响应头回调，
不匹配路由、不鉴权、不访问数据库，也不触碰 DOCX 识别链路。

HTTP 路径归一、Cookie 取值、CSRF 头读取、管理页隐藏字段、紧凑 JSON 和 HTML 转义
已迁移到 `src/docxtool/web/request_utils.py`。该模块只处理请求头、字节和字符串，
不访问数据库、不读取运行目录，也不参与识别或排版。

query、JSON body 和 URL 编码表单 body 的请求参数合并已迁移到
`src/docxtool/web/request_params.py`。该模块只消费已解析 URL、HTTP 方法、请求头和调用方传入的
请求体读取函数，不直接访问 socket、数据库、任务队列或 DOCX。

HTTP 文本/JSON 响应编码、附加响应头归一化、`Retry-After` 头和认证接口错误响应体已迁移到
`src/docxtool/web/responses.py`。该模块只返回 bytes、响应头元组或错误 dict，不直接写
socket、不设置 CORS/安全头，也不访问数据库或 DOCX。

Web 兼容处理器的 GET/POST/PUT/DELETE 路由匹配已迁移到 `src/docxtool/web/routing.py`。
该模块只消费已归一化路径并返回动作名称和资源 ID，不执行鉴权、不读取请求体、不访问数据库，
也不调用 DOCX 处理链路。

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

任务状态、DOCX 下载和任务日志页面路由处理已迁移到
`src/docxtool/web/task_route_handlers.py`。该模块只消费 handler facade、任务映射、数据库连接
回调、文件流和日志渲染回调，不执行 DOCX 导入、识别或渲染。

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

Web 服务启动顺序、启动日志、TCP_NODELAY 设置和 KeyboardInterrupt 关闭流程已迁移到
`src/docxtool/web/server_runtime.py`。该模块只消费调用方注入的启动回调、HTTPServer 类型和
运行配置，不处理 HTTP 路由、不访问数据库细节，也不触碰 DOCX 识别链路。

## 共享文档模型

`src/docxtool/document/models/` 提供导入后的稳定数据契约：

- `source.py`：源 run 格式事实和逻辑段边界候选。
- `paragraph.py`：物理段特征、行内 token 和逻辑段落数据。
- `document.py`：整篇文档数据、body 顺序块和规范化审计记录。

旧的 `docxtool.document.importer` 仍 re-export 这些类型，保持现有测试、SDK 和渲染器导入路径兼容。

## 物理导入边界

`src/docxtool/document/importing/reader.py` 负责打开已修复关系的 DOCX、按 body XML
顺序读取段落/表格/分节、保留页眉页脚关系，并保护紧邻表格或纯图片的首条题注。它只返回
旧 importer 已使用的物理块 tuple，不生成逻辑段、不调用候选或状态机；关系修复函数和特征
提取函数仍由兼容 importer 注入，保持现有调用方可替换的边界。

`src/docxtool/document/importing/features.py` 只编排物理段初始 locator、样式名、格式、
图片和编号事实。run 有效格式、source run span、段落对齐与缩进由 `physical_format.py`
读取；Word 原生列表和 Heading 样式前缀由 `numbering.py` 按原顺序应用。二者均只填充
既有 `ParagraphFeatures` 字段，不决定标题层级或最终 `type_id`。

## 逻辑分段边界

`src/docxtool/document/segmentation/` 开始承接物理段到逻辑段的守恒职责：

- `pipeline.py`：把物理块按原顺序展开为旧 importer 使用的逻辑行 tuple，并保留原 `build_logical_span_plan` facade 和 monkeypatch 边界；识别相关回调仍由 importer 注入，该模块不创建最终段落类型。
- `partition.py`：根据源物理段行范围、软换行证据、行内标题正文拆分开关和正文区域状态生成 logical source span 计划，同时决定整段 inline token 是否可原样保留；不创建 `ParagraphData` 或最终类型。
- `conservation.py`：校验拆分范围的可见文字覆盖、顺序、重叠、空洞和越界，保留既有异常文本；`boundaries.py` 和 importer 旧入口只作兼容转发。
- `source_locator.py`：根据源物理段 raw span 写入 UTF-16 locator、canonical locator、段内格式特征，构建逻辑段 `ParagraphFeatures`，并按物理段写入逻辑段序号和总数。旧的 importer 私有函数名仍作为兼容入口转发到该模块。
- `boundaries.py`：根据源范围、冒号结构、编号事实和 run 格式切换生成标题正文边界候选，并提供“标题后粘连正文”共享事实；该模块不修改文本，也不决定最终标题层级。
- `soft_breaks.py`：根据编号、文号、键值段、日期、附件、职务姓名和落款证据，判断软换行是否应形成逻辑段边界；其中职务姓名和文首职务日期组合由本模块提供通用形态判断，不维护具体姓名名单，也不决定最终段落类型。
- `body_tail.py`：根据 importer 注入的附件、成文日期、附件项和附件页标记判断函数，扫描逻辑行中的最后正文候选位置；该模块只提供尾部边界事实，不写入最终类型。

当前 importer 保留兼容 facade 与识别编排；软换行、标题正文粘连和尾部软换行的边界实现已由 segmentation 消费既有回调。后续迁移必须继续保持文字覆盖、不重叠和不丢失。

## 目录

`src/docxtool/document/recognition/` 包含识别层：

- `features.py`：保留原文的块模型和共享特征。表格、图片、空段和分页标记不会被静默丢弃。
- `attachment.py`：提供附件说明、附件续项、附件边界形态事实和附件说明起点许可状态事实；只返回正则匹配或布尔事实，不写最终类型。
- `colon.py`：共享冒号存在判断、冒号标签加粗位置和结构分析，只输出标签、值、称呼形态、机构形态、解释性正文等事实，不直接返回最终类型。
- `document_mode.py`：提供旧 importer scorer 兼容的文种关键词、报告回顾标题、正文小标题、名词解释和称呼候选评分；只返回识别证据，不改变候选分数或最终类型。
- `front_matter.py`：提供旧 importer scorer 兼容的文首标题、续行、日期、署名和职务姓名候选评分；只返回分值事实，不推进标题区状态、不写最终类型。
- `metadata.py`：根据最终类型、段落特征和上下文事实补充旧渲染 meta，例如标题正文粘连、正文引导句加粗、冒号标签和报告首句加粗；不重新打分或改写最终类型。
- `model.py`：`DocumentMode`、`SectionKind`、`ParagraphType` 三层模型。
- `candidates.py`：结构、键值、编号、语义、旧分类器和样式候选提供器。旧分类结果只作为兼容候选。
- `opening_speech.py`：提供文首“在……上的讲话”主标题证据和误推断一级编号剥离 helper；只生成识别证据，不写入最终类型。
- `numbering.py`：提供字面编号、Word 多级列表/标题样式、损坏编号标题、“一是/一要”正文引导句和旧编号标题候选分事实映射；只返回候选类型、编号前缀、位置或分值，不更新上下文状态。
- `selection.py`：构建旧 importer 兼容的骨架层、文种覆盖层和兜底层 scorer registry，并执行三阶段 scorer 选择；只返回候选类型、meta、前缀和得分日志，不执行 Repair 或推进上下文。
- `signature.py`：提供落款单位否定前缀、通用组织后缀、正文尾部上下文和下一段日期组合事实；只判断短行是否像落款单位，不写最终类型。
- `state.py`：提供旧 importer 兼容 Flow 状态允许表、标题层级 Repair、最后结构事实记录和识别上下文推进；只消费最终类型，不重新打分或改写最终类型。
- `tail_structure.py`：承接旧 importer 尾部固定结构状态机，通过回调消费附件、落款、日期和附件页事实，保持旧返回契约并避免反向依赖 importer。
- `global_context.py`：文首结构、正文边界和同级标题族的全文只读分析。
- `decoder.py`：硬结构否决、标题序列冲突复核和宽度可配置的确定性 Beam Search；默认宽度为 12。
- `compatibility.py`：内部段落类型到旧渲染 `type_id` 的唯一映射边界。
- `validators.py`：有限结构序列校验。
- `diagnostics.py`：只输出结构信息，不输出源文档正文、OOXML 或敏感字段。
- `config.py` / `version.py`：集中管理 Beam 宽度、候选上限、诊断开关和引擎/schema 版本。

`src/docxtool/document/normalization/` 位于识别层之后：

- `changes.py`：根据最终段落和调用方传入的规范化前快照生成 `NormalizationChange` 账本；只记录 strict 模式建议和 normalize 模式已应用变化，不修改正文、类型或段落顺序。
- `dates.py`：提供中文数字转换、成文日期形态判断、成文日期规范化和附件页标识规范化。该模块只处理已识别文本的安全显示转换，不决定段落类型。
- `numbering.py`：提供已识别标题编号前缀剥离、旧样式规则行号映射、最终标题编号 meta 分配和跳号修复。该模块只消费 Recognition 已给出的最终 `type_id`、前缀和样式规则，不重新判断标题层级或正文类型。
- `signature.py`：提供已识别落款单位的安全文本规范化，只移除误粘连的中文一级编号前缀，不识别或扩写单位名称。
- `responsibility.py`：提供已识别责任单位行的标签归一和重复标签换行规范化，只处理显示文本，不把正文重新分类为责任单位。
- `text.py`：提供旧 importer 兼容的基础文本清理、中文语境引号转换和半角标点转换。该模块只封装文本转换 helper，不改变处理模式开关。
- `tail.py`：消费最终 `type_id`，整理已确认的附件说明、落款单位、成文日期和附件正文页标记，承接 `sign_org + sign_date + attachment_note` 的尾部窄重排，并同步识别诊断。它不重新生成候选、不重新判定正文或标题，也不改变候选分数。
- `pipeline.py`：仅承接 importer 原有的 Recognition 之后规范化调用顺序，包括尾部整理、编号 meta、同级合并、编号间隙修复、Word 自动编号清理和最终诊断同步。所有具体操作仍由 importer 注入的兼容回调执行，因此不改变私有 monkeypatch 边界、处理模式语义或 Recognition 的先后顺序。

## Phase A-2 Mechanical Boundary

Phase A-2 only changes the placement of document-chain code. `DocxImporter.load()` remains
the compatibility facade and retains the existing order:

```text
physical reader -> logical segmentation -> legacy/core metadata -> Recognition
-> post-recognition normalization -> renderer
```

The importer still owns the legacy/core classification call and the Recognition invocation.
`normalization/pipeline.py` starts only after Recognition returns; it receives every action as
an injected importer callback so it cannot silently acquire authority over candidates, state,
final types, text rewriting or ordering rules.

`scripts/phase_a_equivalence_snapshot.py` observes the existing importer aliases to record
physical blocks, logical lines, pre-Recognition inputs, locator facts, post-chain types,
review diagnostics and the complete exported OPC package manifest. The manifest covers every
part, content type and relationship, and rejects missing internal relationship targets. Snapshot
JSON stores only text length and SHA-256 values. The provider experiment toggles only
`LegacyCandidateProvider` at the decoder boundary; importer Legacy preprocessing remains enabled
in both runs and is explicitly reported as outside that experiment.

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
