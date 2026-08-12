# DocxTool 项目文件架构树

本文按当前工作树说明项目代码文件的职责，供维护者和其他 AI 快速定位实现。
范围包括可发布源码、配置、脚本、文档和测试；不包含 `.venv/`、`var/` 运行数据、
`local_recycle/`、构建产物及 `test_docx/` 中的用户样本和批量输出。

## 一、总体链路

```text
HTTP/CLI/SDK 入口
└─ application 应用编排
   └─ document.importing 读取 DOCX 物理事实
      └─ document.segmentation 划分逻辑片段并核验文字守恒
         └─ document.recognition 生成候选、全文上下文和最终类型
            └─ document.normalization 执行模式允许的规范化
               └─ document.engine 渲染并验证输出 DOCX

SDK 绑定链
RecognitionRequest → RecognitionPlan → HostSnapshot → RecognitionBinding

Web 执行链
Handler → 路由/鉴权 → 任务队列 → worker/子进程 → application → 文档主链
```

## 二、根目录

```text
docxtool/
├─ AGENTS.md                       # AI 与维护者必须遵守的仓库协作、回归和发布规则
├─ README.md                       # 项目功能、安装、启动和主要使用入口
├─ CHANGELOG.md                    # 正式版本及变更记录
├─ WPS_SERVER_PRD.md               # WPS 公网账号、设备、授权和统计产品需求
├─ WPS_SERVER_TECHNICAL_DESIGN.md  # WPS 公网服务与本地客户端技术设计
├─ CONVENTIONS.md                  # 开发、排版边界和人工验证约定
├─ 公文格式规范.md                  # 公文版式与样式配置依据
├─ pyproject.toml                  # Python 包元数据、依赖、入口和 wheel 配置
├─ requirements.txt               # 便捷安装依赖清单
├─ requirements.lock              # Python 3.8 生成的生产依赖哈希锁
├─ requirements-dev.lock          # 测试、检查和构建依赖哈希锁
├─ pytest.ini                     # pytest 搜索路径、源码路径和默认参数
├─ ruff.toml                      # Ruff 规则与排除项
├─ .env.example                   # 无真实密钥的环境变量示例
├─ .gitignore                     # 本地数据、缓存、DOCX 和构建产物忽略规则
├─ .gitattributes                 # 文本换行和二进制文件属性
├─ server.py                      # 兼容服务器入口，转入 docxtool.web.app
├─ run.ps1                        # Windows/Windows 7 可移动启动入口
├─ run.sh                         # Linux 启动入口
├─ deploy/
│  └─ nginx-docxtool.conf         # Nginx 到 127.0.0.1:9527 的反向代理模板
└─ .github/workflows/ci.yml       # GitHub Actions 测试、检查和构建门禁
```

## 三、Python 生产源码

### 3.1 包入口、应用层、认证、安全和存储

```text
src/docxtool/
├─ __init__.py                    # 包入口和公开基础符号
├─ __main__.py                    # `python -m docxtool` Web 启动入口
├─ version.py                     # 运行时版本统一解析
├─ env.py                         # 小型 .env 加载器
├─ paths.py                       # 项目、资源和可移动运行目录定位
├─ application/
│  ├─ __init__.py                 # 应用层包入口
│  └─ process_document.py         # 上传任务编排；串联导入、导出、完整性检查和脱敏结果
├─ auth/
│  ├─ __init__.py                 # 普通用户认证原语包入口
│  ├─ passwords.py                # Argon2id 密码哈希和验证
│  └─ service.py                  # 用户名、密码和身份输入验证
├─ security/
│  ├─ __init__.py                 # 安全辅助包入口
│  ├─ docx_integrity.py           # 生成 DOCX 的 OOXML 包、关系和目标完整性检查
│  ├─ docx_validator.py           # 上传 DOCX 的大小、ZIP、部件和风险检查
│  └─ external_relationships.py   # 外部 OOXML 关系的纯策略判断
└─ storage/
   ├─ __init__.py                 # 存储辅助包入口
   └─ database.py                 # SQLite 路径和连接辅助
```

### 3.2 文档共享模型、分析和物理导入

```text
src/docxtool/document/
├─ __init__.py                    # 文档处理包入口
├─ importer.py                    # 旧公开导入 facade；保留 re-export、patch 点和薄 load 入口
├─ classifier.py                  # 保守的公文段落分类辅助
├─ effective_format.py            # 解析 run、样式继承和主题字体的有效格式
├─ source_tape.py                 # 单物理段落的 raw/canonical 可逆坐标带
├─ style_config.py                # 排版规则、页面设置和日志配置模型
├─ letterhead_config.py           # 托管版头配置验证和归一化
├─ role_shape.py                  # 文首职务与姓名的共享结构形态证据
├─ models/
│  ├─ __init__.py                 # 稳定共享模型导出
│  ├─ document.py                 # 文档级模型和块集合
│  ├─ paragraph.py                # 段落、特征、行内 token 等模型
│  └─ source.py                   # 来源坐标、locator 和片段范围模型
├─ analysis/
│  ├─ __init__.py                 # 跨层只读结构分析入口
│  ├─ document_structure.py       # 文档级标题、正文、尾部结构只读统计
│  └─ letterhead.py               # 首页正文流已有版头的只读检测
└─ importing/
   ├─ __init__.py                 # DOCX 物理导入层入口
   ├─ reader.py                   # 安全打开 DOCX，并按 body XML 顺序读取段落、表格和分节
   ├─ features.py                 # 提取段落文本、样式、对齐、缩进、字号和加粗等物理特征
   ├─ physical_format.py          # 提取 run 与段落的直接格式快照
   ├─ inline_tokens.py            # 提取文本、制表符、软换行和分页符 token
   ├─ numbering.py                # 提取文本编号、Word 列表和标题样式编号事实
   ├─ images.py                   # 判断可见图片、纯图片段和表图题注事实
   ├─ relationships.py            # 在临时副本中修复 `../NULL` 等损坏关系
   └─ sections.py                 # 读取分节、页眉页脚及其关系事实
```

### 3.3 逻辑分段和导入主链

```text
src/docxtool/document/
├─ segmentation/
│  ├─ __init__.py                 # 物理段到逻辑段的分段入口
│  ├─ source_locator.py           # 定位子片段并映射段内格式
│  ├─ boundaries.py               # 标题、正文、称呼、日期、附件和落款边界判断
│  ├─ soft_breaks.py              # Word 软换行是否形成独立结构的决策
│  ├─ body_tail.py                # 正文与文尾结构边界辅助
│  ├─ partition.py                # 将来源范围保序划分为逻辑片段
│  ├─ conservation.py             # 核验范围无重叠、无丢失、无重复
│  └─ pipeline.py                 # 组织分段规划并生成逻辑来源范围
└─ pipeline/
   ├─ __init__.py                 # 导入主链公开入口
   ├─ options.py                  # strict、structural、normalize 及文字/token 策略构建
   ├─ paragraph_materialization.py # 将物理流项目机械转换为 ParagraphData
   └─ document_pipeline.py        # 按顺序串联导入、分段、识别和规范化
```

### 3.4 Recognition 识别层

```text
src/docxtool/document/recognition/
├─ __init__.py                    # 稳定识别层公开入口
├─ model.py                       # 候选、结果、复核项和类型词汇模型
├─ config.py                      # 集中的识别阈值与调优常量
├─ version.py                     # 识别引擎和诊断协议版本
├─ features.py                    # 所有候选提供器共用的只读特征提取
├─ validators.py                  # 无副作用的有限结构校验器
├─ diagnostics.py                # 脱敏识别诊断序列化
├─ compatibility.py              # Recognition 到旧渲染类型的唯一兼容边界
├─ core_adapter.py               # ParagraphData 到 Core 分类器输入的适配器
├─ candidates.py                 # 候选提供器旧路径兼容 facade
├─ global_context.py             # 全文上下文旧路径兼容 facade
├─ decoder.py                    # Beam 解码器旧路径兼容 facade
├─ colon.py                      # 分段、识别和渲染共享的语义冒号证据
├─ numbering.py                  # 文本/Word 编号事实到标题候选的映射
├─ attachment.py                 # 附件说明和附件项形态证据
├─ signature.py                  # 落款单位通用结构形态证据
├─ opening_speech.py             # “在……上的讲话”等文首标题证据
├─ front_matter.py               # 文首标题、职务姓名、日期等元数据证据
├─ document_mode.py              # 文种和报告标题的旧链兼容证据
├─ metadata.py                   # 旧链兼容识别元数据补充
├─ selection.py                  # 旧 scorer 选择和结果兼容
├─ state.py                      # 旧导入链上下文状态约束
├─ tail_structure.py             # 旧链文尾附件、落款和日期状态机
├─ providers/
│  ├─ __init__.py                # 按稳定顺序注册内置候选提供器
│  ├─ base.py                    # 候选模型和提供器共用函数
│  ├─ compatibility.py           # Core、样式和 Legacy 兼容候选
│  ├─ key_value.py               # 键值段、字段标签和责任单位候选
│  ├─ numbering.py               # 显式一至四级编号候选
│  ├─ semantic.py                # 语义及文首结构候选
│  └─ structural.py              # 图片、表格、附件、落款等结构候选
├─ context/
│  ├─ __init__.py                # 全文上下文分析入口
│  ├─ model.py                   # 全文上下文只读模型
│  ├─ analyzer.py                # 汇总标题、编号、文首和文尾全文证据
│  ├─ front.py                   # 文首标题、职务姓名、日期和称呼证据
│  ├─ numbering.py               # 标题家族及同级序号作用域分析
│  └─ tail.py                    # 附件、落款和日期的全文尾部证据
├─ decoding/
│  ├─ __init__.py                # Beam 解码实现包入口
│  ├─ model.py                   # Beam 路径、状态和内部结果模型
│  ├─ candidate_selection.py     # 收集候选并执行确定性本地排序
│  ├─ transitions.py             # 状态转移加分、冲突和 hard veto
│  ├─ review.py                  # 根据最终候选生成 review/diagnostics
│  └─ pipeline.py                # 全文 Beam Search 和最终类型裁决
└─ legacy/
   ├─ __init__.py                # 旧识别链兼容入口
   ├─ scoring.py                 # ScoreDetail、ScoreBoard 和 DetectionContext 模型
   ├─ classifier.py              # Legacy 单段分类编排
   └─ pipeline.py                # Legacy 段落流上下文推进
```

### 3.5 Recognition 后规范化

```text
src/docxtool/document/normalization/
├─ __init__.py                    # 识别后规范化公开入口
├─ pipeline.py                    # 按处理模式组织规范化步骤
├─ changes.py                     # 生成已应用或建议变更账本
├─ text.py                        # 通用文本清理辅助
├─ dates.py                       # 成文日期和附件页标记规范化
├─ numbering.py                   # 识别后标题前缀剥离和序号重建
├─ responsibility.py             # 责任单位、联系人等键值文本规范化
├─ signature.py                  # 落款单位和日期文本规范化
└─ tail.py                        # 整理附件说明、落款、日期和附件正文页顺序
```

### 3.6 DOCX 渲染引擎

```text
src/docxtool/document/engine/
├─ __init__.py                    # `export_doc` 等公开引擎入口
├─ core.py                        # 旧公开兼容 facade 和必要 patch 点
├─ export_pipeline.py             # 全文导出薄编排
├─ render_context.py              # 单次导出共享可变状态
├─ paragraph_renderer.py          # 按原顺序渲染普通段落和受保护对象
├─ special_items.py               # 渲染表格、图片、题注等特殊对象
├─ export_finalize.py             # 页结构收尾、完整性检查、统计和保存
├─ render_types.py                # 识别类型到渲染类型和流分组映射
├─ render_options.py              # 功能开关和渲染选项解析
├─ render_text.py                 # 渲染使用的小型文本辅助
├─ normal.py                      # 通用公文样式解析与应用
├─ style_catalog.py               # 输出 DOCX 的 DCT 结构样式目录
├─ paragraph_styles.py            # 段落 style id 和样式不变量
├─ paragraph_format.py            # 对齐、缩进、间距和行距应用
├─ typography.py                  # 字体、数字西文字体和上标后处理
├─ inline.py                      # run 写入和源 run 样式复制
├─ inline_effects.py              # 冒号、引导句、特殊字段等行内效果
├─ heading_body_split.py          # 标题与行内正文拆分后的成对渲染核验
├─ numbering.py                   # 编号文本检测与保守规范化兼容函数
├─ render_numbering.py            # 根据最终类型写入标题序号
├─ punctuation.py                 # 中立标点函数的旧 Engine 兼容 facade
├─ punctuation_docx.py            # 保持 run 结构的 DOCX 标点替换
├─ document_structure.py          # 中立文档结构分析的旧 Engine facade
├─ context_candidate.py           # 基于导入事实生成独立局部上下文候选
├─ structure_context.py           # 将局部候选与文档块结构协调
├─ letterhead.py                  # 托管版头渲染及旧检测路径兼容
├─ header_footer.py               # 页眉页脚兼容辅助
├─ page_number.py                 # 页码域和奇偶页外侧页码写入
├─ sections.py                    # 分节尺寸、横向边距、网格和页眉页脚关系
├─ signature_block.py             # 落款单位和成文日期版式
├─ preservation.py               # 复制受保护 OOXML、样式和关系部件
├─ table.py                       # 显式启用时的安全表格格式辅助
└─ cleanup.py                     # 显式启用时清理异常 run 直接格式
```

### 3.7 中立文本工具

```text
src/docxtool/document/text/
├─ __init__.py                    # 跨导入和渲染层的中立文本工具入口
└─ punctuation.py                # 保护 URL、时间、编号等范围的安全中文标点规范化
```

## 四、SDK 与协议资源

```text
src/docxtool/sdk/
├─ __init__.py                    # `docxtool.sdk` 稳定公开导入面
├─ constants.py                   # 协议版本、坐标编码、状态和能力常量
├─ models.py                      # JSON 安全的公开请求、计划、快照和绑定模型
├─ validation.py                  # Schema 加载、字段检查和跨字段语义验证
├─ errors.py                      # 稳定错误码、脱敏异常和 JSON 错误体
├─ manifest.py                    # SDK manifest 与能力/版本协商
├─ recognition.py                 # DOCX 识别主链到 RecognitionPlan 的公开 facade
├─ binding.py                     # RecognitionPlan 与宿主文本快照的安全绑定
└─ cli.py                         # manifest、recognize、bind、validate、summary CLI

src/docxtool/resources/
├─ __init__.py                    # 包内资源定位入口
├─ config/
│  └─ default-format.json         # 默认公文样式、页面和功能配置
└─ schemas/
   ├─ __init__.py                 # JSON Schema 包资源入口
   ├─ sdk-manifest-v1.schema.json # SDK 能力清单 Schema
   ├─ recognition-request-v1.schema.json # 识别请求 Schema
   ├─ recognition-plan-v1.schema.json    # 脱敏识别计划 Schema
   ├─ host-snapshot-v1.schema.json       # 宿主完整文本快照 Schema
   ├─ host-snapshot-summary-v1.schema.json # 无正文快照摘要 Schema
   ├─ recognition-binding-v1.schema.json # 安全绑定结果 Schema
   ├─ validation-report-v1.schema.json   # 校验问题报告 Schema
   └─ sdk-error-v1.schema.json           # 统一 SDK 错误 envelope Schema
```

## 五、Web 服务

`web.app` 是 composition root 和旧兼容入口；其余文件按单一职责拆分。HTTP、数据库、
队列和文档处理通过显式回调或共享 runtime state 连接，业务模块不反向依赖 `web.app`。

```text
src/docxtool/web/
├─ __init__.py                    # Web 包入口
├─ app.py                         # 兼容 composition root；装配配置、状态、Handler 和公开旧符号
├─ bootstrap.py                   # import-time 环境、路径和默认值装配
├─ runtime_state.py               # 锁、队列、缓存等进程内共享状态工厂
├─ hooks.py                       # 延迟注册/读取 app provider，保持独立导入和 monkeypatch
├─ compatibility.py               # 动态同步 app namespace 的旧函数 facade
├─ handler.py                     # BaseHTTPRequestHandler 实现
├─ handler_lifecycle.py           # OPTIONS、方法入口和生命周期分派
├─ handler_dispatch.py            # 路由动作到 Handler 方法的分派
├─ handler_responses.py           # Handler 文本、JSON、跳转和错误响应写入
├─ routing.py                     # 纯路由匹配和资源 ID 提取
├─ route_authorization.py         # 路由鉴权结果和兼容上下文处理
├─ protected_route_handlers.py    # 对需鉴权路由执行统一转发
├─ request_utils.py               # 路径、Cookie、CSRF、JSON 和 HTML 小工具
├─ request_params.py              # 合并 query、JSON body 和表单参数
├─ responses.py                   # 纯响应编码、响应头和错误体构建
├─ stream_io.py                   # 有界读取上传流和文件下载流
├─ config.py                      # Web 环境变量、CORS 和 Cookie 安全配置解析
├─ secrets.py                     # 管理员/代理密钥加载和弱密钥检查
├─ client_ip.py                   # 可信代理、客户端 IP 和常量时间密钥比较
├─ server_runtime.py              # HTTP 服务启动、日志和关闭编排
├─ time_check.py                  # 启动时区和网络时间提示
├─ health.py                      # health、readiness、version 和启动 URL payload
├─ health_route_handlers.py       # 健康检查相关 HTTP 响应
├─ frontend_pages.py              # 打包前端页面资源定位和读取
├─ page_route_handlers.py         # 首页和管理员登录页响应
├─ file_utils.py                  # 安全文件名、下载头和诊断文本
├─ file_api_auth.py               # 文件 API 的代理密钥和本机授权
├─ format_request.py              # 上传格式配置、处理模式和功能开关解析
├─ upload_route_handlers.py       # 上传限流、落盘、校验、复杂度检查和入队
├─ task_paths.py                  # 上传、输出和日志路径及半成品清理
├─ task_queue.py                  # 写 queued 记录后加入内存队列
├─ task_worker.py                 # worker 启动、消费、子进程执行和超时边界
├─ task_state.py                  # 公开任务状态、队列位置和识别摘要
├─ task_cache.py                  # 内存任务缓存容量裁剪
├─ task_records.py                # queued、processing 和终态数据库记录
├─ task_result.py                 # 终态结果、统计、内存状态和失败清理收口
├─ task_recovery.py               # 启动时把遗留非终态任务标记为 interrupted
├─ task_statistics.py             # 任务统计、日汇总和监控聚合查询
├─ task_route_handlers.py         # 状态、下载和日志 HTTP 路由
├─ database_schema.py             # Web SQLite 建表、补列、索引和默认模板 seed
├─ maintenance.py                 # 永久保留策略下的兼容维护线程
├─ log_redaction.py               # 管理页面展示前的日志脱敏
├─ rate_limits.py                 # IP 限流、封禁、认证限制和上传配额
├─ anonymous_identity.py          # 匿名 owner Cookie 签名、解析和 Origin 校验
├─ owner_migration.py             # 登录后迁移匿名 owner 的任务与私人模板
├─ auth_payloads.py               # 普通用户认证响应体和 Cookie 头
├─ auth_route_handlers.py         # 注册、登录、退出和 `/auth/me` 路由
├─ user_auth.py                   # 用户 session、principal、Cookie 和 CSRF
├─ admin_access.py                # 管理员请求上下文和 POST CSRF 检查
├─ admin_actions.py               # 管理员封禁、IP 查询和配额表单参数
├─ admin_auth.py                  # 管理员 session、旧 token 和 CSRF 原语
├─ admin_forms.py                 # 管理员登录表单解析
├─ admin_pages.py                 # 管理员登录页 HTML
├─ admin_session_routes.py        # 管理员登录、退出和 session 路由
├─ admin_route_handlers.py        # 管理员监控动作路由
├─ monitoring.py                 # 监控 query、分页和 URL 纯辅助
├─ monitoring_pages.py           # 统计、IP 和任务日志局部 HTML
├─ monitor_dashboard_page.py      # 监控仪表盘整页 HTML
├─ monitor_route_handlers.py      # 监控首页和统计 JSON 路由
├─ admin_workspace_page.py        # 网页业务与 WPS 用户的统一管理员工作台页面
├─ preset_config.py               # 预设模板 ID、名称和格式配置校验
├─ preset_defaults.py             # 官方默认模板和功能开关 seed
├─ preset_store.py                # 预设模板 SQLite CRUD
└─ preset_route_handlers.py       # 预设模板列表、创建、修改和删除路由
```

## 六、WPS 插件与公网服务

```text
src/docxtool/wps_server/
├─ __init__.py                    # WPS 公网服务包入口
├─ config.py                      # 7 天会话、心跳、受控命令和数据库路径配置
├─ database.py                    # 独立 wps_plugin.db 的四张核心表和连接初始化
├─ validation.py                  # 账号、密码、设备、请求编号和结果字段校验
├─ auth.py                        # 会话哈希、设备指纹和 Bearer 会话认证
├─ format_config.py               # 当前服务器排版配置和配置版本加载
├─ service.py                     # 注册、双槽 Argon2 登录、心跳、排版授权和结果回传事务
├─ route_handlers.py              # /wps-api/v1 JSON HTTP 边界
├─ admin.py                       # WPS 用户、设备和排版请求管理查询
└─ admin_routes.py                # WPS 管理页面和启停动作路由

apps/wps/
├─ main.py                        # 源码和冻结 EXE 的独立启动入口
├─ account_store.py               # %LOCALAPPDATA% 本地账号库和 Windows DPAPI 加密
├─ account_runtime.py             # 运行期会话刷新、10 分钟心跳、授权和结果回传
├─ public_api.py                  # 严格 HTTPS WPS 公网 JSON 客户端
├─ login_window.py                # PySide2 Qt Widgets 登录注册窗口与认证线程
├─ desktop_runtime.py              # 系统托盘、单实例和桌面生命周期
├─ windows_startup.py              # 当前用户 Windows 登录启动项
├─ client-config.json             # 源码开发服务器 Origin；生产构建时替换
├─ DocxToolWps.spec               # PyInstaller 控制台单文件构建规格
├─ requirements-build.txt         # Python 3.8 兼容的固定 PyInstaller 版本
├─ host-runtime.js                # WPS Host 主线程、长请求命令和文档操作
├─ taskpane.html / taskpane.js    # 侧边栏界面、账号状态和命令提交
├─ control/                       # 本机 Control、HostBridge、识别、排版和事务
├─ js/ / images/                  # Ribbon bootstrap 脚本和图标资源
├─ scripts/build-exe.ps1          # 注入 HTTPS Origin、构建并在仓库外验证 EXE
└─ scripts/verify.ps1             # WPS 源码门禁
```

## 七、前端资源

```text
resources/frontend/pages/
├─ index.html                     # 单页 Web 前端，包含上传、配置、任务状态和管理界面
└─ _worker.js                     # Cloudflare Pages Functions/API 代理和静态资源回退
```

## 八、维护脚本

```text
scripts/
├─ analyze_end_format.py          # 分析批量排版结果的文尾格式和结构问题
├─ analyze_letterhead_batch.py    # 批量调查已有版头检测结果
├─ batch_test_docx.py             # 运行标准集/专项集、模板比较、结构审计和视觉抽查
├─ benchmark_recognition.py       # 识别性能基准测试
├─ compare_recognition_runs.py    # 对比两个识别运行的结构和诊断差异
├─ check_public_metadata.py       # 检查公开清单/报告是否泄漏文件名、路径或源哈希
├─ generate_005_format_fixtures.py # 生成脱敏 005 格式扰动测试夹具
├─ generate_secrets.py            # 生成本地部署密钥，不把密钥写入仓库
├─ generate_wps_validation_fixtures.py # 生成 WPS 人工验收脱敏夹具
├─ migrate_legacy_database.ps1    # 迁移旧版 SQLite 数据库
├─ normalize_correct_template_role_spacing.py # 一次性规范正确模板职务姓名间距
├─ phase_a_equivalence_snapshot.py # 生成导入、识别、包部件等机械迁移等价快照
├─ phase_a_web_contract_snapshot.py # 生成 Web 路由与响应契约快照
└─ publish_to_github.ps1          # 在临时干净克隆中按白名单校验、提交并推送
```

## 九、项目文档

```text
docs/
├─ README.md                      # 文档导航和唯一职责索引
├─ PROJECT_FILE_TREE.md           # 本文件；当前项目逐文件中文架构树
├─ ARCHITECTURE_DAG.md            # Web 任务链和 SDK 宿主绑定 DAG
├─ RECOGNITION_ARCHITECTURE.md    # 导入、分段、识别、规范化和渲染边界
├─ DOCX_REGRESSION_CHECKLIST.md   # 已确认公文问题及必须执行的回归项
├─ RECOGNITION_RELEASE.md         # 识别发布门禁、快照、回滚和 wheel 验证
├─ API.md                         # HTTP API、鉴权、错误和前端接入
├─ DEPLOY.md                      # 服务部署、环境变量、Nginx 和检查步骤
├─ SDK.md                         # wheel/SDK 安装、Python API、CLI 和隐私默认值
├─ INTEGRATION_CONTRACT_V1.md     # 宿主无关 SDK JSON 协议
├─ RECOGNITION_SOURCE_LOCATORS.md # UTF-16 来源定位和安全绑定规则
├─ HOST_ADAPTER_GUIDE.md          # WPS、Office.js、VSTO 宿主适配职责和伪代码
├─ HOST_TEXT_V1_GOLDEN.json       # 脱敏 host-text-v1 金标
├─ USER_WPS_VALIDATION.md         # WPS 人工验收步骤
├─ USER_WPS_VALIDATION_RESULT.md  # WPS 人工验收记录模板
├─ UPLOAD_MANIFEST.md             # GitHub 发布文件清单和职责
├─ GITHUB_UPLOAD_GUIDE.md         # 快速/完整发布流程和禁止上传内容
├─ examples/
│  └─ sdk-contract-examples.md    # 脱敏 SDK 请求、计划、绑定和异常示例
└─ migration/
   ├─ README.md                   # 迁移文档目录入口
   ├─ codex-workflow.md           # 机械迁移快速、模块和里程碑门禁
   ├─ phase-a2-checklist.md       # Phase A-2 完成项和文件位置
   ├─ phase-a2-looper-log.md      # Phase A-2 微批次验证记录
   ├─ phase-a3-final-looper-log.md # Phase A-3 收口记录
   ├─ phase-b0-manifest.json      # Phase B-0 脱敏可复现基线
   └─ phase-b0-report.md          # Phase B-0 Finding 与差异聚类报告
```

## 十、测试文件

测试文件遵循 `test_<被测职责>.py` 命名。下面逐文件列出验证对象；测试夹具均应脱敏，
真实 DOCX 与生成结果不属于 GitHub 发布范围。

### 10.1 项目、应用、安全和存储

```text
tests/
├─ test_application_process_document.py # 应用层任务编排、导出器兼容和异常传播
├─ test_architecture_docs.py       # 架构文档存在性和禁止反向依赖
├─ test_audit_hardening.py         # ZIP、路径、错误脱敏和安全审计边界
├─ test_database.py                # 基础 SQLite 数据库行为
├─ test_database_storage.py        # 数据库路径和存储辅助
├─ test_docx_integrity.py          # 生成 DOCX 包和关系完整性
├─ test_entrypoint.py              # 包和服务器入口
├─ test_env_loader.py              # `.env` 加载行为
├─ test_packaging.py               # Python 包和 wheel 资源配置
├─ test_pages_proxy_packaging.py   # Cloudflare Pages 代理资源打包
├─ test_paths.py                   # 可移动路径和项目外启动
├─ test_public_metadata_scan.py    # 公开迁移清单和报告脱敏
├─ test_resources.py               # 默认配置和 Schema 包资源
└─ test_version_consistency.py     # pyproject、运行时和文档版本一致性
```

### 10.2 导入、分段、识别和规范化

```text
tests/
├─ test_document_models.py         # 文档、段落和来源共享模型
├─ test_document_importing_helpers.py # 物理导入小型辅助
├─ test_effective_format.py        # Word 样式继承和有效格式
├─ test_importer_broken_relationships.py # `../NULL` 损坏关系修复
├─ test_importer_facade.py         # importer 旧导入、对象身份和 patch 兼容
├─ test_importer_heading_flow.py   # 标题、正文和编号导入流程
├─ test_importing_features.py      # 段落物理特征和兼容转发
├─ test_importing_reader.py        # body 块、表格、图片和分节读取
├─ test_segment_boundaries.py      # 标题正文、称呼、附件和落款分段边界
├─ test_segmentation_pipeline.py   # 物理段到逻辑段的整体规划
├─ test_segmentation_soft_breaks.py # 软换行强结构判断
├─ test_segmentation_source_locator.py # 子范围、UTF-16 和格式映射
├─ test_document_classifier.py     # 基础段落分类
├─ test_document_structure.py      # 全文只读结构分析
├─ test_colon_structure.py         # 数字冒号、语义冒号和标签范围
├─ test_numbered_bold_detection.py # 编号引导句加粗识别
├─ test_recognition_attachment.py  # 附件说明和附件项候选
├─ test_recognition_decoder.py     # 候选、Beam、硬约束、review 和最终类型
├─ test_recognition_document_mode.py # 文种和报告标题证据
├─ test_recognition_front_matter.py # 文首标题、职务姓名和日期证据
├─ test_recognition_legacy_scoring.py # Legacy scorer 分数和兼容模型
├─ test_recognition_metadata.py    # 识别元数据补充
├─ test_recognition_module_facades.py # candidates/context/decoder 旧路径兼容
├─ test_recognition_numbering.py   # 标题编号候选和冲突复核
├─ test_recognition_opening_speech.py # 讲话类主标题识别
├─ test_recognition_selection.py   # 旧 scorer 选择
├─ test_recognition_signature.py   # 落款单位通用形态证据
├─ test_recognition_state.py       # 旧链状态流约束
├─ test_recognition_tail_structure.py # 文尾结构状态机
├─ test_report_heading_keywords.py # 报告类标题形态反例
├─ test_normalization_changes.py   # 规范化变更账本
├─ test_normalization_dates.py     # 日期规范化
├─ test_normalization_numbering.py # 标题编号重建
├─ test_normalization_pipeline.py  # 规范化步骤顺序和模式
├─ test_normalization_responsibility.py # 责任单位等键值文本
├─ test_normalization_signature.py # 落款文本规范化
└─ test_normalization_text.py      # 通用文本清理
```

### 10.3 渲染、格式和 DOCX 结构

```text
tests/
├─ test_body_order_export.py       # 正文、附件、落款、日期和对象输出顺序
├─ test_cleanup_engine.py          # 可选直接格式清理
├─ test_config_driven_styles.py    # 配置驱动字体、加粗和间距
├─ test_context_candidate.py       # 局部结构上下文候选
├─ test_core_feature_integration.py # 文档主链与引擎集成
├─ test_engine_core_facade.py      # core 旧入口和新 pipeline 对象身份
├─ test_engine_header_footer.py    # 页眉页脚辅助
├─ test_engine_heading_body_split.py # 标题与正文成对渲染核验
├─ test_engine_heading_spacing.py  # 标题、称呼、职务姓名和正文间距
├─ test_engine_inline.py           # run 写入和样式复制
├─ test_engine_inline_effects.py   # 冒号、引导句和段内加粗范围
├─ test_engine_paragraph_format.py # 对齐、缩进、间距和行距
├─ test_engine_paragraph_styles.py # DCT 样式绑定和不变量
├─ test_engine_preservation.py     # 表格、图片、题注和关系迁移
├─ test_engine_render_numbering.py # 渲染期标题序号
├─ test_engine_render_options.py   # 渲染功能选项解析
├─ test_engine_render_text.py      # 渲染文本小工具
├─ test_engine_render_types.py     # 类型映射和流分组
├─ test_engine_sections.py         # 分节页面和关系
├─ test_engine_typography.py       # 字体、数字和上标处理
├─ test_letterhead_config.py       # 版头配置校验
├─ test_letterhead_engine.py       # 版头检测、生成和开关语义
├─ test_numbering_engine.py        # 编号文本辅助
├─ test_page_number_engine.py      # 页码域和奇偶页页脚
├─ test_processing_flags.py        # strict/structural/normalize 和功能开关
├─ test_punctuation_docx.py        # 保持 run 的 DOCX 标点处理
├─ test_punctuation_engine.py      # 中立安全标点规则
├─ test_responsibility_export.py   # 键值段落样式与加粗范围
├─ test_section_header_footer.py   # 多分节页眉页脚关系完整性
├─ test_signature_attachment_detection.py # 同段落款日期及附件边界
├─ test_signature_block_engine.py  # 落款块版式
├─ test_signature_detection.py     # 落款、日期和附件识别顺序
├─ test_structural_styles.py       # 输出结构样式目录
├─ test_structure_context.py       # 文档结构上下文协调
├─ test_structured_layout_quality.py # 页面、网格、字号和段落质量
├─ test_style_config_features.py   # 样式配置功能开关
└─ test_table_engine.py            # 表格格式安全边界
```

### 10.4 SDK 与宿主协议

```text
tests/
├─ test_host_text_contract_golden.py # host-text-v1 金标和坐标契约
├─ test_sdk.py                     # 识别 SDK 最小调用和隐私默认值
├─ test_sdk_binding.py             # locator、状态、前置条件和稳定 binding_id
└─ test_sdk_contract_v1.py         # 模型、Schema、严格校验、CLI 和错误码
```

### 10.5 Web、任务和服务器

```text
tests/
├─ test_server_client_ip.py        # 服务器入口客户端 IP 兼容
├─ test_server_ip_admin.py         # 管理员 IP 操作兼容
├─ test_server_presets_api.py      # 预设模板 API 集成
├─ test_server_production_controls.py # 生产模式、密钥、Cookie 和 CORS
├─ test_server_spawn_regression.py # Windows spawn 子进程回归
├─ test_server_task_logging.py     # 服务器任务日志记录
├─ test_server_upload_security.py  # 上传接口安全边界
├─ test_user_auth.py               # 普通用户认证基础服务
├─ test_web_admin_access.py        # 管理员上下文和 CSRF
├─ test_web_admin_actions.py       # 管理员动作参数
├─ test_web_admin_auth.py          # 管理员 session 和旧 token
├─ test_web_admin_forms.py         # 管理员登录表单
├─ test_web_admin_pages.py         # 管理员静态页面
├─ test_web_admin_route_handlers.py # 管理员动作路由
├─ test_web_admin_session_routes.py # 管理员 session 路由
├─ test_web_anonymous_identity.py  # 匿名 owner Cookie
├─ test_web_app_facade.py          # app/handler/compatibility 独立导入与 monkeypatch
├─ test_web_auth_payloads.py       # 用户认证响应体
├─ test_web_auth_route_handlers.py # 普通用户认证路由
├─ test_web_client_ip.py           # 可信代理和客户端 IP
├─ test_web_config.py              # Web 环境和 CORS 配置
├─ test_web_database_schema.py     # SQLite 建表和迁移
├─ test_web_file_api_auth.py       # 文件 API 授权
├─ test_web_file_utils.py          # 文件名、下载头和诊断脱敏
├─ test_web_format_request.py      # 上传格式配置解析
├─ test_web_frontend_pages.py      # 前端页面资源读取
├─ test_web_handler_dispatch.py    # Handler 路由分派
├─ test_web_handler_lifecycle.py   # Handler 方法和生命周期
├─ test_web_handler_responses.py   # Handler 响应写入
├─ test_web_health.py              # 健康状态 payload
├─ test_web_health_route_handlers.py # 健康检查路由
├─ test_web_log_redaction.py       # 日志脱敏
├─ test_web_maintenance.py         # 永久保留维护线程
├─ test_web_monitor_dashboard_page.py # 监控整页 HTML
├─ test_web_monitor_route_handlers.py # 监控路由
├─ test_web_monitoring.py          # 监控查询和分页
├─ test_web_monitoring_pages.py    # 监控局部 HTML
├─ test_web_owner_migration.py     # 匿名资源迁移
├─ test_web_page_route_handlers.py # 首页和登录页路由
├─ test_web_preset_config.py       # 预设模板配置校验
├─ test_web_preset_defaults.py     # 默认模板 seed
├─ test_web_preset_route_handlers.py # 预设模板 API 路由
├─ test_web_preset_store.py        # 预设模板 SQLite CRUD
├─ test_web_protected_route_handlers.py # 受保护路由转发
├─ test_web_rate_limits.py         # 限流、封禁和上传配额
├─ test_web_request_params.py      # query/body 参数合并
├─ test_web_request_utils.py       # HTTP 请求小工具
├─ test_web_responses.py           # 纯响应编码和错误体
├─ test_web_route_authorization.py # 路由鉴权响应
├─ test_web_routing.py             # 路由匹配
├─ test_web_secrets.py             # 密钥加载和生产校验
├─ test_web_server_runtime.py      # HTTP 服务启动编排
├─ test_web_stream_io.py           # 上传/下载流边界
├─ test_web_task_cache.py          # 内存任务缓存
├─ test_web_task_paths.py          # 任务路径和清理策略
├─ test_web_task_queue.py          # queued 记录与入队顺序
├─ test_web_task_records.py        # 任务数据库状态记录
├─ test_web_task_recovery.py       # 启动恢复中断状态
├─ test_web_task_result.py         # 终态结果同步
├─ test_web_task_route_handlers.py # 状态、下载和日志路由
├─ test_web_task_state.py          # 公开任务状态
├─ test_web_task_statistics.py     # 任务统计
├─ test_web_task_worker.py         # worker、子进程和超时
├─ test_web_time_check.py          # 启动时间提示
├─ test_web_upload_route_handlers.py # 上传路由编排
├─ test_web_user_auth.py           # 用户 session、Cookie 和 CSRF
├─ test_web_admin_workspace.py     # 统一管理员工作台和 WPS 页面渲染
├─ test_wps_server_admin.py        # WPS 用户、设备和请求管理查询
├─ test_wps_server_auth.py         # 注册、登录、7 天会话、Argon2 并发和心跳
├─ test_wps_server_database.py     # WPS 独立四表数据库结构
├─ test_wps_server_format_requests.py # 排版授权幂等和结果终态
├─ test_wps_server_http_flow.py    # 真实 HTTP 注册到后台统计闭环
└─ test_wps_server_routes.py       # WPS 公网路由显式映射
```

### 10.6 批量回归、迁移快照和 Node

```text
tests/
├─ test_batch_test_docx.py         # 模板对齐、严重度、抽样和视觉报告
├─ test_phase_a_equivalence_snapshot.py # 机械迁移快照字段和脱敏
├─ frontend-format-config.test.mjs # 浏览器端格式配置与功能开关
└─ worker-routing.test.mjs         # Cloudflare Worker 路由、方法和敏感头转发
```

## 十一、维护时如何定位

```text
识别错了        → importing → segmentation → recognition → normalization
格式写错了      → engine/style_catalog、paragraph_format、typography、inline_effects
分页或对象丢失  → engine/sections、preservation、header_footer、security/docx_integrity
Web 请求错了    → web/routing → 对应 *_route_handlers → task/application
SDK 绑定错了    → sdk/validation → sdk/recognition → sdk/binding
发布漏文件      → docs/UPLOAD_MANIFEST.md → scripts/publish_to_github.ps1
```

兼容 facade（`document/importer.py`、`recognition/candidates.py`、
`recognition/global_context.py`、`recognition/decoder.py`、`engine/core.py`、
`web/app.py`）保留旧导入或 monkeypatch 路径，但不应重新放入第二套业务实现。
