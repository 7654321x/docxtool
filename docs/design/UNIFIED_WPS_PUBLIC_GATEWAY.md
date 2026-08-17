# 统一 WPS 公网入口与 Cloudflare Gateway 设计

## 目标

将 WPS 与浏览器的正式公网入口统一为 `https://docx.toolpp.cn`，由 Pages Worker 使用唯一的
`BACKEND_BASE_URL=https://origin.toolpp.cn` 回源到 Nginx。`origin.toolpp.cn` 的 DNS A 记录指向
`43.130.232.115`；Python 服务继续只监听 `127.0.0.1:9527`。

```text
WPS / Browser
  -> https://docx.toolpp.cn
  -> Cloudflare Pages Worker
  -> https://origin.toolpp.cn (DNS -> 43.130.232.115)
  -> Nginx :443
  -> 127.0.0.1:9527
  -> DocxTool
```

## 已核实事实

- WPS 的 `WpsPublicApi` 是唯一的公网请求客户端；其当前构建配置键、实例属性和本地账户列均命名为
  `server_origin`，但所有请求实际由这一值与 `/wps-api/v1/*` 拼接生成。
- Pages Worker 已以 `BACKEND_BASE_URL` 作为唯一 Origin 环境变量，保留 WPS Bearer
  `Authorization`，并在回源时重写 `X-Proxy-Secret` 与 `X-Docxtool-Proxy`。
- 本地文档识别、预览、事务保存和排版均通过 WPS loopback Control Server 完成，不依赖公网地址。
- `server/1.ps1`、README 和 WPS PRD/技术设计仍含 nip.io、Pages 默认域名或 Tunnel 的历史生产描述。

## 范围

1. 将 WPS 构建参数、生成配置、验证函数和 API 客户端统一命名为
   `public_api_base_url` / `PUBLIC_API_BASE_URL`，生产 EXE 仅写入 `https://docx.toolpp.cn`。
2. 删除 WPS 本机账户存储中不再需要的 `server_origin` 字段；迁移已有 SQLite 的
   `local_account` 表，保留账号、设备、DPAPI 密文、会话、偏好和待上报结果。
3. 保持 Worker 的唯一 Origin 变量 `BACKEND_BASE_URL`，新增窄测试保证 WPS Bearer 转发、
   代理密钥重写和禁止硬编码 Origin IP。
4. 将服务器诊断、部署说明和正式产品文档切换到 Pages Worker -> Nginx HTTPS Origin 拓扑，
   删除 Tunnel、nip.io 和历史 Pages 生产路径。
5. 增加架构测试，限制 WPS 生产运行时代码只使用公共网关概念，禁止包含 Origin 域名、服务器 IP、
   nip.io、Tunnel URL 和公网 `:9527`。

## 非目标

- 不修改 WPS 本地 Control Server、Importer、Recognition、Normalization、Engine 或 DOCX 处理协议。
- 不上传 DOCX 至公网服务，不变更 WPS 公共 API 路径、请求体或 Bearer 会话协议。
- 不新增直连、备用 Origin、裸 IP、Tunnel、重试到其他主机或高可用抽象。
- 不执行 Cloudflare Secret、DNS、Nginx 或服务器上的外部配置变更；这些由部署步骤完成。

## 契约与迁移

| 边界 | 唯一权威来源 | 值 |
| --- | --- | --- |
| WPS 公网客户端 | `public_api_base_url` | `https://docx.toolpp.cn` |
| Pages Worker Origin | `BACKEND_BASE_URL` | `https://origin.toolpp.cn` |
| Pages / Backend 共享凭据 | `PROXY_SECRET` | 两端相同的 Secret |
| DNS 映射 | `origin.toolpp.cn` A 记录 | `43.130.232.115` |
| 后端监听 | `BIND_HOST`、`PORT` | `127.0.0.1:9527` |

WPS 的 `client-config.json` 从 `server_origin` 改为只含 `public_api_base_url`。本地
`local_account` 表在首次使用新客户端时重建为不含 `server_origin` 的等价表，复制保留字段后原子替换。
新代码不读取、映射或回退旧名称；旧字段仅在一次性数据库迁移中被丢弃。

## 失败边界

- 缺少或非法 `public_api_base_url`、`BACKEND_BASE_URL` 或 `PROXY_SECRET` 立即失败。
- 公共网关不可达时 WPS 返回既有网络错误，不尝试 Origin、IP 或 Tunnel。
- Pages 不配置 `PROXY_SECRET` 或与后端不一致时，Worker/后端按既有鉴权逻辑拒绝请求。
- 迁移遇到无法读取的本机数据库时沿用现有隔离逻辑，不猜测或伪造账户状态。

## 5.5.5 网关收尾约束

### 客户端网络

`origin.toolpp.cn` 仅有 IPv4 A 记录不影响客户端到公共网关的地址族选择。WPS 统一使用标准
`urllib.request` 访问 `https://docx.toolpp.cn`，由操作系统和 Cloudflare 正常选择 IPv4 或 IPv6；
不得手工解析地址、强制 IPv4，或在网关失败后尝试 Origin、裸 IP 或 Tunnel。

### 后端网关鉴权

生产模式下，`PROXY_SECRET` 是 Backend 唯一的公共网关凭据。所有业务 HTTP 请求在统一
`Handler -> handler_lifecycle` 入口处校验该请求头，未通过时返回
`PUBLIC_GATEWAY_REQUIRED` / HTTP 403，业务分派不会执行。仅 `/health` 和 `/ready` 是部署
所需的直连 Origin 检查路径；`/version`、`/api/*`、`/admin/*` 和 `/wps-api/v1/*` 都不例外。
开发模式不施加该网关门禁。File API 原有的文件操作授权保留为第二层独立检查。

### 真实客户端地址

只有 loopback Nginx 被配置为可信代理时才读取转发头。可信请求严格按
`CF-Connecting-IP -> X-Forwarded-For（最左合法项）-> X-Real-IP -> socket peer` 取值，IPv4
与 IPv6 无优先级差异，避免 Cloudflare 的 IPv4 回源地址覆盖 IPv6 终端用户地址。

### 部署包

Nginx 只负责反向代理，因此使用 `client_max_body_size 0`；唯一上传大小策略仍是 Backend 的
`MAX_UPLOAD_SIZE_MB`。Ubuntu 应用目录固定为 `/opt/docxtool`，安装器不提供与 systemd
路径冲突的自定义目录参数。根 `.env.example` 保持本地开发语义；`server/.env.example` 是必须
明确填写密钥后才能启动的生产配置。根包和 `server/` 部署包的项目版本及本轮 Gateway 源码必须一致。

### WPS 本地账户迁移

旧 `local_account.server_origin` 列只在一次性重建中移除。创建临时表、复制、删除旧表、重命名和
其他本地 schema 更新处于同一个 `BEGIN IMMEDIATE` 事务内；任意 Python 或 SQLite 异常都回滚并
继续抛出，不保留半迁移表或静默降级路径。

## 验证与停止条件

- WPS 公共 API、账户存储/迁移、登录、心跳、授权与结果上报聚焦 pytest；WPS Node 入口。
- Worker 路由测试、网关入口/客户端 IP 测试、服务器包版本与 Gateway 源码 parity 测试、安装脚本
  语法检查、文档架构测试与 `verify_changed.ps1`。
- 真实 WPS、Pages Secret、DNS、Nginx/Certbot 证书和 Ubuntu 连通性均为独立线上验证，不由本地测试宣称通过。
- 若发现现有 WPS 路由无法经 Worker 转发，或 `origin.toolpp.cn` 已被其他生产服务占用，停止实施并报告。
