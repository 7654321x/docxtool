# Ubuntu Nginx HTTPS Origin 与托管会话部署设计

## 目标

`docxtool/` 是唯一受版本控制、可整体上传到 Ubuntu 22.04 的后端部署包。它使用腾讯云托管会话
以前台方式运行 Python；Nginx 是唯一常驻系统服务和 HTTPS 终点，Certbot 管理 Let's Encrypt 证书。
旧 `server/` 部署包不再是正式发布路径。

```text
Browser / WPS
  -> https://docx.toolpp.cn (Cloudflare Pages)
  -> Pages Worker + X-Proxy-Secret
  -> https://origin.toolpp.cn (A -> 43.130.232.115)
  -> Nginx :443
  -> http://127.0.0.1:9527 (DocxTool foreground process)
```

## 权威来源与范围

- 根 `src/docxtool/` 是 Python 源码唯一权威来源；`docxtool/src/docxtool/` 是与其完全一致的可上传镜像，
  由窄 parity 测试约束，不能独立演进。
- `docxtool/.env.example` 是生产配置模板，根 `.env.example` 仍只服务本地开发。
- `MAX_UPLOAD_SIZE_MB` 是唯一上传大小配置。`setup.sh` 从 `.env` 读取它，渲染
  `nginx/docxtool.conf` 中的 `client_max_body_size`；Backend 用同一环境变量完成应用层最终检查。
- `docxtool/setup.sh` 与 `start.sh` 不创建 Python systemd 服务。Nginx 和 Certbot 仍由 systemd 管理。
- 不使用 Cloudflare Tunnel、Quick Tunnel、裸 IP、Origin fallback 或公开 `9527`。

## 安装、更新与启动顺序

1. 停止当前托管会话中的 `start.sh`；`setup.sh` 发现仍存活的本包 PID 时立即失败，避免在运行中的
   Python 代码、虚拟环境或 Nginx 配置上继续更新。
2. 上传新的完整 `docxtool/` 目录，再运行 `setup.sh`。首次运行只创建 `.env` 和虚拟环境；示例 Secret
   尚未替换时立即停止，不配置或启动 Backend。
3. 后续 `setup.sh` 使用同一 Python Secret 校验器验证生产 `.env`，校验 loopback 地址、端口与
   `MAX_UPLOAD_SIZE_MB`，生成 Nginx candidate，先执行 `nginx -t`，再由 Certbot 写入 TLS 配置。
4. Certbot 成功后执行最终 `nginx -t` 和 reload；在 Certbot 前不 reload 仅含 HTTP 的 candidate。
5. 运行 `start.sh` 启动前台 Backend。它写入受控 PID 文件并在退出时清理；另一个活动实例会被拒绝。

Nginx 证书、私钥和运行数据不在上传包中。`/health`、`/ready` 可直接检查 Origin；生产其余业务请求
必须由 Worker 注入正确 `X-Proxy-Secret`。

## Secret 与失败边界

- Secret 强度、默认/弱值和“两个 Secret 不同”的规则只定义在 `docxtool.web.secrets`；部署脚本调用该
  Python 校验器，不在 Bash 复制规则。
- `PRODUCTION_MODE=true`、`BIND_HOST=127.0.0.1`、`PORT=9527` 与正整数
  `MAX_UPLOAD_SIZE_MB` 是部署专属 preflight 条件；任一失败时 Backend 保持停止。
- `origin.toolpp.cn` 当前只使用 A 记录 `43.130.232.115`，没有 AAAA。终端用户访问 Public Gateway
  可使用 IPv4 或 IPv6；这一 Origin 事实不改变 WPS 地址族选择。

## 验收

1. 部署包版本与根项目版本一致，镜像源码与根源码一致。
2. `setup.sh` 不在活动托管会话运行时继续更新；配置失败时不启动 Backend。
3. Nginx body limit 来自 `MAX_UPLOAD_SIZE_MB`，不存在第二上传限制变量或无限 body 设置。
4. `nginx -t` 在 Certbot 前执行，但 Certbot 前没有 reload；Certbot 后再验证并 reload。
5. `curl http://127.0.0.1:9527/health` 与 `curl https://origin.toolpp.cn/health` 返回 HTTP 200，且
   `ss -ltn` 不显示 `0.0.0.0:9527` 或 `[::]:9527`。

真实 Ubuntu、Certbot、DNS、Cloudflare、IPv6 客户端和 WPS 均需在线人工验收；本地自动测试不替代它们。
