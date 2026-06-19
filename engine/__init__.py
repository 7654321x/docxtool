"""engine — 排版引擎。

目录结构：
  _core.py   — 排版引擎主体（段落渲染、编号、页面设置）
  normal.py  — 通用模式样式重写
  report.py  — 报告模式样式重写
  scheme.py  — 方案模式样式重写
"""

from engine._core import export_doc
