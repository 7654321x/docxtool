# Phase A-3 Final Looper 日志

状态：`completed`。本文只保留 Phase A-3 和 Phase A 最终门禁的脱敏历史记录。

## 职责

本日志只记录 Phase A-3 剩余 Web 收口、Engine 评估或拆分，以及 Phase A 最终门禁。
Importer、Recognition 和更早 Phase A-2 迁移事实继续以
`phase-a2-checklist.md`、`phase-a2-looper-log.md` 为准，不在此重复维护。

## 开始基线

- 本地分支：`main`，开始提交 `fe0667313ee43791f2846b8574a969b6d07bec8b`。
- 工作树开始前已包含 Phase A-2、Importer 收口和 Recognition 拆分修改；全部原样保护。
- Module 1 Importer：passed。
- Module 2 Recognition：passed，固定 6 份脱敏样本、3 种模式共 18 个案例差异为 0。
- 本轮不执行 pull、fetch、merge、rebase、reset、checkout、switch、clean、commit 或 push。

## Checkpoint

### Web

状态：passed

#### Loop W1：bootstrap 和 import-time 配置

- 原位置：`web/app.py` 的路径、目录创建、环境变量、版本、Cookie/secret 相关配置和限制参数装配。
- 新位置：`web/bootstrap.py`；`app.py` 在原调用位置装配并继续暴露旧全局名。
- 兼容入口：`web.app` 的配置常量、`_load_secret`、`parse_frontend_origin`、`resolve_cookie_secure` 等旧符号保留。
- 快速门禁：路径、配置、health、secret、生产控制和启动测试 `71 passed`；Ruff、compileall、`git diff --check` 通过。
- 契约快照：路由、HTTP status/header/body shape、HTML hash、配置、目录副作用和 runtime shape 差异为 0。
- 状态：passed。

#### Loop W2：runtime state

- 原位置：`web/app.py` 的 SQL 锁、限流、任务、队列和 worker 共享对象。
- 新位置：`web/runtime_state.py` 工厂；每次 app import 仍只创建一组对象。
- 兼容入口：`web.app` 原锁、容器和状态全局名继续引用同一对象。
- 快速门禁：runtime、限流、任务队列、worker、生产控制和启动测试通过；对象身份断言通过。
- 契约快照：queue/task shape、HTTP 与 import-time 路径副作用差异为 0。
- 状态：passed。

#### Loop W3：旧函数 compatibility facade

- 原位置：`web/app.py` 中 120 个数据库、任务、鉴权、preset、health、monitor 和路径兼容转发函数。
- 新位置：`web/compatibility.py`；每次调用动态读取 `web.app` 旧命名空间。
- 兼容入口：全部旧函数从 `web.app` 显式 re-export，旧路径 monkeypatch 继续命中真实执行。
- 快速门禁：兼容调用、生产控制、IP 管理、preset、任务日志、上传安全、用户鉴权和审计测试 `145 passed`；HTTP 契约差异为 0。
- 状态：passed。

#### Loop W4：Handler

- 原位置：`web/app.py::Handler`。
- 新位置：`web/handler.py::Handler`。
- 兼容入口：`from docxtool.web.app import Handler` 保留；每个方法入口同步读取 app hook。
- 快速门禁：Handler、路由、生命周期、响应、生产控制、preset、上传安全和用户鉴权测试 `94 passed`；HTTP 契约差异为 0。
- 状态：passed。

#### Loop W5：main/server 入口

- 调查结论：`main()` 已只负责向既有 `server_runtime.run_http_service` 注入旧 app hook，无第二个独立实现职责。
- 兼容入口：`server.py`、`docxtool.__main__` 和 `web.app.main` 保持不变。
- 快速门禁：app facade、server runtime、spawn 和路径测试 `14 passed`；启动顺序 monkeypatch 与 HTTP 契约差异为 0。
- 状态：passed。

#### Web checkpoint

- Python Web、server、auth、admin、preset、task、upload、health、monitor、路径、资源、版本和审计测试 `433 passed`；2 条重复 ZIP fixture 警告为既存安全测试构造。
- Node `v24.15.0`：11 passed，0 failed，0 skipped。
- 修改 Web 文件 Ruff、compileall、发布脚本语法和 `git diff --check` 通过。
- 路由、顺序、methods、status、headers、Cookie/CORS/security headers、JSON shape、HTML hash、错误响应、queue shape、runtime identity、启动配置和目录副作用契约差异为 0。
- `web/app.py` 从 2101 行降为 986 行；剩余内容为公开依赖/patch surface、import-time 装配、兼容 re-export、`Handler` re-export 和薄 `main`。

### Engine

状态：passed

#### Loop E1：导出主链迁移

- 原位置：`document/engine/core.py::export_doc`。
- 新位置：`document/engine/export_pipeline.py`；`core.export_doc` 保留原公开签名并注入旧 core patch 命名空间。
- 快速门禁：56 项直接测试通过；固定 6 篇、3 种模式快照差异为 0。
- 状态：passed。

#### Loop E2：共享渲染上下文

- 原位置：导出函数中的 document、关系/样式复制器、统计、开关和延迟状态局部变量。
- 新位置：`document/engine/render_context.py::RenderContext`。
- 兼容要求：后续阶段持有同一 document、copier、stats、集合和列表对象。
- 快速门禁：69 项相关测试通过；双样本、3 种模式快照差异为 0。
- 状态：passed。

#### Loop E3：特殊对象分派

- 原位置：导出循环中的表格、图片、对象题注和已有版头分支。
- 新位置：`document/engine/special_items.py`。
- 兼容要求：对象顺序、关系复制器、保护集合、异常类型和异常文本保持不变。
- 快速门禁：65 项相关测试通过；静态检查通过。
- 状态：passed。

#### Loop E4：导出最终化

- 原位置：段落循环后的字体后处理、页面/版头/分节/页码、清理、结构校验、保存和统计。
- 新位置：`document/engine/export_finalize.py`。
- 兼容要求：后处理、关系校验和保存顺序保持不变。
- 快速门禁：66 项相关测试通过；双样本、3 种模式完整 package 快照差异为 0。
- 状态：passed。

#### Loop E5：段落渲染器

- 原位置：`document/engine/export_pipeline.py` 的普通段落主循环。
- 新位置：`document/engine/paragraph_renderer.py::render_document_items`。
- 兼容入口：`engine.core.export_doc` 继续动态注入旧 core patch 点；新边界测试验证 prepare、render、finalize 顺序和共享 context 身份。
- 快速门禁：106 项段落、标题、编号和样式测试通过；1 条既有 `python-docx` 弃用警告；双样本、3 种模式完整 package 快照差异为 0。
- 状态：passed。

#### Engine checkpoint

- Engine、导出、关系、样式、编号、分节、表格、图片、页眉页脚、页码、清理和校验测试共 197 项通过；1 条既有 `python-docx` 弃用警告。
- 固定 6 篇脱敏样本、3 种模式共 18 个案例：快照 SHA-256 均为 `e7e2fa57a75696ae4f3667c0e55b9fde65c830c4f45556095ea667152f0e1749`。
- package part、relationship、XML、missing target、文档结构和 export stats 差异均为 0。
- `document/engine/core.py` 从 768 行降为 175 行；保留公开 import、helper/patch surface 和薄 `export_doc` facade。
- `document/engine/export_pipeline.py` 为 prepare、render、finalize 薄编排，不存在第二套渲染实现。

### Phase A final gate

状态：passed

- Python 3.8.10：全量 1138 项通过；2 条重复 ZIP fixture 警告和 1 条 `python-docx` 样式 API 弃用警告为既存警告。
- Python 3.10.11：按 `requirements-dev.lock` 建立独立临时环境并安装当前项目后，全量 1138 项通过；同 3 条既存警告。
- 全量 Ruff、`compileall`、`git diff --check` 通过。
- Node v24.15.0：11 passed，0 failed，0 skipped。
- 构建成功：wheel 与 sdist 均生成；wheel SHA-256 为 `20d4476e96198284442c585c932c1499cd9104d9843cb90defb31b4352e0e3c0`。
- 源码目录外 Python 3.10 干净环境仅安装 wheel：版本、资源 Schema、SDK manifest、JSON round-trip、最小识别、confirmed 绑定、validation、统一 CLI envelope 和最小 DOCX 导出通过。
- wheel 包含 Recognition providers/context/decoding、Web bootstrap/runtime/compatibility/handler 和 Engine pipeline/context/special/paragraph/finalize 全部新增模块。
- 固定源清单 50 个标准稿、5 个专项稿、3 种模式共 165 个案例；源 SHA-256 全部与基线一致，迁移前后快照 SHA-256 均为 `99f000af4fc97f74ed9ecac032a807755c981fb2b1b4f3f297a9aa94c967260a`，全部差异为 0。
- 视觉批次 `phase-a3-final-20260802-211227`：标准 50/50、专项 5/5 成功；标准 10 篇、专项 5 篇和 1 个模板均完成 LibreOffice + PyMuPDF 渲染，失败 0。
- 唯一自动标记页为正确模板第 17 页；人工确认是落款、日期和页码组成的预期稀疏签名页，不是空白页。另抽查标准稿首屏、附件页和讲话专项稿首末页，未见裁切、重叠或异常空白。

## Phase B 待调查

- 结构对齐报告仍将标准稿 021-030 各 6 项、共 60 项记为 P1 `output_regression`，涉及类型、输出新增/模板缺失和文字增减归因。该结果在本轮前后完整快照中完全一致，不是 Phase A 机械迁移引入；按阶段边界只记录，未修改识别或比较规则。
- `web.handler` 是由公开 `web.app` 装配的内部模块；独立直接导入不属于公开契约。wheel 冒烟按 `web.app` 旧入口验证通过，后续若要公开 handler 模块，需要独立设计初始化合同。

## 收口结论

- Web checkpoint：passed。
- Engine checkpoint：passed。
- Phase A final gate：passed。
- 本轮未产生仓库内快照或 wheel 发布产物；等价快照、构建包和隔离环境均位于系统临时目录。
