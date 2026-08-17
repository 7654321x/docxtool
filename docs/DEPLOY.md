# 生产部署说明

## 固定生产拓扑

```text
Browser / WPS
  -> https://docx.toolpp.cn
  -> Cloudflare Pages + Worker
  -> https://origin.toolpp.cn (DNS A -> 43.130.232.115)
  -> Nginx :443
  -> http://127.0.0.1:9527
  -> DocxTool Python
```

`https://docx.toolpp.cn` 是网页、管理后台和 WPS 公网 API 的唯一用户入口：

- Web：`https://docx.toolpp.cn/`
- 管理后台：`https://docx.toolpp.cn/admin/login`
- WPS：`https://docx.toolpp.cn/wps-api/v1/*`

`https://origin.toolpp.cn` 仅用于 Pages Worker 回源。WPS、浏览器、EXE、浏览器代码和 Worker
源码都不使用服务器 IP、Origin 直连、Tunnel URL 或公网 `9527`。

终端用户到 `https://docx.toolpp.cn` 可使用 IPv4 或 IPv6。生产 Backend 的统一 HTTP 网关门禁使用
唯一的 `PROXY_SECRET`：除 `/health`、`/ready` 外，任何 `/version`、`/api/*`、`/admin/*` 或
`/wps-api/v1/*` 业务请求缺少或使用错误的 `X-Proxy-Secret` 都返回 HTTP 403；不根据 User-Agent、Host、IP、
Referer 或 Origin 放行。

## Ubuntu 后端

DocxTool 只监听：

```text
BIND_HOST=127.0.0.1
PORT=9527
```

Nginx 是唯一的公网 TLS 终点：`origin.toolpp.cn:443 -> 127.0.0.1:9527`。Certbot 通过 Nginx
集成申请、写入和续期 Let's Encrypt 证书。安全组仅开放 TCP 80、443，不开放 `9527`。不使用
Cloudflare Tunnel、Quick Tunnel、`trycloudflare.com` 或 Cloudflare Access。

首次部署包安装：

```bash
chmod +x linux/install.sh
sudo ./linux/install.sh --origin-host origin.toolpp.cn --certbot-email ops@example.com
```

服务器 `/opt/docxtool/.env` 至少配置：

```text
BIND_HOST=127.0.0.1
PORT=9527
PRODUCTION_MODE=true
FRONTEND_ORIGIN=https://docx.toolpp.cn
ADMIN_CONSOLE_ORIGIN=https://docx.toolpp.cn
COOKIE_SECURE=true
ADMIN_COOKIE_SECURE=true
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_IPS=127.0.0.1,::1
ADMIN_TOKEN=<different-long-random-secret>
PROXY_SECRET=<different-long-random-secret>
DATABASE_PATH=var/data/stats.db
WPS_DATABASE_PATH=var/data/wps_plugin.db
```

`ADMIN_TOKEN` 与 `PROXY_SECRET` 必须不同。修改 `.env` 后重启 `docxtool`；Python 不承担
公网 TLS，也不直接暴露管理后台。

## DNS 与 Cloudflare Pages

DNS 的唯一职责：

| 记录 | 值 | 职责 |
| --- | --- | --- |
| `docx.toolpp.cn` | Pages 自定义域名 | 公共网关 |
| `origin.toolpp.cn` A | `43.130.232.115` | Worker IPv4 HTTPS 回源定位 |

`origin.toolpp.cn` 当前不配置 AAAA 记录。Cloudflare 可以接受用户侧 IPv4 或 IPv6 请求，但回源
固定使用 Origin 的 IPv4 A 记录；不得因 Origin IPv4-only 改写客户端网络策略。

在 Pages 的 Production 环境只配置两个变量：

```text
BACKEND_BASE_URL=https://origin.toolpp.cn
PROXY_SECRET=<与 /opt/docxtool/.env 完全相同的值>
```

`BACKEND_BASE_URL` 必须是无路径、无凭据、非 IP 字面量的 HTTPS hostname。Worker 删除客户端
伪造的代理头，仅注入 `X-Proxy-Secret` 与 `X-Docxtool-Proxy`；WPS 的 Bearer Token 仅在
`/wps-api/v1/*` allowlist 路由上透传，浏览器 Cookie 不转发给 WPS 接口。

缺少 Pages Secret、Origin 不合法或共享密钥不一致时立即失败；不得改为裸 IP、直连 Origin、
Tunnel 或备用地址。

## WPS 客户端

正式 EXE 只在构建时写入一个公网基址：

```pwsh
pwsh -NoProfile -File .\apps\wps\scripts\build-exe.ps1 -PublicApiBaseUrl https://docx.toolpp.cn
```

包内 `public_api_base_url` 是 WPS 公网请求的唯一来源；所有账号、会话、心跳、通知、授权与
结果上报都由它派生 `/wps-api/v1/*`。本机 Control Server、DOCX 识别与排版仍在 loopback，
不会上传 DOCX 正文或回退直连服务器。

## 受控验证

部署完成后由有权限的人员验证：

```bash
curl http://127.0.0.1:9527/health
curl https://origin.toolpp.cn/health
```

再通过 `https://docx.toolpp.cn` 验证网页、管理员登录与 WPS 登录/心跳/授权/结果上报。线上 DNS、
Pages Secret、Nginx/Certbot 证书和真实 WPS 冒烟不由本地自动化代替。
