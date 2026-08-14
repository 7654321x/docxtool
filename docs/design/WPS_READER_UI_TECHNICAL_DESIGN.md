# DocxTool WPS 阅读模式 UI 技术设计

本文件属于 `docs/design/` 专题设计，不作为主文档入口。

## 1. 适用范围

本文档规定 WPS TaskPane 阅读模式的界面结构、状态映射、资源组织和验证方法，适用于 DocxTool 5.4 阅读模式 UI 精修及后续维护。

本文档不改变以下边界：

- 不新增阅读 HTTP 路径、Token、端口或公网服务。
- 不修改 `apps/reader` 的 SQLite 数据模型、阅读文本存储或服务端字段。
- 不调用 WPS `Application`、`Document`、`Range`、`Comments` 对象。
- 不复制 DocxTool Core 的识别、规范化或排版规则。
- 不在本轮生成 EXE；冻结资源只通过源码资源校验和现有 PyInstaller 递归打包链验证。

## 2. 设计目标与约束

参考面板以 396px 为视觉基准，真实 WPS 侧边栏按 300–360px 运行。阅读页面采用单列、正常文档流和下方内容区滚动，不使用 `fixed` 或 `sticky`；现有版头表单等全局业务模态层不属于阅读页面布局。

视觉语言固定为：

- 浅灰绿色页面背景、白色内容卡片、单一低饱和绿色强调色。
- 卡片圆角 12–14px，使用轻微绿色调阴影表达层级。
- 常规控件间距 4–10px；窄宽度下优先压缩卡片内边距和按钮文字间距。
- 关闭按钮固定 36px 圆形图标按钮。
- 所有操作、状态、识别、阅读和设置图标均来自 `apps/wps/images/taskpane-icons.svg`，不使用 Emoji 或第三方图标库。

设计阅读结论：这是面向 WPS 日常办公用户的紧凑工具面板，采用低动效、低视觉噪声、结构清晰的原生 CSS 组件，而不是独立网页应用或第二套 UI 框架。

## 3. 组件与职责

```text
taskpane.html
  ├─ 页面 Header / 模式切换 / 排版卡片
  ├─ 阅读工具卡片
  │    ├─ 书库弹层：现有书籍下拉选择 + 删除
  │    ├─ TXT 导入
  │    └─ 折叠
  ├─ 阅读正文卡片
  ├─ 阅读控制卡片：上一段 / 播放 / 下一段 / 章节控制
  └─ 样式卡片：字号 / 行距 / 主题 / 透明度按钮和原有选项

reader-ui.js
  ├─ 复用 ReaderClient 读写现有状态
  ├─ 维护书库、阅读内容、自动滚动和进度
  ├─ 将速度滑杆索引映射为既有速度值
  └─ 只读更新阅读进度视觉轨道

taskpane.js
  └─ 复用现有 recognition_rows，按 role_name 聚合确认、复核和数量显示

reader-client.js → Control Server → ReaderService → SQLite / books/*.txt
```

`taskpane.html` 中既有业务 ID 视为稳定兼容入口，例如 `reader_book_select`、`reader_delete`、`reader_speed`、`reader_font_size` 等，不因 UI 重排而更名。新增按钮只负责显示和控制现有控件，不创建第二套状态。

## 4. 书库交互

“书库”是一个真实可展开的面板，不是无行为的装饰按钮。面板内保留：

1. `reader_book_select`：复用现有书籍列表和 `selectBook()`。
2. `reader_delete`：复用现有确认、删除托管副本和刷新流程。
3. 空书库时仍由现有导入入口提供导入，不修改原始 TXT。

按钮只切换 `reader_library.hidden`，不会把书籍数据复制到新的前端缓存，也不改变 `ReaderService` 的删除和进度迁移语义。

## 5. 速度滑杆协议保持不变

### 5.1 映射

滑杆使用离散索引，避免 HTML `range` 产生协议未约定的 1.75 倍速：

```text
slider index: 0    1     2    3     4    5
saved value:  0.5  0.75  1.0  1.25  1.5  2.0
```

UI 显示的是滑杆，保存时仍向 `ReaderClient.saveSettings()` 发送：

```json
{
  "settings": {
    "auto_scroll_speed": 1.25
  }
}
```

不新增字段，不修改 `ReaderSettings.auto_scroll_speed`，不改变服务端 0.5–2.0 的校验范围。读取历史值时按精确数组查找；不存在于 UI 离散数组但仍在服务端合法范围内的历史值必须保留原值并显示最近可见档位，下一次用户操作才按离散档位保存。

### 5.2 自动滚动

`requestAnimationFrame + 实际时间差` 仍是唯一滚动实现。滑杆变化先保存设置，再由下一帧读取 `state.settings.auto_scroll_speed`；不增加定时器、不增加重试、不向 WPS API 轮询。

## 6. 阅读进度

进度轨道只读，不注册 `input`、`change` 或拖动跳转事件。比例来源仍是：

```text
ratio = clamp(scrollTop / max(scrollHeight - clientHeight, 1), 0, 1)
```

显示层同时更新填充宽度和百分比文本。保存仍调用现有 `saveProgress()`，使用已有 `book_id`、`chapter_index`、`text_offset` 和 `scroll_ratio` 字段；不新增跳转接口。

书籍切换、章节切换、内容重载、窗口隐藏、折叠和关闭仍沿用现有强制保存点。

## 7. 样式设置按钮

四个紧凑按钮分别对应字号、行距、主题和透明度。按钮展开同一个承载面板，面板内仍使用原有 `select` 和 `reader_stealth_mode` 控件，因此：

- 保存字段与服务端协议完全不变。
- 现有配置值在重新打开阅读模式时回填。
- 按钮只负责展示选项面板和聚焦对应控件。
- 不新增设置缓存，不在 DOM 中复制一套设置值。

## 8. 识别结果展示

`taskpane.js` 只消费已有 `recognition_rows`：

- 以 `role_name` 作为显示角色；缺失时显示“未知”，不得泄露内部 `type_id`。
- 同一角色聚合总数。
- `binding_status=confirmed` 显示本地图标；数量显示绿色数字胶囊。
- `binding_status=review` 或 review level 为 review/critical_review 时显示真实待复核数量。
- 没有数据时显示简洁空状态，不伪造成功统计。

识别汇总只改变显示，不改变 Recognition、SDK Binding、预览批注和宿主协议。

## 9. 资源、缓存与打包

- 图标资源：`apps/wps/images/taskpane-icons.svg`。
- TaskPane 通过同源静态服务加载 SVG symbol，所有资源继续发送 `no-store`。
- PyInstaller spec 已递归收集 `images/`，`main.py verify` 额外检查图标集存在。
- `taskpane.html` 对 `reader-ui.js`、`taskpane.js` 和 `reader.css` 使用版本查询参数，避免 WPS 复用旧页面缓存。
- 不提交生成的 EXE、运行日志、Token 配置或用户 TXT。

## 10. 验证矩阵

源码和模拟宿主验证：

```pwsh
node --check apps/wps/reader/reader-ui.js
node --check apps/wps/taskpane.js
node --test apps/wps/tests/reader-ui.test.mjs
node --test apps/wps/tests/wps-runtime.test.mjs
python apps/wps/main.py verify
git diff --check
```

必须覆盖：

- 书库按钮打开面板，选择和删除仍调用原有 ReaderClient。
- 四个样式按钮展开现有选项，保存请求字段不变。
- 六档速度滑杆只产生既有六个值。
- 进度轨道只读且比例随正文滚动变化。
- 识别角色聚合、确认图标、绿色数量和复核数量。
- 300px、360px 和 396px 下按钮不横向溢出。
- SVG 可解析，WPS 资源校验通过。

真实宿主验证：

```text
WPS_UI_SMOKE = PASS
```

本轮已在真实 WPS 空白文档中打开 TaskPane 并切换到阅读模式。WPS 当前 DPI 下，宿主逻辑宽度约 390px 映射为约 320px 物理截图；已核对本地图标、书库弹层、删除入口、速度滑杆、只读进度、四个样式按钮和设置选项展开，未发现横向溢出。300/360/396px 的边界行为继续由 CSS 与模拟宿主测试覆盖。自动化 Node 测试不得替代真实宿主结论。

## 11. 后续非本轮内容

- 不增加拖动进度跳转。
- 不增加书库搜索、云同步、书签或全文搜索。
- 不引入第三方图标库、WebView 登录页或新的 UI 框架。
- 不改变阅读正文本地存储和日志隐私边界。
