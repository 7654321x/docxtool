# -*- mode: python ; coding: utf-8 -*-

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from PyInstaller.utils.hooks import collect_data_files


project_root = Path(SPECPATH).parents[1]
wps_root = project_root / "apps" / "wps"
server_origin = os.environ.get("DOCXTOOL_WPS_SERVER_ORIGIN", "")
parsed_origin = urlparse(server_origin)
try:
    _ = parsed_origin.port
except ValueError as exc:
    raise RuntimeError("WPS_BUILD_SERVER_ORIGIN_INVALID") from exc
if (
    parsed_origin.scheme != "https"
    or not parsed_origin.hostname
    or parsed_origin.username is not None
    or parsed_origin.password is not None
    or parsed_origin.path not in {"", "/"}
    or parsed_origin.query
    or parsed_origin.fragment
):
    raise RuntimeError("WPS_BUILD_SERVER_ORIGIN_INVALID")

generated_root = project_root / "build" / "wps-client"
generated_root.mkdir(parents=True, exist_ok=True)
client_config = generated_root / "client-config.json"
client_config.write_text(
    json.dumps({"server_origin": server_origin.rstrip("/")}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

datas = collect_data_files("docxtool.resources", include_py_files=False)
for filename in (
    "package.json",
    "manifest.xml",
    "ribbon.xml",
    "index.html",
    "main.js",
    "host-runtime.js",
    "taskpane.html",
    "taskpane.js",
):
    datas.append((str(wps_root / filename), "."))
for directory in ("js", "images", "reader"):
    for source in (wps_root / directory).rglob("*"):
        if source.is_file():
            destination = str(source.relative_to(wps_root).parent)
            datas.append((str(source), destination))
datas.append((str(client_config), "."))

a = Analysis(
    [str(wps_root / "main.py")],
    pathex=[str(project_root), str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "docxtool.resources",
        "docxtool.resources.schemas",
        "apps.reader",
        "apps.reader.models",
        "apps.reader.paths",
        "apps.reader.storage",
        "apps.reader.import_text",
        "apps.reader.parser",
        "apps.reader.service",
        "apps.wps.control.reader_routes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DocxToolWps",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
