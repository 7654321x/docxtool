# WPS 宿主回归清单

本文档记录 WPS 插件的具体故障场景、稳定错误码和最小验证命令。跨任务架构边界见 [`../apps/wps/AGENTS.md`](../apps/wps/AGENTS.md)，公网接口见 [`API.md`](API.md)，真实 WPS 未执行的项目必须标记 `NOT_RUN`。

## 启动、账号与加载项

- [ ] 每次启动先显示独立登录/注册窗口；已有本地账号只用于回填字段。
- [ ] 自动登录只在窗口显示后调用与点击“登录”相同的提交函数；失败时窗口保持打开并允许手动修改。
- [ ] 登录成功前不创建 AccountRuntime、Control Server、静态服务，不发布 `docxtool-wps-app`。
- [ ] 没有账号、账号损坏或取消窗口时只移除本项目加载项，保留其他 WPS 加载项。
- [ ] 退出登录先停止服务、移除加载项，再以强制登录模式重新打开窗口。
- [ ] 固定端口 3889 被占用时，仅确认是本项目旧服务才自动停止并重试；非本项目进程不得自动结束。
- [ ] 自动登录、记住密码和开机自启相互独立；开机自启仍显示登录窗口。
- [ ] 登录窗口、设置窗口、任务栏、Alt+Tab 和托盘使用统一本地 D 标志；Qt5/PySide2 资源必须进入冻结文件校验。

## Host、TaskPane 与 Control

- [ ] Host/TaskPane 使用单槽长请求；禁止使用 PluginStorage 命令或状态轮询。
- [ ] 新 Host generation 使旧请求、旧命令和旧窗格状态失效。
- [ ] `panel_ready` 5 秒无 `CLAIMED/RUNNING` 只记录一次 ACK 超时，提交后总计 30 秒无 `PASS/FAIL` 时停止等待、禁用按钮、清理窗格标识并提示重启 WPS。
- [ ] 普通命令 ACK 超时仍按原有清理行为，不进入 `panel_ready` 30 秒观察流程。
- [ ] Control 长请求遇到本机客户端断开只记录一次 `control.client.disconnected` 和 `WPS_CONTROL_CLIENT_DISCONNECTED`，不二次写响应、不打印 traceback、不访问公网。
- [ ] 真实响应写入错误仍记录 `control.response.write_failed` 并保留原异常。
- [ ] TaskPane 状态值在协议中保持大写稳定值，用户界面显示“就绪、处理中、成功、失败”等中文；错误码只能放在“错误代码：”之后。
- [ ] TaskPane 页面自身不滚动，顶部操作区保持正常布局，只允许内容区滚动；初始化和 `load` 后均清理宿主恢复的根滚动位置。
- [ ] 首次创建窗格按 `DockPosition → Width → Visible` 设置，并使用页面版本替换旧实例；不得用 CSS 位移掩盖 WPS 原生裁剪。
- [ ] `panel_ready` 只执行一次宿主工作区重排，不保存临时文档、不调用 Engine、不自动重提同一命令。
- [ ] Ribbon 只保留官方支持的按钮回调；自定义图标使用仓库内 SVG，不调用未公开 WPS API。

## 正式排版与事务

- [ ] 一键排版必须经过公网授权，再进入现有 Core 排版事务；授权失败不创建 Host 命令。
- [ ] 结果同步失败不改判文档事务失败；本地 `PASS/FAIL` 进入 SQLite 持久 outbox，心跳或下次启动继续补报。
- [ ] 账号被明确拒绝时，在同一 SQLite 事务删除本地账号和待发回执；网络失败、会话过期和正常停止保留回执。
- [ ] Host 在取得 `operation_id` 前断开时，后续同一 `request_id` 的 `apply/FAIL` 必须精确回滚对应事务，其他请求不得触发清理。
- [ ] Control 重启时恢复未完成事务；已提交结果与备份均缺失但源文件已匹配结果时，清理旧 journal 后继续启动。
- [ ] `.doc/.wps` 只由 WPS Host 使用隐藏临时文件一次性升级为同名 `.docx`；检测和清除预览不得触发升级。
- [ ] 指定页码范围按排版前分页一次性固定；跨页物理段整体纳入，范围外内容原样复制。
- [ ] 事务失败、取消、重开或 finalize 失败时恢复原文件；成功结果不在插件退出时自动恢复。

## Recognition、样式与版头

- [ ] WPS 正式排版使用 `structural`，保留用户明确开启的标点、序号、页码、版头和清理开关。
- [ ] 原生自动编号标题先由 Core 识别和规范化；WPS 不复制编号算法，普通自动列表继续保留。
- [ ] 通过 `style_profile=wps_builtin` 输出的正文和一至四级标题使用内置 `Normal`、`Heading1`—`Heading4`；中文 WPS 顶部保持“正文、标题1、标题2、标题3、标题4”。
- [ ] “添加版头”只执行 `inspect → prepare → commit → reopen → finalize`，不调用 Recognition 或公网授权；生成失败恢复原文。
- [ ] 版头当前只支持单机关；联合源版头返回 `WPS_LETTERHEAD_JOINT_SOURCE_UNSUPPORTED`。
- [ ] 直线型和五角星型分割线、机关标志、发文字号、签发人和页码范围均有对应本地事务或绑定测试。

## 登录和任务窗格 UI

- [ ] 登录/注册使用 PySide2 5.15.2.1、Qt Widgets 和 QSS；不得引入 Qt6、PySide6、PyQt6、Electron 或 WebView 登录页。
- [ ] 登录和注册视图按内容与 DPI 调整，不使用会遮挡提交按钮的固定高度；小屏只允许内容区滚动。
- [ ] 账号、密码和确认密码输入框等宽；账号尾部使用本地 user SVG，密码显示开关作为 `QLineEdit` 尾部 action 嵌入输入框。
- [ ] 顶部只显示 D 标志和 DocxTool 名称，不展示宣传语、无内容状态、服务条款或隐私政策占位。
- [ ] 登录、设置、应用、任务栏、Alt+Tab 和托盘使用同一完整图标；页面品牌图只裁切安全边距后放大。
- [ ] 使用 Qt5 原生 Windows 标题栏和 Windows 7 可用的 AppUserModelID，不依赖 Windows 10/11 专属 UI API。

## Launcher 清理与调试收尾

- [ ] Launcher 退出或失败时逐项停止 AccountRuntime、Web、Control、Control 线程和运行配置；单个清理失败不得跳过后续步骤。
- [ ] 业务已有异常时保留业务异常；只有清理失败时抛出第一个清理异常。
- [ ] 启动调试服务前记录本轮 PID 和端口；验证结束后只关闭本轮创建的进程树并删除生成的 runtime config。
- [ ] 不默认结束用户原有 WPS 进程；清理加载项前只处理 `docxtool-wps-app`，保留其他加载项。

## 日志、隐私与人工门禁

- [ ] 日志只记录阶段、状态、耗时、计数、稳定错误码和脱敏短 ID，不记录正文、路径、Token、Cookie、完整哈希或快照。
- [ ] 后台心跳只有 `PublicApiError.network=True` 才显示“服务器无法连接”；账号禁用、会话过期和业务拒绝不得误报网络离线。
- [ ] 真实 WPS 未执行时分别报告 `WPS_AUTO_NUMBERING_SMOKE`、`WPS_STYLE_GALLERY_SMOKE`、`WPS_PAGE_RANGE_SMOKE`、`WPS_LETTERHEAD_SMOKE = NOT_RUN`。

## 最小验证命令

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest apps/wps/tests -q"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest tests/test_architecture_docs.py -q"
pwsh -NoProfile -Command "node --test apps/wps/tests/wps-runtime.test.mjs"
pwsh -NoProfile -File .\apps\wps\scripts\verify.ps1
```
