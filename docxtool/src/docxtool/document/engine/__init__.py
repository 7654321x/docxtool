"""engine — 排版引擎。

目录结构：
  core.py    — 排版引擎主体（段落渲染和导出编排）
  heading_body_split.py — 可靠标题正文拆分输出和校验
  inline_effects.py — 段内文本效果和责任单位行渲染
  paragraph_format.py — 段落直接格式执行
  paragraph_styles.py — DCT 样式 ID 和段落样式不变量
  render_numbering.py — 最终标题类型的渲染期编号写入
  render_options.py — 渲染功能开关解析
  render_text.py — 渲染纯文本辅助
  render_types.py — 渲染类型映射和正文流分组
  normal.py  — 通用模式样式重写
  report.py  — 报告模式样式重写
  scheme.py  — 方案模式样式重写
"""

from docxtool.document.engine.core import export_doc as export_doc
