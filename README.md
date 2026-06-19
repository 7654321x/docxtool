# 公文排版 Web 服务部署包

这是一个公文排版软件，支持常见格式自动排版，暂时不可排列表格和图片。

这个目录是云服务器部署所需的最小代码集合，不包含本地测试文档、打包产物、日志和数据库。

## 文件说明

- `server.py`: Web 服务入口，上传 `.docx` 后生成排版文件。
- `index.html`: 浏览器访问的前端页面。
- `importer.py`, `style_config.py`, `engine/`: 文档识别与排版核心代码。
- `config.json`: 默认排版规则。
- `requirements.txt`: Python 依赖。
- `logs/`, `outputs/`: 运行时目录，服务会写入日志和生成文件。

详细 HTTP 接口、鉴权方式、错误码和调用示例见 `API.md`。

## 快速启动

```bash
cd docxtool
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

默认监听 `127.0.0.1:9527`，适合配合 Nginx 反向代理。

如果需要直接监听公网网卡：

```bash
BIND_HOST=0.0.0.0 PORT=9527 python3 server.py
```

后台监控默认地址会在启动时打印，默认管理密码来自 `ADMIN_TOKEN`，未设置时使用代码里的默认值。生产环境建议设置：

```bash
export ADMIN_TOKEN='换成你的后台密码'
export PROXY_SECRET='换成你的前端代理密钥'
```

## 可选 systemd 示例

把路径 `/opt/docxtool` 替换成你实际上传后的目录：

```ini
[Unit]
Description=Docx Tool
After=network.target

[Service]
WorkingDirectory=/opt/docxtool
ExecStart=/opt/docxtool/.venv/bin/python /opt/docxtool/server.py
Environment=ADMIN_TOKEN=换成你的后台密码
Environment=PROXY_SECRET=换成你的前端代理密钥
Restart=always

[Install]
WantedBy=multi-user.target
```
