# Ubuntu Nginx HTTPS Origin 部署设计

## 目标

Ubuntu 生产环境只保留一条正式反向代理路径：Nginx 以 `origin.toolpp.cn` 的 HTTPS
终点反向代理到 loopback DocxTool 服务。证书由 Certbot 的 Nginx 集成申请、写入配置并自动续期。

```text
Browser / WPS
  -> https://docx.toolpp.cn (Cloudflare Pages)
  -> Pages Worker + X-Proxy-Secret
  -> https://origin.toolpp.cn (A -> 43.130.232.115)
  -> Nginx :443
  -> http://127.0.0.1:9527 (DocxTool)
```

## 已确认事实与非目标

- 生产服务器只使用 Nginx；不安装、配置、启动或保留第二套生产反向代理路径。
- `origin.toolpp.cn` 当前仅配置 A 记录 `43.130.232.115`，不配置 AAAA 记录。
- Python 固定监听 `127.0.0.1:9527`；安全组仅开放 TCP `80`、`443`，不开放 `9527`。
- Cloudflare 到 Origin 通过 IPv4 HTTPS 回源。终端用户到 Cloudflare 可以使用 IPv4 或 IPv6；
  Origin 的 IPv4-only 状态不改变客户端网络策略。
- Nginx 使用 `client_max_body_size 0`，不复制 Backend 的上传大小策略；唯一上传限制为
  `MAX_UPLOAD_SIZE_MB`。
- 生产 Backend 除 `/health`、`/ready` 外的所有 HTTP 请求必须带正确的 `X-Proxy-Secret`；
  统一入口拒绝 Origin 直连业务请求。
- 不改变 Pages Worker 的 `BACKEND_BASE_URL`、`PROXY_SECRET`、WPS 公网地址或任何业务 API。

## 安装接口与数据流

`linux/install.sh` 接收 `--origin-host` 与 `--certbot-email`。它安装 `nginx`、`certbot`、
`python3-certbot-nginx` 和 Python 运行依赖，将模板渲染到
`/etc/nginx/sites-available/docxtool`，并启用该站点：

```nginx
server {
    listen 80;
    server_name origin.toolpp.cn;

    location / {
        proxy_pass http://127.0.0.1:9527;
        # Host、X-Forwarded-* 与连接语义由模板统一定义。
    }
}
```

脚本先执行 `nginx -t` 并启用 Nginx，再执行：

```bash
certbot --nginx --non-interactive --agree-tos \
  --email <运维邮箱> --keep-until-expiring -d origin.toolpp.cn
```

Certbot 是证书文件路径、Nginx TLS 块与续期的唯一 owner；部署包不复制私钥或硬编码证书路径。
安装脚本只覆盖专属 `docxtool` site，不重写默认站点或其他业务站点。

## 失败边界

- `origin.toolpp.cn` 未解析到服务器、TCP 80 未开放、Nginx 配置非法或证书签发失败时，安装立即失败，
  不宣称 HTTPS 可用。
- `.env` 仍为示例密钥时，安装完成后不启动 `docxtool`，由运维填写密钥后显式启动。
- 不为裸 IP、公开 `9527`、Tunnel 或备用 Origin 保留兼容分支。

## 验收与停止条件

1. `nginx -t` 与 `systemctl is-active nginx` 成功。
2. `certbot certificates --cert-name origin.toolpp.cn` 显示有效证书。
3. `curl http://127.0.0.1:9527/health` 与 `curl https://origin.toolpp.cn/health` 返回 HTTP 200。
4. `ss -ltn` 不显示 `0.0.0.0:9527` 或 `[::]:9527`。
5. 窄部署架构测试断言脚本、模板和正式文档只描述 Nginx、Certbot、IPv4 Origin 与 loopback 后端。

真实 DNS、Certbot 与服务器连通性需要在 Ubuntu 环境人工验收；本地静态测试不能替代它们。
