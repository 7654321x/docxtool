# Ubuntu 直接 HTTPS Origin 部署设计

## 目标

为 Ubuntu 22.04 提供与现有 Pages Worker 两变量契约一致的后端部署路径：

```text
浏览器 / WPS
  -> https://docx.toolpp.cn (Cloudflare Pages)
  -> Pages Worker + X-Proxy-Secret
  -> https://origin.toolpp.cn (DNS A: 43.130.232.115; Caddy)
  -> http://127.0.0.1:9527 (DocxTool)
```

不使用 Quick Tunnel、`trycloudflare.com`、Cloudflare Access Service Token 或公网
`9527`。`origin.<domain>` 仅是 Pages Worker 的回源地址，不是用户入口。

## 约束

- `docx.toolpp.cn` 使用 CNAME 指向现有 Pages 项目，并先在 Pages
  项目的 Custom domains 中关联。
- `origin.toolpp.cn` 使用 A 记录指向 `43.130.232.115`；Caddy 管理它的 HTTPS 证书。
- 后端 `.env` 不保存 Origin IP 或 `BACKEND_BASE_URL`；它保存用户入口 Origin、
  两个不同随机密钥和 loopback 监听配置。
- `PROXY_SECRET` 是唯一 Pages 到后端的共享鉴别值，必须同时作为 Pages Secret 和
  后端 `.env` 值，绝不写入仓库或部署包。
- Linux 包以 `/opt/docxtool` 运行，使用专用低权限 `docxtool` 用户与 systemd。

## 安装与更新

部署包中的 `linux/install.sh` 接收 `--origin-host`，安装 Python 3.10、Caddy、
虚拟环境、systemd 单元和 Caddy 配置。替换已有 `/etc/caddy/Caddyfile` 必须显式
传入 `--replace-caddyfile`，避免覆盖服务器其他站点。

更新时脚本同步源码和锁文件，但排除 `.env`、`var/` 和 `.venv/`；运行数据和密钥
不会被新包覆盖。首次安装只创建 `.env` 模板，不会输出、生成或提交真实密钥，也
不会在模板密钥仍存在时启动后端。

## 验收

1. `systemctl status docxtool` 为 `active (running)`。
2. `curl http://127.0.0.1:9527/health` 返回 HTTP 200。
3. `curl https://origin.toolpp.cn/health` 经 Caddy 返回 HTTP 200。
4. Pages 环境只包含 `BACKEND_BASE_URL` 和 `PROXY_SECRET`；用户经
   `https://docx.toolpp.cn` 完成 Web、管理后台和 WPS 冒烟。
5. 公网安全组仅开放 Caddy 所需的 TCP 80、443；不开放 9527。
