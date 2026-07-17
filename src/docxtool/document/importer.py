"""importer — .docx 导入 + 段落分类 + 结构识别。

职责边界：
  - 按 Word body XML 顺序提取段落/表格/图片段落
  - 标点规范化（引号/括号/英文标点→中文）
  - 19 步 scorer 优先级的段落分类
  - FLOW 状态机控制层级跳转
  - 附件/落款/日期固定结构识别（正文→附件说明→落款→日期→附件页）
  - 编号分配 + 同级合并 + 连续性修复
  - 不负责排版渲染（由 engine.py 负责）
"""

import copy
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

from docxtool.document.classifier import ClassificationOptions, classify_paragraphs
from docxtool.document.style_config import (
    NB_FIXED, NB_SUFFIXES,
    logger, ImportError,
    StyleRule,
)

# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class ParagraphFeatures:
    """段落的可观测物理特征。"""
    text: str = ""
    style_name: str = ""          # Word 原始样式名
    font_name: str = ""           # 字体名
    font_size_pt: Optional[float] = None
    bold: bool = False
    alignment: str = ""           # "LEFT"/"CENTER"/"RIGHT"/"JUSTIFY"
    first_line_indent: float = 0.0
    numbering_prefix: str = ""    # 检测到的编号前缀
    paragraph_index: int = 0
    is_in_table: bool = False
    contains_image: bool = False
    is_new_line: bool = False     # 是否由 \n 拆分出的新行


@dataclass
class InlineToken:
    """Inline paragraph content that must survive re-rendering."""
    kind: str                     # "text" / "tab" / "line_break" / "page_break"
    text: str = ""


@dataclass
class ParagraphData:
    """段落数据（导入后的中间表示）。"""
    text: str                     # 剥离编号后的纯文本
    type_id: str                  # "heading1" / "body" / …
    original_text: str            # 原始文本（含编号）
    features: ParagraphFeatures
    meta: dict = field(default_factory=dict)  # {"is_title": True, …}
    inline_tokens: List[InlineToken] = field(default_factory=list)


@dataclass
class BodyBlock:
    """Original body-order block for export."""
    kind: str                     # "paragraph" / "table" / "paragraph_xml"
    value: object


@dataclass
class DocumentData:
    """文档数据（导入后的完整表示）。"""
    paragraphs: List[ParagraphData] = field(default_factory=list)
    tables: list = field(default_factory=list)     # 原样保留的表格
    body_blocks: list = field(default_factory=list) # 原文 body 顺序：段落/表格/图片段落
    filepath: str = ""
    has_cover: bool = False
    doc_mode: str = ""  # 文种：REPORT / NORMAL / ""
    body_sectPr: object = None
    section_relationship_parts: Dict[str, object] = field(default_factory=dict)
    even_and_odd_headers: object = None
    letterhead_detection: object = None


_OBJECT_CAPTION_RE = re.compile(
    r"^(?:表|图)\s*(?:(?:[0-9一二三四五六七八九十百]+(?:[-—._、][0-9一二三四五六七八九十百]+)*).*|[:：].*|)$"
)


def _is_object_caption(paragraph) -> bool:
    """Return whether a paragraph immediately below an object is a caption."""
    text = paragraph.text.strip()
    style_name = (paragraph.style.name or "") if paragraph.style else ""
    return bool(text and (_OBJECT_CAPTION_RE.match(text) or style_name.lower() == "caption" or "题注" in style_name))


# ═══════════════════════════════════════════════════════════════
# 特征提取
# ═══════════════════════════════════════════════════════════════

def extract_features(paragraph, index: int) -> ParagraphFeatures:
    """从 python-docx Paragraph 提取物理特征。"""
    text = paragraph.text.strip()
    pf = ParagraphFeatures(
        text=text,
        paragraph_index=index,
    )

    # 样式名
    if paragraph.style:
        pf.style_name = paragraph.style.name or ""

    # 字体属性（选取第一个有内容的 run）
    if paragraph.runs:
        for run in paragraph.runs:
            if run.text.strip():
                try:
                    if run.font.name:
                        pf.font_name = run.font.name
                    if run.font.size:
                        pf.font_size_pt = run.font.size / 12700
                    pf.bold = bool(run.font.bold)
                except Exception:
                    pass
                break

    # 对齐（统一小写 + 处理 None）
    try:
        if paragraph.alignment is not None:
            pf.alignment = str(paragraph.alignment).split(".")[-1].lower()
    except Exception:
        pass

    # 缩进
    try:
        indent = paragraph.paragraph_format.first_line_indent
        if indent is not None:
            pf.first_line_indent = indent / 360000  # EMU → cm
    except Exception:
        pass

    # 编号前缀
    pf.numbering_prefix = _detect_numbering_prefix(text)

    pf.contains_image = _contains_visible_image(paragraph._element)

    # Word 多级列表：ilvl → 项目里的标题级别（0=heading2, 1=heading3, 2+=heading4）
    try:
        from docx.oxml.ns import qn as _qn2
        pPr = paragraph._element.find(_qn2('w:pPr'))
        if pPr is not None:
            numPr = pPr.find(_qn2('w:numPr'))
            if numPr is not None:
                ilvl_el = numPr.find(_qn2('w:ilvl'))
                lvl = int(ilvl_el.get(_qn2('w:val'), '0')) if ilvl_el is not None else 0
                # 只要 Word 里确实存在自动编号/多级列表，且文本本身没有字面编号，
                # 就保留层级信息，后续再结合上下文决定是标题还是附件项。
                has_literal = bool(re.match(r'^[（\(]?\d+[）\)\.．]', text.strip()))
                if not pf.numbering_prefix and not has_literal:
                    pf.numbering_prefix = f"@lvl_{lvl}"
                    logger.debug(f"[多级列表] ilvl={lvl} → heading{lvl+2} text={text[:30]}")
    except Exception as e:
        logger.debug(f"[多级列表] 提取失败: {e}")

    # Word 自动编号/样式检测
    try:
        # 样式名直接映射
        style_name = pf.style_name.lower()
        heading_styles = {
            "heading 1": "heading1", "heading1": "heading1",
            "标题 1": "heading1", "标题1": "heading1",
            "heading 2": "heading2", "heading2": "heading2",
            "标题 2": "heading2", "标题2": "heading2",
            "heading 3": "heading3", "heading3": "heading3",
            "标题 3": "heading3", "标题3": "heading3",
            "heading 4": "heading4", "heading4": "heading4",
            "标题 4": "heading4", "标题4": "heading4",
        }
        if style_name in heading_styles:
            pf.numbering_prefix = f"@style_{heading_styles[style_name]}"

    except Exception:
        pass

    return pf


def _contains_visible_image(paragraph_element) -> bool:
    picts = paragraph_element.findall(
        './/{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict'
    )
    if picts:
        return True

    drawings = paragraph_element.findall(
        './/{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing'
    )
    for drawing in drawings:
        extents = [element for element in drawing.iter() if element.tag.endswith('}extent')]
        if not extents:
            return True
        for extent in extents:
            try:
                if int(extent.get('cx', '0')) > 0 and int(extent.get('cy', '0')) > 0:
                    return True
            except ValueError:
                return True
    return False


def extract_inline_tokens(paragraph) -> List[InlineToken]:
    """Extract supported inline tokens without duplicating rendered page breaks."""
    from docx.oxml.ns import qn as _qn

    tokens: List[InlineToken] = []
    for run in paragraph._element.findall(".//" + _qn("w:r")):
        for child in run.iterchildren():
            if child.tag == _qn("w:t"):
                tokens.append(InlineToken("text", child.text or ""))
            elif child.tag == _qn("w:tab"):
                tokens.append(InlineToken("tab"))
            elif child.tag == _qn("w:br"):
                break_type = child.get(_qn("w:type"))
                tokens.append(InlineToken("page_break" if break_type == "page" else "line_break"))
            elif child.tag == _qn("w:cr"):
                tokens.append(InlineToken("line_break"))
            elif child.tag == _qn("w:lastRenderedPageBreak"):
                continue
    return tokens


def inline_tokens_text(tokens: List[InlineToken]) -> str:
    parts = []
    for token in tokens or []:
        if token.kind == "text":
            parts.append(token.text)
        elif token.kind == "tab":
            parts.append("\t")
        elif token.kind == "line_break":
            parts.append("\n")
    return "".join(parts)


def _normalize_inline_tokens(tokens: List[InlineToken], punctuation_enabled: bool) -> List[InlineToken]:
    if not punctuation_enabled:
        return list(tokens or [])
    normalized = []
    for token in tokens or []:
        if token.kind == "text":
            normalized.append(InlineToken("text", _to_chinese_punctuation(_normalize_quotes(token.text))))
        else:
            normalized.append(token)
    return normalized


def extract_paragraph_sectPr(paragraph):
    from docx.oxml.ns import qn as _qn

    pPr = paragraph._element.find(_qn("w:pPr"))
    if pPr is None:
        return None
    sectPr = pPr.find(_qn("w:sectPr"))
    return copy.deepcopy(sectPr) if sectPr is not None else None


def collect_section_header_footer_parts(doc, sectPr, data: DocumentData) -> None:
    """Record source document relationships used by a section properties element."""
    if sectPr is None:
        return

    from docx.oxml.ns import qn as _qn

    for tag in ("w:headerReference", "w:footerReference"):
        for ref in sectPr.findall(_qn(tag)):
            rel_id = ref.get(_qn("r:id"))
            if not rel_id or rel_id in data.section_relationship_parts:
                continue
            related = doc.part.related_parts.get(rel_id)
            if related is not None:
                data.section_relationship_parts[rel_id] = related


# ═══════════════════════════════════════════════════════════════
# 编号前缀检测（仅用于提取特征，不做业务判定）
# ═══════════════════════════════════════════════════════════════

_NUMBERING_PATTERNS = [
    (re.compile(r'^[一二三四五六七八九十百]+、'), "chinese_dun"),
    (re.compile(r'^[（\(][一二三四五六七八九十百]+[）\)]'), "chinese_paren"),
    (re.compile(r'^\d+[.．]'), "digit_dot"),
    (re.compile(r'^[（\(]\d+[）\)]'), "digit_paren"),
    (re.compile(r'^\[(\d+)\]'), "bracket_ref"),
    (re.compile(r'^-\s*\d+\s*-'), "page_num"),
]


def _detect_numbering_prefix(text: str) -> str:
    """检测文本中的编号前缀（仅特征提取，不判断类型）。"""
    for pat, name in _NUMBERING_PATTERNS:
        m = pat.match(text)
        if m:
            return m.group(0)
    return ""


# ═══════════════════════════════════════════════════════════════
# 统一评分容器
# ═══════════════════════════════════════════════════════════════

@dataclass
class ScoreDetail:
    """某个候选类型的完整评分明细。"""
    total: float = 0.0
    reasons: List[Tuple[str, float]] = field(default_factory=list)  # [(来源, 分值), …]


@dataclass
class ScoreBoard:
    """统一评分面板，保留完整评分链路（可解释）。"""
    _scores: Dict[str, ScoreDetail] = field(default_factory=dict)

    def add_pattern(self, type_id: str, score: float) -> None:
        self._add(type_id, "pattern", score)

    def add_rules(self, scores: Dict[str, float]) -> None:
        for type_id, score in scores.items():
            if score != 0:
                self._add(type_id, "rule", score)

    def add_context(self, type_id: str, score: float) -> None:
        self._add(type_id, "context", score)

    def _add(self, type_id: str, source: str, value: float) -> None:
        if value == 0:
            return
        if type_id not in self._scores:
            self._scores[type_id] = ScoreDetail()
        self._scores[type_id].total += value
        self._scores[type_id].reasons.append((source, value))

    def winner(self) -> Tuple[str, ScoreDetail]:
        """返回 (type_id, ScoreDetail)。无候选时返回 body。"""
        if not self._scores:
            detail = ScoreDetail()
            detail.total = 10.0
            detail.reasons.append(("default", 10.0))
            return ("body", detail)
        best = max(self._scores, key=lambda x: self._scores[x].total)
        return best, self._scores[best]

    def explain(self) -> List[dict]:
        """结构化解释（供 UI 或高级 debug 使用）。"""
        result = []
        for type_id, detail in sorted(
            self._scores.items(), key=lambda x: x[1].total, reverse=True
        ):
            result.append({
                "type": type_id,
                "score": detail.total,
                "reasons": detail.reasons,
            })
        return result

    def debug_log(self, para_index: int, text: str) -> None:
        """输出完整评分明细到 DEBUG 日志。"""
        logger.debug(f"[评分] para={para_index} text={text[:30]}")
        for item in self.explain():
            parts = " + ".join(f"{s}={v:.0f}" for s, v in item["reasons"])
            logger.debug(f"  {item['type']:15} = {item['score']:5.0f}  ({parts})")


# ═══════════════════════════════════════════════════════════════
# 上下文对象
# ═══════════════════════════════════════════════════════════════

@dataclass
class DetectionContext:
    """段落识别上下文，随遍历推进更新。"""
    para_index: int = 0
    prev_type_id: str = ""
    has_seen_heading: bool = False
    has_seen_body: bool = False
    current_level: int = 0  # 0=无, 1=heading1, 2=heading2, 3=heading3, 4=heading4
    doc_mode: str = ""       # 文种："" / "REPORT" / "NORMAL"（头部结束后自动锁定）
    glossary_mode: bool = False  # 名词解释模式（title2="名词解释"后激活）
    title_texts: list = field(default_factory=list)  # 头部标题文字（用于文种检测）

    # ── 附件 / 落款 结构状态 ──
    has_seen_real_body: bool = False
    attachment_note_seen: bool = False
    attachment_note_mode: bool = False
    attachment_page_mode: bool = False
    signature_seen: bool = False
    signature_complete: bool = False
    _remaining_has_no_body: bool = False  # 后面没有正文/标题了
    last_structural_type: str = ""
    last_structural_text: str = ""
    attachment_note_next_no: int = 1


# ═══════════════════════════════════════════════════════════════
# V3 规则引擎 — 19 步优先级 + 独立 scorer + Flow 状态机
# ═══════════════════════════════════════════════════════════════

# ── 附件 / 落款 结构正则 + 中文数字 ──
_CN_NUM2 = {"零":0,"〇":0,"○":0,"一":1,"二":2,"两":2,"三":3,"四":4,
            "五":5,"六":6,"七":7,"八":8,"九":9,"十":10}
_CN_YEAR_DIGITS = {"零":"0", "〇":"0", "○":"0", "一":"1", "二":"2", "两":"2",
                   "三":"3", "四":"4", "五":"5", "六":"6", "七":"7", "八":"8", "九":"9"}
_ATT_NOTE_RE = re.compile(r'^\s*附件\s*[:：]\s*(.*)$')
_ATT_ITEM_RE = re.compile(r'^\s*\d+[.．、]\s*\S+')
_ATT_PAGE_RE = re.compile(r'^\s*附件\s*([0-9一二三四五六七八九十]*)\s*$')
_SIGN_DATE_RE2 = re.compile(
    r'^\s*((?:19|20)\d{2}|[零〇○一二两三四五六七八九]{4})\s*年\s*'
    r'([0-9]{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*月\s*'
    r'([0-9]{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*日\s*$'
)
_REPORT_HEADING_STARTS = ("一年来", "五年来")
_SIGN_ORG_NEGATIVE_STARTS = ("以上", "请", "现将", "特此", "有关", "此")

def _is_body_context(ctx) -> bool:
    return ctx.last_structural_type in ("body", "addressing",
        "attachment_note", "attachment_note_item", "attachment_body")

def _cn2int(s: str):
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_NUM2:
        return _CN_NUM2[s]
    if "十" in s:
        left, _, right = s.partition("十")
        return (_CN_NUM2.get(left, 1) if left else 1) * 10 + (
            _CN_NUM2.get(right, 0) if right else 0
        )
    return None

def _cn_year2int(s: str):
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    digits = "".join(_CN_YEAR_DIGITS.get(ch, "") for ch in s)
    return int(digits) if len(digits) == 4 else None

def _norm_sign_date(text: str) -> str:
    m = _SIGN_DATE_RE2.match(text or "")
    if not m:
        return text
    y, mo, d = _cn_year2int(m.group(1)), _cn2int(m.group(2)), _cn2int(m.group(3))
    return f"{y}年{mo}月{d}日" if mo and d else text

def _norm_attach_mark(text: str) -> str:
    m = _ATT_PAGE_RE.match(text or "")
    if not m:
        return text
    no = m.group(1)
    normalized_no = _cn2int(no)
    return f"附件 {normalized_no}" if normalized_no is not None else "附件"

def _is_attachment_page_mark(text: str) -> bool:
    return bool(_ATT_PAGE_RE.match((text or "").strip()))

def _is_attachment_boundary(text: str) -> bool:
    t = (text or "").strip()
    return bool(_ATT_NOTE_RE.match(t) or _is_attachment_page_mark(t))

def _norm_sign_org(text: str) -> str:
    return re.sub(r'^\s*[一二三四五六七八九十百]+、\s*', '', text or "", count=1).strip()

def _record_structural(ctx, type_id: str, text: str) -> None:
    ctx.last_structural_type = type_id
    ctx.last_structural_text = (text or "").strip()

def _blocks_independent_sign_date(ctx) -> bool:
    prev = (ctx.last_structural_text or "").strip()
    if not prev:
        return False
    if prev.replace(" ", "").replace("\u3000", "").startswith("责任单位："):
        return False
    if prev.startswith(_SIGN_ORG_NEGATIVE_STARTS):
        return True
    return _contains_colon(prev)

def _looks_like_sign_org(text: str, next_text: str, ctx) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 30:
        return False
    if t.startswith(_SIGN_ORG_NEGATIVE_STARTS):
        return False
    if any(c in t for c in ("。","；",";","：",":")):
        return False
    if _ATT_NOTE_RE.match(t) or _SIGN_DATE_RE2.match(t):
        return False
    if not _is_body_context(ctx):
        return False
    if not _SIGN_DATE_RE2.match(next_text or ""):
        return False
    return True

def _heading_has_inline_body(text: str) -> bool:
    period_pos = (text or "").find("。")
    return period_pos >= 0 and len(text[period_pos + 1:].strip()) >= 5

def _can_start_attachment_note(ctx) -> bool:
    """判断当前上下文是否允许进入附件说明块。

    旧逻辑要求上一段必须精确等于 body，实际文档里附件说明前常常会夹着
    addressing / heading / title2 等结构，导致“附件：...”被普通分类器抢走。
    这里放宽为：正文主体已经出现，且尚未进入附件正文页/未完成一轮落款附件流程。
    """
    if not ctx.has_seen_real_body:
        return False
    if ctx.attachment_page_mode:
        return False
    if ctx.signature_complete and ctx.last_structural_type != "sign_date":
        return False
    return ctx.last_structural_type in (
        "body", "addressing", "heading1", "heading2", "heading3", "heading4",
        "heading1_report", "title2", "glossary_item", "sign_date",
        "attachment_note_item",
    )

def _is_auto_numbered_item(feats: Optional[ParagraphFeatures]) -> bool:
    if not feats or not feats.numbering_prefix:
        return False
    return feats.numbering_prefix.startswith("@lvl_") or feats.numbering_prefix.startswith("@style_")


_RESPONSIBILITY_LINE_RE = re.compile(r"^\s*[“”\"'‘’「『]?\s*责\s*任\s*单\s*位\s*[:：]")
_RESPONSIBILITY_LABEL_RE = re.compile(r"\s*责\s*任\s*单\s*位\s*[:：]\s*")
_RESPONSIBILITY_WRAPPER_RE = re.compile(r"^\s*[“”\"'‘’「『]\s*(.*?)\s*[”\"'’」』]?\s*$")


def _should_split_structural_line_breaks(parts: list[str], next_text: str) -> bool:
    """Split manual line breaks when they delimit known document structures."""
    nonempty = [part.strip() for part in parts if part.strip()]
    if len(nonempty) < 2:
        return False
    if any(_detect_numbering_prefix(part) for part in nonempty[1:]):
        return True

    # A title block often uses soft line breaks and ends in "职务  姓名".
    role_line = nonempty[-1]
    if (re.fullmatch(r"[\u4e00-\u9fff、，,·]{2,28}\s{2,}[\u4e00-\u9fff·]{2,6}", role_line)
            or (re.search(r"主任|书记|主席|部长|局长|处长|科长|市长|县长|区长|镇长|乡长|院长|校长|政委|组长|队长|秘书长|委员|常委|负责人", role_line)
                and re.search(r"\s{2,}", role_line))):
        return True

    # A signature organization may be separated from the final body paragraph
    # by manual blank lines; the following paragraph supplies the date boundary.
    next_visible_line = next(
        (part.strip() for part in (next_text or "").splitlines() if part.strip()),
        "",
    )
    return bool(_SIGN_DATE_RE2.match(next_visible_line)
                and len(role_line) <= 30
                and not any(mark in role_line for mark in "。；;：:"))


def _normalize_responsibility_line(text: str) -> str:
    unwrapped = _RESPONSIBILITY_WRAPPER_RE.sub(r"\1", text or "")
    normalized = _RESPONSIBILITY_LABEL_RE.sub("责任单位：", unwrapped)
    return re.sub(r"(?<!^)(责任单位：)", r"\n\1", normalized)


def detect_structural_type(line: str, next_line: str, ctx,
                           feats: Optional[ParagraphFeatures] = None,
                           next_feats: Optional[ParagraphFeatures] = None):
    """固定结构状态机：正文 → [附件说明] → 落款 → 日期 → [附件页]+

        body → [attachment_note → item*] → sign_org → sign_date → [page_mark → title → body*]*

        返回 (type_id, meta, prefix, fixed_text) 或 (None, {}, "", orig_text)
    """
    text = line.strip()
    next_text = next_line.strip() if next_line else ""

    if _RESPONSIBILITY_LINE_RE.match(text):
        return "responsibility_line", {"colon_bold": True}, "", _normalize_responsibility_line(text)

    # 1. 附件说明：上一段必须是正文
    m = _ATT_NOTE_RE.match(text)
    if m and _can_start_attachment_note(ctx):
        had_signature_complete = ctx.signature_complete
        body = m.group(1).strip()
        first_no = re.match(r"^(\d+)[.．、]\s*", body)
        next_is_item = bool(_ATT_ITEM_RE.match(next_text)) or _is_auto_numbered_item(next_feats)

        # 空"附件："无内容且无续行 → 不识别
        if not body and not next_is_item:
            return None, {}, "", text

        if first_no and next_is_item:
            # A: 多附件，规范空格：附件：1.基本情况 → 附件：1. 基本情况
            is_multi = True
            ctx.attachment_note_next_no = int(first_no.group(1)) + 1
            fixed_text = re.sub(
                r"^\s*附件\s*[:：]\s*(\d+)[.．、]\s*",
                lambda x: f"附件：{x.group(1)}. ",
                text, count=1)
        elif first_no and not next_is_item:
            # B: 首行有 1. 但下一行不是编号 → 单附件，去掉编号
            is_multi = False
            ctx.attachment_note_next_no = 1
            body_no = re.sub(r"^\d+[.．、]\s*", "", body, count=1).strip()
            fixed_text = f"附件：{body_no}"
        elif not first_no and next_is_item:
            # C: 首行无编号但下一行有 → 补 1.
            is_multi = True
            ctx.attachment_note_next_no = 2
            fixed_text = f"附件：1. {body}"
        else:
            # D: 单附件
            is_multi = False
            ctx.attachment_note_next_no = 1
            fixed_text = text

        ctx.attachment_note_seen = True
        ctx.attachment_note_mode = is_multi
        ctx.signature_seen = had_signature_complete
        ctx.signature_complete = had_signature_complete
        _record_structural(ctx, "attachment_note", fixed_text)
        return "attachment_note", {"attachment_single": not is_multi,
                                    "attachment_multi": is_multi}, "", fixed_text

    # 2. 附件续行：已进入附件说明块，且当前段是编号项；自动修正序号
    m2 = _ATT_ITEM_RE.match(text)
    is_auto_item = _is_auto_numbered_item(feats)
    if ctx.attachment_note_mode and ctx.attachment_note_seen and (m2 or is_auto_item):
        if m2:
            fixed = re.sub(r"^\s*\d+[.．、]\s*", f"{ctx.attachment_note_next_no}. ", text, count=1)
        else:
            fixed = f"{ctx.attachment_note_next_no}. {text.strip()}"
        ctx.attachment_note_next_no += 1
        _record_structural(ctx, "attachment_note_item", fixed)
        return "attachment_note_item", {}, "", fixed

    # 3. 落款单位：上段是 body / attachment_note / item，且下一行是日期
    if ctx.last_structural_type in ("body", "attachment_note", "attachment_note_item"):
        if _looks_like_sign_org(text, next_text, ctx):
            ctx.attachment_note_mode = False
            ctx.signature_seen = True
            fixed = _norm_sign_org(text)
            _record_structural(ctx, "sign_org", fixed)
            return "sign_org", {}, "", fixed

    # 4. 成文日期：紧接落款单位之后，自动规范化
    if ctx.last_structural_type == "sign_org" and _SIGN_DATE_RE2.match(text):
        ctx.signature_complete = True
        fixed = _norm_sign_date(text)
        _record_structural(ctx, "sign_date", fixed)
        return "sign_date", {}, "", fixed

    # 4b. 独立尾部日期：正文后、非附件页内，且后续只接附件边界或已到文末
    if (ctx.has_seen_real_body and not ctx.attachment_page_mode
            and _SIGN_DATE_RE2.match(text)
            and (not next_text or _is_attachment_boundary(next_text))
            and not _blocks_independent_sign_date(ctx)):
        ctx.attachment_note_mode = False
        ctx.signature_seen = True
        ctx.signature_complete = True
        fixed = _norm_sign_date(text)
        _record_structural(ctx, "sign_date", fixed)
        return "sign_date", {}, "", fixed

    # 5. 附件正文页标识：由附件说明或成文日期形成强边界，不再依赖二者同时存在
    if ((ctx.attachment_note_seen or ctx.signature_complete or ctx.attachment_page_mode)
            and ctx.last_structural_type in ("sign_date", "attachment_note", "attachment_note_item",
                                             "attachment_body", "attachment_title")
            and _is_attachment_page_mark(text)):
        ctx.attachment_page_mode = True
        fixed = _norm_attach_mark(text)
        _record_structural(ctx, "attachment_page_mark", fixed)
        return "attachment_page_mark", {}, "", fixed

    # 6. 附件标题：附件页标识后 + 短句(<28字) + 无编号无冒号 → 标题
    if (ctx.last_structural_type == "attachment_page_mark" and ctx.attachment_page_mode
            and len(text) <= 28 and not _contains_colon(text)):
        tid, _ = _match_numbering(text)
        if not tid:
            _record_structural(ctx, "attachment_title", text)
            return "attachment_title", {}, "", text

    # 7. 附件正文：附件页内，不满足标题条件 → 走正常分类
    if ctx.attachment_page_mode and ctx.last_structural_type in ("attachment_title", "attachment_body", "attachment_page_mark"):
        ctx.has_seen_real_body = True  # 确保 scorer 的 has_seen_body 条件通过
        # 不 return，让 detect_paragraph_type 正常分类

    return None, {}, "", text


# ── 编号正则（仅匹配，不决策）──

_HEADING_RE = [
    (re.compile(r'^[一二三四五六七八九十百]+、'),           "heading1"),
    (re.compile(r'^[（\(][一二三四五六七八九十百]+[）\)]'), "heading2"),
    (re.compile(r'^\d+[.．]'),                            "heading3"),
    (re.compile(r'^[（\(]\d+[）\)]'),                      "heading4"),
]

# ── 一是/二要/比如 ──
_NB_RE = re.compile(rf'[一二三四五六七八九十]+(?:{"|".join(NB_SUFFIXES)})')
_NB_FIXED_RE = re.compile(rf'^(?:{"|".join(map(re.escape, NB_FIXED))})') if NB_FIXED else None


def _normalize_text(text: str) -> str:
    """统一括号 + 去零宽/全角空格（仅中文语境转换括号）。"""
    text = re.sub(r'\(([\u4e00-\u9fff][^)]*[\u4e00-\u9fff])\)', r'（\1）', text)
    text = re.sub(r'[\u200b\u3000\u00a0]', '', text)
    return text


def _to_chinese_punctuation(text: str) -> str:
    """英文标点 → 中文标点（仅中文语境，避免误伤 URL、时间、金额、缩写）。"""
    if not text:
        return text
    text = re.sub(r'(?<=[\u4e00-\u9fff])[:：]\s*', '：', text)
    text = re.sub(r'(?<=[\u4e00-\u9fff]),\s*', '，', text)
    text = re.sub(r'(?<=[\u4e00-\u9fff0-9]);\s*', '；', text)
    text = re.sub(r'(?<=[\u4e00-\u9fff])\?', '？', text)
    text = re.sub(r'(?<=[\u4e00-\u9fff])!', '！', text)
    text = re.sub(r'(?<=[\u4e00-\u9fff])\.(?=$|[\s\u4e00-\u9fff])', '。', text)
    return text


def _normalize_quotes(text: str) -> str:
    """英文引号 → 中文引号。避免误伤英文单词内部的撇号（O'Reilly, don't）。"""
    if not text:
        return text
    # 1. 双单引号作双引号：''text'' → "text"
    text = re.sub(r"''(?=\S)", '\u201c', text)
    text = re.sub(r"(?<=\S)''", '\u201d', text)
    # 2. 半角双引号 → 全角（奇数位左引号，偶数位右引号）
    parts = text.split('"')
    if len(parts) > 1:
        result = [parts[0]]
        for i in range(1, len(parts)):
            result.append('\u201c' if i % 2 == 1 else '\u201d')
            result.append(parts[i])
        text = ''.join(result)
    # 3. 半角单引号：只处理中文语境，避免 O'Reilly / don't
    text = re.sub(r"(?<![A-Za-z])'(?=[\u4e00-\u9fff])", '\u2018', text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])'(?![A-Za-z])", '\u2019', text)
    return text


def _feature_bool(value, default: bool = False) -> bool:
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on", "启用", "是"}:
        return True
    if raw in {"0", "false", "no", "off", "禁用", "否"}:
        return False
    return default


def _contains_colon(text: str) -> bool:
    return '：' in text or ':' in text


def _colon_bold_match(text: str):
    """冒号关键词加粗：含冒号+不在段末+前缀≤10字无标点+整段≤28字。返回冒号位置或 -1。"""
    if not text or len(text) > 28 or text.rstrip().endswith(('：', ':')):
        return -1
    for colon in ('：', ':'):
        pos = text.find(colon)
        if 0 < pos <= 10 and not re.search(r'[，。、；]', text[:pos]):
            return pos
    return -1


def _find_numbered_bold_pos(text: str) -> int:
    """X是/X要/比如 命中检测。返回首次匹配索引，-1 为无。"""
    text = _normalize_text(text)
    if _NB_FIXED_RE and _NB_FIXED_RE.search(text):
        return _NB_FIXED_RE.search(text).start()
    m = _NB_RE.search(text)
    return m.start() if m else -1


def _looks_like_heading(text: str) -> bool:
    """OCR 损坏标题检测。"""
    text = text.strip()
    if len(text) > 30 or re.search(r'[。；：]', text[:10]):
        return False
    if re.match(r'^([一二三四五六七八九十百]+)[，,、\s]', text):
        return True
    if re.match(r'^[）\)][一二三四五六七八九十百]+', text):
        return True
    if re.match(r'^[（\(][一二三四五六七八九十百]+', text) and len(text) <= 15:
        return True
    return False


# ── 提取编号前缀（供 strip_numbering）──

def _match_numbering(text: str):
    """返回 (type_id, prefix) 或 (None, None)。"""
    text_norm = _normalize_text(text)
    for pat, tid in _HEADING_RE:
        m = pat.match(text_norm)
        if m:
            if tid == "heading4" and _contains_colon(text_norm):
                continue  # heading4 含冒号 → 过滤
            return tid, m.group(0)
    return None, None


def _match_style_or_lvl(text: str, feats):
    """Word 样式/多级列表 → 返回 (type_id, prefix)。"""
    if not feats:
        return None, None
    # "一是/一要/比如："这类正文强调句即使被 Word 误挂了自动编号，也不按标题处理。
    if _find_numbered_bold_pos(text) == 0:
        return None, None
    # Word 多级列表标记为 heading2，但文本是长正文（>25字含标点）→ 不按标题处理
    if feats.numbering_prefix.startswith("@lvl_0") and len(text) > 25:
        if re.search(r'[、，；]', text):
            return None, None
    # @lvl_N 自动编号：从提取到的 Word 多级列表层级直接映射
    if feats.numbering_prefix.startswith("@lvl_"):
        try:
            lvl = int(feats.numbering_prefix[5:])
            return f"heading{min(lvl + 2, 4)}", ""
        except ValueError:
            pass
    # @style_ 样式映射
    if feats.numbering_prefix.startswith("@style_"):
        return feats.numbering_prefix[7:], ""
    return None, None


# ═══════════════════════════════════════════════════════════════
# Scorer 层：每个类型独立打分函数（按优先级 ①~⑲ 排列）
# ═══════════════════════════════════════════════════════════════

def _score_01_title(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """① title（方正小标宋 二号 居中）：文档第一段 + <60字 + 无编号无冒号。"""
    if ctx.has_seen_body:
        return 0, {}, ""
    if ctx.para_index != 0:  # 仅第一段
        return 0, {}, ""
    # 含文种关键词放宽到 60 字
    _TITLE_KW = '对照检查|述职报告|工作总结|工作计划|实施方案|提纲|发言稿|主持词|致辞|讲话稿|汇报材料|调研报告'
    max_len = 60 if re.search(_TITLE_KW, text) else 40
    if len(text) >= max_len:
        return 0, {}, ""
    if _contains_colon(text):
        return 0, {}, ""
    tid, _ = _match_numbering(text)
    if tid:
        return 0, {}, ""
    if text.startswith('（'):
        return 0, {}, ""
    return 100, {"is_title": True}, ""


def _score_02_title_cont(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """② title续行：头部区域内 + 短行 + 无特征，兜底为标题续行。"""
    if ctx.has_seen_body:
        return 0, {}, ""
    # 上段是标题/日期/作者时，短行可能是标题续行（role_name 之后不再续）
    if ctx.prev_type_id not in ("title", "title_cont", "date_line", "author_line"):
        return 0, {}, ""
    if len(text) >= 40:
        return 0, {}, ""
    if _contains_colon(text):
        return 0, {}, ""
    tid, _ = _match_numbering(text)
    if tid:
        return 0, {}, ""
    if text.startswith('（'):
        return 0, {}, ""
    if re.search(r'\S\s{2,}\S', text):  # 含连续空格 → 留给职务人名
        return 0, {}, ""
    # 含文种关键词 → 必然是标题（如 "对照检查材料"），不避让 date_line
    _TITLE_KW = '对照检查|述职报告|工作总结|工作计划|实施方案|提纲|发言稿|主持词|致辞|讲话稿|汇报材料|调研报告'
    if re.search(_TITLE_KW, text):
        return 90, {}, ""
    # 含年份或日期特征 → 留给 date_line（但以上文种关键词优先）
    if re.search(r'\d{4}年', text):
        return 0, {}, ""
    return 90, {}, ""


def _score_03_date_line(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """③ 日期行（楷体 居中）：上段 title/续行/署名 + 括号开头或含年份 + <50字。"""
    if ctx.has_seen_body:
        return 0, {}, ""
    if ctx.prev_type_id not in ("title", "title_cont", "role_name", "author_line"):
        return 0, {}, ""
    tid, _ = _match_numbering(text)
    if tid:
        return 0, {}, ""
    if len(text) >= 50:  # 长段落如"按照《中共四川省纪委...》"不是日期行
        return 0, {}, ""
    # 含文种关键词 → 不是日期行，是标题（如 "2025年度民主生活会对照检查材料"）
    _TITLE_KW = '对照检查|述职报告|工作总结|工作计划|实施方案|提纲|发言稿|主持词|致辞|讲话稿|汇报材料|调研报告'
    if re.search(_TITLE_KW, text):
        return 0, {}, ""
    is_date = text.startswith('（') or re.search(r'\d{4}年', text)
    if not is_date:
        return 0, {}, ""
    return 85, {}, ""


def _score_04_author_line(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """④ 署名行（楷体 加粗 居中）：上段是日期行 + <20字 + 无编号无冒号 + 无连续空格。"""
    if ctx.has_seen_body:
        return 0, {}, ""
    if ctx.prev_type_id != "date_line":  # 仅在日期行之后
        return 0, {}, ""
    if len(text) >= 20:
        return 0, {}, ""
    if _contains_colon(text):
        return 0, {}, ""
    tid, _ = _match_numbering(text)
    if tid:
        return 0, {}, ""
    if text.startswith(('（', *_REPORT_HEADING_STARTS, '各位委员', '各位同志')):
        return 0, {}, ""
    if re.search(r'\S\s{2,}\S', text):  # 含连续空格 → 留给职务人名
        return 0, {}, ""
    return 80, {}, ""


def _score_05_role_name(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑤ 职务署名（楷体 加粗）：上段 title/续行 + <20字 + 含空格或职务关键词。"""
    if ctx.has_seen_body:
        return 0, {}, ""
    if ctx.prev_type_id not in ("title", "title_cont", "date_line", "author_line"):
        return 0, {}, ""
    role_name_match = re.fullmatch(r"[\u4e00-\u9fff、，,·]{2,28}\s{2,}[\u4e00-\u9fff·]{2,6}", text)
    if len(text) >= 20 and not role_name_match:
        return 0, {}, ""
    if _contains_colon(text):
        return 0, {}, ""
    # 含连续空格 → 署名（如 "韩 双 林"）
    if role_name_match or re.search(r'\S\s{2,}\S', text):
        return 80, {}, ""
    # 含职务关键词 → 署名/职务行
    _ROLE_KW = ('局长|主任|书记|主席|部长|处长|科长|司长|厅长|市长|县长'
                '|区长|镇长|乡长|院长|校长|政委|总工|组长|队长|秘书长'
                '|委员|常委|召集人|负责人|联系人|审定人|审核人|签发人')
    if re.search(_ROLE_KW, text):
        return 80, {}, ""
    # 上段标题含文种关键词（汇报/总结/方案/报告）→ 当前短行大概率是署名
    _DOC_TYPE_KW = ('对照检查|述职报告|工作总结|工作计划|实施方案|提纲|发言稿'
                     '|主持词|致辞|讲话稿|汇报材料|调研报告'
                     '|汇报|总结|方案|报告|要点|计划|规划|意见|通知|通报'
                     '|请示|批复|函|纪要|公报|条例|规定|办法|细则')
    prev_title = ctx.title_texts[-1] if ctx.title_texts else ""
    # 发言/讲话类材料常见头部为“标题 → 姓名 → 日期”，姓名通常是 2-4 个中文字符。
    if (re.search(r'发言|讲话|致辞|主持词', prev_title)
            and re.fullmatch(r'[\u4e00-\u9fff]{2,6}', text)):
        return 92, {}, ""
    if re.search(_DOC_TYPE_KW, prev_title) and len(text) < 20 and not _contains_colon(text):
        return 75, {}, ""
    return 0, {}, ""


def _score_06_heading1_cn(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑥ heading1（黑体 左对齐 有编号）：^一、~^二十、，但跳过报告模式的回顾类标题。"""
    tid, prefix = _match_numbering(text)
    if tid != "heading1":
        return 0, {}, ""
    # REPORT 模式：编号后紧跟回顾类标题 → 留给 heading1_report 处理（无编号）
    mode = ctx.doc_mode or _detect_doc_type(ctx)
    if mode == "REPORT":
        stripped = text[len(prefix):].lstrip()
        if stripped.startswith(_REPORT_HEADING_STARTS):
            return 0, {}, ""
    return 100, {}, prefix


def _score_07_heading2_cn(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑦ heading2（楷体 加粗 左对齐）：^（一）~^（二十）"""
    tid, prefix = _match_numbering(text)
    if tid != "heading2":
        return 0, {}, ""
    return 100, {}, prefix


def _score_08_heading3_digit(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑧ heading3（仿宋 左对齐）：^1.~"""
    tid, prefix = _match_numbering(text)
    if tid != "heading3":
        return 0, {}, ""
    return 90, {}, prefix


def _score_09_heading4_digit(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑨ heading4（仿宋 左对齐 无冒号）：^（1）~"""
    tid, prefix = _match_numbering(text)
    if tid != "heading4":
        return 0, {}, ""
    if _contains_colon(text):
        return 0, {}, ""
    return 90, {}, prefix


def _score_10_heading1_report(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑩ heading1 报告回顾类标题（黑体 左对齐）：段首或编号后接"一年来/五年来"。"""
    # 可能带编号前缀如"一、 一年来" / "一、 五年来"
    tid, prefix = _match_numbering(text)
    body = text[len(prefix):].lstrip() if prefix else text
    if not body.startswith(_REPORT_HEADING_STARTS):
        return 0, {}, ""
    # 拆句号：标题部分 + body 续文（引擎侧换行渲染）
    period = text.find('。')
    heading_part = text[:period] if period > 0 else text
    if len(heading_part) > 50:  # 标题部分过长 → 回退为 body
        return 0, {}, ""
    return 95, {"heading1_report_split": period > 0}, prefix if prefix else ""


def _score_11_title2(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑪ title2（黑体 居中）：has_body(或 REPORT 模式) + <28字 + 非报告回顾/称呼 + 无冒号 + 无编号 + 无句号。"""
    doc_mode = ctx.doc_mode or _detect_doc_type(ctx)
    if not ctx.has_seen_body and doc_mode != "REPORT":
        return 0, {}, ""
    if len(text) >= 28:
        return 0, {}, ""
    if _contains_colon(text):
        return 0, {}, ""
    if text.startswith((*_REPORT_HEADING_STARTS, '各位委员', '各位同志')):
        return 0, {}, ""
    tid, _ = _match_numbering(text)
    if tid:
        return 0, {}, ""
    # date_line 之后 → 留给 author_line
    if ctx.prev_type_id == "date_line":
        return 0, {}, ""
    # 含句号 → 这是正文句子，不是标题
    if '。' in text:
        return 0, {}, ""
    # "名词解释" → glossary_title
    if '名词解释' in text or '注释' in text:
        return 95, {}, ""
    return 95, {}, ""


def _score_glossary_title(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """glossary_title（方正小标宋 二号 居中）：title2 命中且含"名词解释"。"""
    score, m, p = _score_11_title2(text, feats, ctx)
    if score > 0 and ('名词解释' in text or '注释' in text):
        return score, m, p
    return 0, {}, ""


def _score_glossary_item(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """glossary_item：glossary_mode 下含冒号段落 → 自动编号 + 关键词黑体加粗+正文仿宋。"""
    if not ctx.glossary_mode:
        return 0, {}, ""
    # 先检查是否有显式编号（1. / 2. 等）
    tid, prefix = _match_numbering(text)
    if tid == "heading3":
        body = text[len(prefix):].lstrip()
    else:
        # 无显式编号：只要含冒号且不是极短文本，就认定为 glossary_item
        if not _contains_colon(text) or len(text) < 4:
            return 0, {}, ""
        prefix = ""  # 自动编号，不加 prefix
        body = text
    # 找到冒号位置
    cp = -1
    for c in ('：', ':'):
        cp = body.find(c)
        if cp > 0:
            break
    return 90, {"glossary_item": True, "colon_pos": cp if cp > 0 else -1}, prefix


def _score_12_addressing_report(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑫ addressing 报告"各位委员"（仿宋 两端对齐 缩进2字）。仅匹配短句。"""
    if not text.startswith(("各位委员", "各位同志")):
        return 0, {}, ""
    if len(text) > 25:  # 长段如"各位委员...一年来..."是正文，不是纯称呼
        return 0, {}, ""
    return 120, {"no_indent": False}, ""


def _score_13_addressing_check(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑬ addressing 对照检查主送（仿宋 左对齐 0缩进）：heading后第一段 + 冒号结尾。"""
    if not ctx.prev_type_id.startswith("heading"):
        return 0, {}, ""
    if not text.rstrip().endswith(("：", ":")):
        return 0, {}, ""
    return 110, {"no_indent": True}, ""





def _score_16_body_default(text: str, feats, ctx) -> Tuple[int, dict, str]:
    """⑲ body 兜底：仿宋 两端对齐 缩进2字。"""
    return 10, {}, ""


# ── 骨架层（任何文种都跑，永远不变）──

_STRUCTURE_SCORERS: List[Tuple[str, callable]] = [
    ("title",              _score_01_title),
    ("title_cont",         _score_02_title_cont),
    ("date_line",          _score_03_date_line),
    ("author_line",        _score_04_author_line),
    ("role_name",          _score_05_role_name),
    ("heading1",           _score_06_heading1_cn),
    ("heading2",           _score_07_heading2_cn),
    ("heading3",           _score_08_heading3_digit),
    ("heading4",           _score_09_heading4_digit),
]

# ── 文种覆盖层（mode 锁定后追加到骨架之后）──

_MODE_SCORERS: Dict[str, List[Tuple[str, callable]]] = {
    "NORMAL": [
        ("addressing",     _score_13_addressing_check),
    ],
    "REPORT": [
        ("heading1_report", _score_10_heading1_report),
        ("glossary_title", _score_glossary_title),
        ("title2",         _score_11_title2),
        ("addressing",     _score_12_addressing_report),
        ("glossary_item",  _score_glossary_item),
    ],
}

# ── 兜底层（所有文种通用）──

_FALLBACK_SCORERS: List[Tuple[str, callable]] = [
    ("body",               _score_16_body_default),
]


def _detect_doc_type(ctx) -> str:
    """从头部标题文字检测文种。仅在 has_seen_body 首次变为 True 时调用一次。"""
    combined = " ".join(ctx.title_texts)
    if "报告" in combined or "工作回顾" in combined:
        return "REPORT"
    return "NORMAL"


# ═══════════════════════════════════════════════════════════════
# Flow 层：显式状态机
# ═══════════════════════════════════════════════════════════════

# 上段类型 → 允许的下一段类型（None 表示文档开头）
FLOW = {
    None:               ["title", "addressing", "heading1", "body"],
    "title":            ["title_cont", "date_line", "author_line", "role_name", "addressing", "heading1"],
    "title_cont":       ["title_cont", "date_line", "author_line", "role_name", "addressing", "heading1", "title2"],
    "date_line":        ["author_line", "addressing", "heading1", "heading2", "title2", "body"],
    "author_line":      ["addressing", "heading1", "heading2", "title2", "body"],
    "role_name":        ["date_line", "addressing", "heading1", "heading2", "title2", "body"],
    "heading1":         ["heading1", "heading2", "heading3", "body", "addressing", "title2"],
    "heading1_report":  ["heading2", "heading3", "body", "addressing", "title2"],
    "heading2":         ["heading1", "heading2", "heading3", "heading4", "body", "addressing", "title2", "glossary_title"],
    "heading3":         ["heading1", "heading2", "heading3", "heading4", "body", "addressing", "title2", "glossary_title"],
    "heading4":         ["heading1", "heading2", "heading3", "heading4", "body", "addressing", "title2", "glossary_title"],
    "addressing":       ["heading1", "heading2", "title2", "body"],
    "title2":           ["heading1", "heading2", "body", "addressing", "title2"],
    "glossary_title":   ["glossary_item", "body"],
    "glossary_item":    ["glossary_item", "body", "title2"],
    "body":             ["heading1", "heading2", "heading3", "heading4", "title2", "glossary_title", "addressing", "body",
                         "attachment_note", "sign_org"],
    "attachment_note":  ["attachment_note_item", "sign_org"],
    "attachment_note_item": ["attachment_note_item", "sign_org"],
    "attachment_page_mark": ["attachment_title"],
    "attachment_title": ["attachment_body"],
    "attachment_body":  ["attachment_body", "attachment_page_mark", "heading1", "heading2", "heading3", "heading4"],
    "sign_org":         ["sign_date"],
    "sign_date":        ["attachment_page_mark", "body"],
}


def _flow_allows(candidate: str, ctx) -> bool:
    """候选类型是否被当前上下文允许。"""
    prev = ctx.prev_type_id if ctx.prev_type_id else None
    allowed = FLOW.get(prev, [])
    if not allowed:
        return True
    if candidate in allowed:
        return True
    # heading1_report 映射到 "heading1"
    if candidate in ("heading1", "heading1_report") and "heading1" in allowed:
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# Repair 层
# ═══════════════════════════════════════════════════════════════

def _repair_level(type_id: str, feats, ctx) -> str:
    """跳级修复：heading1→heading4 不允许，提级为 heading2。"""
    if not type_id.startswith("heading"):
        return type_id
    if type_id == "heading1_report":
        return type_id  # 报告 heading1 不走跳级修复
    lvl = int(type_id[-1])
    expected = ctx.current_level + 1
    if lvl > expected:
        capped = f"heading{expected}" if expected <= 4 else type_id
        if capped != type_id:
            logger.debug(f"[修复] 跳级 {type_id}→{capped}")
        return capped
    return type_id


def _repair_heading4_colon(type_id: str, text: str, feats, ctx) -> str:
    """heading4 + 含冒号 → 回退为 body。"""
    if type_id == "heading4" and _contains_colon(text):
        logger.debug(f"[修复] heading4 含冒号→body: '{text[:30]}'")
        return "body"
    return type_id


# ═══════════════════════════════════════════════════════════════
# 主入口：classify（替代 detect_paragraph_type）
# ═══════════════════════════════════════════════════════════════

def detect_paragraph_type(text: str, feats: ParagraphFeatures,
                          ctx: DetectionContext,
                          rules: List[StyleRule]) -> Tuple[str, dict, str]:
    """v3 统一分类器：按 19 步优先级遍历 scorer → Flow 约束 → Repair。

    返回 (type_id, meta_patch, prefix)，与原接口完全兼容。
    """
    ctx.para_index = feats.paragraph_index
    meta: dict = {}
    prefix: str = ""
    from_word_structure = False
    score_log = []  # 收集各 scorer 得分

    # ── 先检查 Word 样式/多级列表 ──
    style_tid, style_prefix = _match_style_or_lvl(text, feats)
    if style_tid:
        type_id = style_tid
        prefix = style_prefix
        from_word_structure = True
    else:
        # ── ① 骨架层 → ② 文种覆盖层 → ③ 兜底层 ──
        type_id = "body"
        best_score = -1

        # 第一遍：骨架层 scorer
        for tid, scorer in _STRUCTURE_SCORERS:
            score, m, p = scorer(text, feats, ctx)
            if score > 0:
                score_log.append(f"{tid}:{score}")
            if score > best_score and score > 0 and _flow_allows(tid, ctx):
                best_score, type_id, meta, prefix = score, tid, m, p

        # 第二遍：文种覆盖层（提前检测 mode，确保首段也生效）
        mode = ctx.doc_mode or _detect_doc_type(ctx)
        if mode:
            for tid, scorer in _MODE_SCORERS.get(mode, []):
                score, m, p = scorer(text, feats, ctx)
                if score > best_score and score > 0 and _flow_allows(tid, ctx):
                    best_score, type_id, meta, prefix = score, tid, m, p

        # 第三遍：兜底层
        if best_score < 0:
            for tid, scorer in _FALLBACK_SCORERS:
                score, m, p = scorer(text, feats, ctx)
                if score > best_score and _flow_allows(tid, ctx):
                    best_score, type_id, meta, prefix = score, tid, m, p

    # ── Repair ──
    type_id = _repair_heading4_colon(type_id, text, feats, ctx)
    if not from_word_structure:
        type_id = _repair_level(type_id, feats, ctx)

    # ── OCR 标题容错 ──
    if type_id == "body" and _looks_like_heading(text) and not ctx.has_seen_body:
        type_id = "heading1"
        logger.debug(f"[修复] OCR 标题升级: '{text[:30]}'")

    # ── 打分日志 ──
    scores_str = ' → '.join(score_log) if score_log else 'by_style'
    logger.info(f"[打分] \"{text[:28]}\" | {scores_str} → {type_id}")

    # ── heading2 续行修复：前段 heading2 + 短句含句号 → 缺编号的 heading2 ──
    if type_id == "body" and ctx.prev_type_id == "heading2" and len(text) <= 30 and text.endswith('。'):
        type_id = "heading2"
        meta["heading2_cont"] = True  # 不自动编号
        logger.debug(f"[修复] heading2 续行: '{text[:30]}'")

    # ── Meta 补充：body 内部加粗标记 ──
    if type_id in ("heading1", "heading2") and _heading_has_inline_body(text):
        # 方案模式二级标题不拆分，整段保留
        if not (type_id == "heading2" and ctx.doc_mode == "SCHEME"):
            meta["heading_inline_body"] = True

    if type_id == "body":
        if _find_numbered_bold_pos(text) >= 0:
            meta["numbered_bold"] = True
        cp = _colon_bold_match(text)
        if cp >= 0:
            meta["colon_bold"] = True
        # 报告首句加粗（current_level==1 + 首句≤30字 + 非报告回顾/称呼）。
        # 一是/二是/三是类段落已有 numbered_bold，避免两套 run 重写规则叠加。
        if (ctx.current_level == 1 and not meta.get("numbered_bold")
                and not text.startswith((*_REPORT_HEADING_STARTS, '各位委员', '各位同志'))):
            period = text.find('。')
            if 0 < period <= 26:  # 首句≤26字加粗
                meta["report_first_sentence_bold"] = True

    if text.endswith(("：", ":")):
        meta["no_indent"] = True

    # ── 更新上下文 ──
    ctx.prev_type_id = type_id

    # 附件/落款 结构状态跟踪
    if type_id in ("body", "addressing", "responsibility_line"):
        ctx.has_seen_real_body = True
        _record_structural(ctx, "body", text)
    elif type_id in ("attachment_note", "attachment_note_item",
                      "attachment_page_mark", "attachment_title",
                      "attachment_body", "sign_org", "sign_date"):
        _record_structural(ctx, type_id, text)
    elif type_id.startswith("heading") or type_id in ("title", "title2"):
        _record_structural(ctx, "body" if meta.get("heading_inline_body") else type_id, text)

    # 成文日期后重置附件页内状态，允许多个附件
    if type_id == "sign_date":
        ctx.signature_complete = True
        ctx.attachment_page_mode = False

    # 头部区域：收集标题文字
    if not ctx.has_seen_body and type_id in ("title", "title_cont"):
        ctx.title_texts.append(text)

    if type_id.startswith("heading"):
        ctx.has_seen_heading = True
        if not ctx.has_seen_body:
            ctx.has_seen_body = True
            ctx.doc_mode = _detect_doc_type(ctx)
        if type_id == "heading1_report":
            ctx.current_level = 1
        else:
            ctx.current_level = int(type_id[-1])
    elif type_id == "title2":
        ctx.has_seen_heading = True
        # title2 不设 current_level，首句加粗仅在 heading1_report 后触发
    elif type_id == "glossary_title":
        ctx.glossary_mode = True
        ctx.has_seen_body = True
    elif type_id in ("title", "title_cont", "date_line", "author_line", "role_name"):
        pass  # 头部区域，不设 has_seen_body
    elif type_id in ("body", "addressing", "responsibility_line"):
        if not ctx.has_seen_body:
            ctx.has_seen_body = True
            ctx.doc_mode = _detect_doc_type(ctx)  # 锁定文种

    logger.debug(f"[决策] para={ctx.para_index} → {type_id} meta={meta}")
    return type_id, meta, prefix


# ═══════════════════════════════════════════════════════════════
# 编号剥离
# ═══════════════════════════════════════════════════════════════

def strip_numbering(text: str, prefix: Optional[str] = None) -> str:
    """剥离编号前缀 + 清理残留多余标点（如 "4..xxx" → "xxx"）。"""
    # 自动编号补标：@lvl_N:text → 剥离 @lvl_N: 部分
    if text.startswith('@lvl_'):
        colon = text.find(':')
        if colon > 0:
            return text[colon+1:].strip()
    if prefix:
        text = text[len(prefix):]
    else:
        # 兜底正则
        for pat, _ in _NUMBERING_PATTERNS:
            text = pat.sub('', text, count=1)
    # 清理残留的多余标点（如 ".还需优化" → "还需优化"）
    text = re.sub(r'^[.．、，,]\s*', '', text)
    return text.strip()


def _key_to_row(key: str) -> int:
    return {"a": 1, "b": 2, "c": 3, "d": 4}.get(key, 5)  # row 0=主标题, row 5=正文


# ═══════════════════════════════════════════════════════════════
# 导入器
# ═══════════════════════════════════════════════════════════════

def _repair_broken_rels(filepath: str) -> str:
    """修复 .docx 中的损坏关系引用（如 Target="../NULL"）。

    常见于 WPS / 在线工具生成的文档。返回修复后的临时文件路径。
    """
    import zipfile as _zipfile
    import re as _re
    import tempfile as _tempfile

    # 检查是否需要修复
    need_fix = False
    try:
        with _zipfile.ZipFile(filepath, 'r') as z:
            if 'word/_rels/document.xml.rels' in z.namelist():
                content = z.read('word/_rels/document.xml.rels').decode('utf-8')
                if _re.search(r'Target="\.\./NULL"', content):
                    need_fix = True
    except Exception:
        return filepath

    if not need_fix:
        return filepath

    logger.info("[修复] 检测到损坏引用 Target=\"../NULL\"，自动修复…")
    tmp = _tempfile.NamedTemporaryFile(delete=False, suffix='.docx')
    tmp.close()

    try:
        with _zipfile.ZipFile(filepath, 'r') as zin:
            with _zipfile.ZipFile(tmp.name, 'w', _zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == 'word/_rels/document.xml.rels':
                        content = data.decode('utf-8')
                        fixed = _re.sub(
                            r'<Relationship[^>]*Target="\.\./NULL"[^>]*/>',
                            '', content
                        )
                        data = fixed.encode('utf-8')
                    zout.writestr(item, data)
        logger.info(f"[修复] 完成 → {tmp.name}")
        return tmp.name
    except Exception as e:
        logger.warning(f"[修复] 失败: {e}")
        return filepath


class DocxImporter:
    """.docx 文件导入器。"""

    def load(self, filepath: str, rules: List[StyleRule], features: dict = None) -> DocumentData:
        """加载 .docx，识别段落类型，返回 DocumentData。"""
        try:
            from docx import Document as DocxDocument
        except ImportError:
            raise ImportError("请安装 python-docx: pip install python-docx")

        features = features or {}
        punctuation_options = features.get("punctuation", {}) if isinstance(features.get("punctuation", {}), dict) else {}
        new_punctuation_enabled = _feature_bool(punctuation_options.get("enabled", False), False)
        punctuation_mode = str(punctuation_options.get("mode", "safe") or "safe")
        punctuation_enabled = _feature_bool(features.get("punctuation_enabled", True), True)

        def normalize_text(text: str) -> str:
            if not text:
                return text
            if new_punctuation_enabled:
                from docxtool.document.engine.punctuation import normalize_punctuation_text

                return normalize_punctuation_text(text, mode=punctuation_mode)
            if punctuation_enabled:
                return _to_chinese_punctuation(_normalize_quotes(text))
            return text

        def normalize_tokens(tokens: List[InlineToken]) -> List[InlineToken]:
            normalized = _normalize_inline_tokens(tokens, punctuation_enabled and not new_punctuation_enabled)
            if not new_punctuation_enabled:
                return normalized
            return [
                InlineToken(token.kind, normalize_text(token.text)) if token.kind == "text" else token
                for token in normalized
            ]

        # 自动修复损坏的 .rels 引用
        filepath = _repair_broken_rels(filepath)

        try:
            doc = DocxDocument(filepath)
        except Exception as e:
            raise ImportError(f"无法打开文件 {filepath}: {e}")

        data = DocumentData(filepath=filepath)
        from docxtool.document.engine.letterhead import detect_letterhead

        data.letterhead_detection = detect_letterhead(doc)
        protected_letterhead_indexes = set(data.letterhead_detection.protected_body_indexes)

        # 第一步：按 Word body XML 顺序提取段落、表格、图片段落。
        from docx.text.paragraph import Paragraph as DocxParagraph
        from docx.table import Table as DocxTable
        from docx.oxml.ns import qn as _qn_body

        data.even_and_odd_headers = copy.deepcopy(
            doc.settings._element.find(_qn_body("w:evenAndOddHeaders"))
        )

        raw_blocks = []
        para_index = 0
        body_index = 0
        for child in doc._body._element.iterchildren():
            if child.tag == _qn_body('w:p'):
                para = DocxParagraph(child, doc._body)
                pf = extract_features(para, para_index)
                inline_tokens = extract_inline_tokens(para)
                sectPr = extract_paragraph_sectPr(para)
                collect_section_header_footer_parts(doc, sectPr, data)
                para_index += 1
                if body_index in protected_letterhead_indexes:
                    raw_blocks.append(("letterhead_paragraph_xml", para))
                elif pf.contains_image:
                    raw_blocks.append(("paragraph_xml", para))
                elif para.text.strip() or sectPr is not None or any(token.kind == "page_break" for token in inline_tokens):
                    raw_blocks.append(("paragraph", para, pf, inline_tokens, sectPr))
            elif child.tag == _qn_body('w:tbl'):
                table = DocxTable(child, doc._body)
                raw_blocks.append(("table", table))
                data.tables.append(table)
            elif child.tag == _qn_body('w:sectPr'):
                data.body_sectPr = copy.deepcopy(child)
                collect_section_header_footer_parts(doc, child, data)
                continue
            body_index += 1

        # Captions immediately below a table/image belong to that object block.
        # Preserve their complete paragraph XML instead of classifying/reformatting them.
        for block_index in range(1, len(raw_blocks)):
            block = raw_blocks[block_index]
            previous = raw_blocks[block_index - 1]
            if (block[0] == "paragraph"
                    and previous[0] in {"table", "paragraph_xml", "protected_paragraph_xml"}
                    and _is_object_caption(block[1])):
                raw_blocks[block_index] = ("protected_paragraph_xml", block[1])

        # 第二步：按换行符拆分段落（解决 3/4 级标题合并在同一段的问题）

        # ── 扁平化 + 单次分类（单 pass，传真实 next_line）──
        flat_lines = []  # text / table / image paragraph XML / protected caption XML
        for block_index, block in enumerate(raw_blocks):
            if block[0] != "paragraph":
                flat_lines.append(block)
                continue
            _, para, pf, inline_tokens, sectPr = block
            text = para.text.strip()
            text = normalize_text(text)
            if not text and sectPr is not None:
                sub_pf = ParagraphFeatures(
                    font_name=pf.font_name, font_size_pt=pf.font_size_pt,
                    bold=pf.bold, alignment=pf.alignment,
                    style_name=pf.style_name,
                    numbering_prefix=pf.numbering_prefix,
                    paragraph_index=len(flat_lines),
                    is_new_line=False,
                )
                flat_lines.append(("text", "", sub_pf, [], sectPr))
                continue
            has_structural_inline = any(token.kind in {"tab", "line_break", "page_break"} for token in inline_tokens)
            if has_structural_inline:
                normalized_tokens = normalize_tokens(inline_tokens)
                raw_inline_text = inline_tokens_text(normalized_tokens)
                line = raw_inline_text.strip()
                boundary_whitespace_trimmed = raw_inline_text != line
                has_page_break = any(token.kind == "page_break" for token in normalized_tokens)
                has_line_break = any(token.kind == "line_break" for token in normalized_tokens)
                split_lines = [part.strip() for part in line.split("\n")]
                following_text = ""
                for following in raw_blocks[block_index + 1:]:
                    if following[0] == "paragraph":
                        following_text = normalize_text(following[1].text).strip()
                        if following_text:
                            break
                # Manual page breaks are often mixed with blank soft breaks before
                # a trailing signature organization.  A following date is a
                # stronger structural boundary, so page-break presence must not
                # suppress the split.
                if (has_line_break
                        and _should_split_structural_line_breaks(split_lines, following_text)):
                    for li, split_line in enumerate(split_lines):
                        if not split_line:
                            continue
                        line_numbering = pf.numbering_prefix if li == 0 else _detect_numbering_prefix(split_line)
                        sub_pf = ParagraphFeatures(
                            font_name=pf.font_name, font_size_pt=pf.font_size_pt,
                            bold=pf.bold, alignment=pf.alignment,
                            style_name=pf.style_name,
                            numbering_prefix=line_numbering,
                            paragraph_index=len(flat_lines),
                            is_new_line=(li > 0),
                        )
                        flat_lines.append(("text", split_line, sub_pf, [], sectPr if li == len(split_lines) - 1 else None))
                    continue
                if not line and has_page_break:
                    line = text
                if not line and not has_page_break:
                    continue
                sub_pf = ParagraphFeatures(
                    font_name=pf.font_name, font_size_pt=pf.font_size_pt,
                    bold=pf.bold, alignment=pf.alignment,
                    style_name=pf.style_name,
                    numbering_prefix=pf.numbering_prefix,
                    paragraph_index=len(flat_lines),
                    is_new_line=False,
                )
                preserved_tokens = [] if boundary_whitespace_trimmed else normalized_tokens
                flat_lines.append(("text", line, sub_pf, preserved_tokens, sectPr))
                continue
            for li, line in enumerate(text.split('\n')):
                line = line.strip()
                line = normalize_text(line)
                if not line:
                    continue
                line_numbering = pf.numbering_prefix if li == 0 else _detect_numbering_prefix(line)
                sub_pf = ParagraphFeatures(
                    font_name=pf.font_name, font_size_pt=pf.font_size_pt,
                    bold=pf.bold, alignment=pf.alignment,
                    style_name=pf.style_name,
                    numbering_prefix=line_numbering,
                    paragraph_index=len(flat_lines),
                    is_new_line=(li > 0),
                )
                flat_lines.append(("text", line, sub_pf, [], sectPr if li == len(text.split('\n')) - 1 else None))

        ctx = DetectionContext()
        # 预扫描：找到最后一个正文/标题行的位置，之后的区域视为文档尾部
        last_body_idx = -1
        for j in range(len(flat_lines)):
            line_text = flat_lines[j][1] if flat_lines[j][0] == "text" else ""
            if not line_text:
                continue
            # 排除附件/落款/日期等非正文内容
            if re.match(r'^附件', line_text):
                continue
            if _SIGN_DATE_RE2.match(line_text):
                continue
            if re.match(r'^\d+[.．、]', line_text):
                continue  # 附件条目
            if _ATT_PAGE_RE.match(line_text):
                continue  # 附件页标记
            last_body_idx = j
        for i, item in enumerate(flat_lines):
            ctx._remaining_has_no_body = (i >= last_body_idx)
            if item[0] == "table":
                pd = ParagraphData(text="", type_id="__table__",
                                   original_text="", features=None,
                                   meta={"table": item[1]})
                data.paragraphs.append(pd)
                continue
            if item[0] == "paragraph_xml":
                pd = ParagraphData(text="", type_id="__image__",
                                   original_text="", features=None,
                                   meta={"image_xml": item[1]})
                data.paragraphs.append(pd)
                continue
            if item[0] == "protected_paragraph_xml":
                pd = ParagraphData(text="", type_id="__object_caption__",
                                   original_text="", features=None,
                                   meta={"paragraph_xml": item[1]})
                data.paragraphs.append(pd)
                continue
            if item[0] == "letterhead_paragraph_xml":
                pd = ParagraphData(
                    text="",
                    type_id="__letterhead__",
                    original_text="",
                    features=None,
                    meta={"paragraph_xml": item[1]},
                )
                data.paragraphs.append(pd)
                continue

            _, line, sub_pf, inline_tokens, sectPr = item
            next_line = ""
            next_pf = None
            for next_item in flat_lines[i + 1:]:
                if next_item[0] == "text":
                    next_line = next_item[1]
                    next_pf = next_item[2]
                    break

            # 受管版头输出重新处理时，固定主标题样式优先于普通物理特征打分。
            managed_title = (
                data.letterhead_detection.status == "managed"
                and sub_pf.style_name == "Docxtool Title"
                and not ctx.has_seen_real_body
            )
            if managed_title:
                type_id = "title" if not ctx.title_texts else "title_cont"
                meta_patch = {"is_title": True} if type_id == "title" else {}
                prefix = ""
                clean_text = line
            else:
                # 结构检测优先
                st, sm, sp, ft = detect_structural_type(line, next_line, ctx, sub_pf, next_pf)
                if st:
                    sm.pop("numbering", None)
                    type_id = st
                    meta_patch = sm
                    prefix = sp
                    clean_text = ft
                    ctx.prev_type_id = st
                else:
                    type_id, meta_patch, prefix = detect_paragraph_type(line, sub_pf, ctx, rules)
                    clean_text = strip_numbering(line, prefix)

            if ctx.attachment_page_mode and type_id == "body":
                type_id = "attachment_body"

            # 跳级修正
            if type_id.startswith("heading") and not type_id == "heading1_report":
                lvl = int(type_id[-1])
                prev_lvl = ctx.current_level
                if lvl == getattr(ctx, '_last_detected_lvl', 0):
                    capped = prev_lvl
                else:
                    capped = min(lvl, prev_lvl + 1)
                if capped != lvl:
                    type_id = f"heading{capped}"
                ctx.current_level = capped
                ctx._last_detected_lvl = lvl
            elif type_id == "heading1_report":
                ctx.current_level = 1
            ctx.prev_type_id = type_id

            # 结构状态跟踪
            if type_id in ("body", "addressing", "responsibility_line"):
                ctx.has_seen_real_body = True
                _record_structural(ctx, "body", clean_text)
            elif type_id.startswith("heading") or type_id in ("title", "title2"):
                if meta_patch.get("heading_inline_body"):
                    ctx.has_seen_real_body = True
                    _record_structural(ctx, "body", clean_text)
                else:
                    _record_structural(ctx, type_id, clean_text)
            else:
                _record_structural(ctx, type_id, clean_text)
            if type_id == "sign_date":
                ctx.signature_complete = True
                ctx.attachment_page_mode = False

            if sectPr is not None:
                meta_patch = dict(meta_patch or {})
                meta_patch["sectPr"] = sectPr
            pd = ParagraphData(
                text=clean_text, type_id=type_id,
                original_text=line, features=sub_pf, meta=meta_patch,
                inline_tokens=inline_tokens if clean_text == line else [],
            )
            data.paragraphs.append(pd)
            # 分类日志
            preview = clean_text[:28].replace('\n', ' ')
            logger.info(f"[识别] #{len(data.paragraphs)-1} {type_id} | \"{preview}\"{' meta='+str(meta_patch) if meta_patch else ''}")
            # (body_blocks removed — tables/images now use paragraph stream placeholders)

        data.doc_mode = ctx.doc_mode
        self._reorder_attachment_note_before_signature(data.paragraphs)
        self._assign_numbering(data.paragraphs, rules)
        self._merge_siblings(data.paragraphs)
        self._apply_core_classification(data, features)
        # (old classification loop removed — replaced by flat_lines single pass above)

        # 第三半：编号连续性检查（需在编号赋值之后）
        self._fix_numbering_gaps(data.paragraphs)

        # 第三步：剥离 Word 自动编号
        for para in doc.paragraphs:
            self._strip_auto_numbering(para)

        logger.info(f"[导入] {filepath}: {len(data.paragraphs)} 段, {len(data.tables)} 表格")
        return data

    def _apply_core_classification(self, data: DocumentData, features: dict) -> None:
        classification_options = features.get("classification", {}) if isinstance(features.get("classification", {}), dict) else {}
        if not _feature_bool(classification_options.get("enabled", True), True):
            return
        threshold = classification_options.get("minimum_auto_format_confidence", 0.85)
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = 0.85
        candidates = []
        indexes = []
        for index, paragraph in enumerate(data.paragraphs):
            if paragraph.type_id.startswith("__"):
                continue
            pf = paragraph.features or ParagraphFeatures()
            candidates.append(
                SimpleNamespace(
                    text=paragraph.original_text or paragraph.text,
                    style_name=pf.style_name,
                    alignment=pf.alignment,
                    first_line_indent=pf.first_line_indent,
                    font_size_pt=pf.font_size_pt,
                    bold=pf.bold,
                    native_numbering=bool(pf.numbering_prefix),
                )
            )
            indexes.append(index)
        if not candidates:
            return
        results = classify_paragraphs(candidates, ClassificationOptions(auto_format_threshold=threshold))
        for paragraph_index, result in zip(indexes, results):
            meta = dict(data.paragraphs[paragraph_index].meta or {})
            meta["classification_kind"] = result.kind.value
            meta["classification_confidence"] = round(result.confidence, 3)
            meta["classification_auto_format"] = bool(result.auto_format)
            data.paragraphs[paragraph_index].meta = meta

    def _reorder_attachment_note_before_signature(self, paragraphs: list) -> None:
        """Normalize sign/date before attachment note into official note→sign→date order."""
        i = 0
        while i < len(paragraphs) - 3:
            if paragraphs[i].type_id != "sign_org" or paragraphs[i + 1].type_id != "sign_date":
                i += 1
                continue
            if paragraphs[i + 2].type_id != "attachment_note":
                i += 1
                continue

            note_end = i + 3
            while note_end < len(paragraphs) and paragraphs[note_end].type_id == "attachment_note_item":
                note_end += 1

            sign_pair = paragraphs[i:i + 2]
            note_block = paragraphs[i + 2:note_end]
            paragraphs[i:note_end] = note_block + sign_pair
            i = note_end

    def _assign_numbering(self, paragraphs: list, rules: list, reset_on_attach: bool = True) -> None:
        """预计算所有标题编号，写入 pd.meta['numbering']。

        四级计数器 a/b/c/d，级联清零。Renderer 只负责显示，不计算。
        """
        # 内联中文数字（绕过模块缓存问题）
        _CN = ["零","一","二","三","四","五","六","七","八","九","十",
               "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十"]
        def _cn(n):
            r = _CN[n] if 0 <= n <= 20 else (_CN[n//10] + "十" + (_CN[n%10] if n%10 else ""))
            logger.debug(f"[CN] _cn({n}) = {r!r}")
            return r
        def _ar(n): return str(n)

        counters = {"a": 0, "b": 0, "c": 0, "d": 0}
        level_map = {"heading1": "a", "heading2": "b", "heading3": "c", "heading4": "d",
                     "glossary_item": "c"}

        for pd in paragraphs:
            # 附件页标记 → 重置所有编号
            if reset_on_attach and pd.type_id == "attachment_page_mark":
                counters = {"a": 0, "b": 0, "c": 0, "d": 0}
                continue
            if pd.meta.get("heading2_cont"):  # 缺编号的 heading2 续行，不自动编号
                continue
            key = level_map.get(pd.type_id)
            if key is None:
                continue

            # 递增本级，清零下级
            counters[key] += 1
            if key == "a":
                counters["b"] = counters["c"] = counters["d"] = 0
            elif key == "b":
                counters["c"] = counters["d"] = 0
            elif key == "c":
                counters["d"] = 0

            # 查找对应规则获取模板（若已被误渲染则回退默认值）
            rule = rules[_key_to_row(key)] if _key_to_row(key) < len(rules) else None
            pattern = rule.numbering_pattern if rule else ""
            # 修复：pattern 中没有 {a}/{b}/{c}/{d} → 说明是渲染后的值，强制回退
            if pattern and not any(c in pattern for c in ("{a}", "{b}", "{c}", "{d}")):
                fallback = {
                    "a": "{a}、", "b": "（{b}）", "c": "{c}.", "d": "（{d}）",
                }.get(key, "")
                logger.warning(f"[编号修复] pattern={pattern!r} 不包含模板变量，回退为 {fallback!r}")
                pattern = fallback

            # 渲染编号
            is_cn = pd.type_id in ("heading1", "heading2")
            num_fn = _cn if is_cn else _ar
            result = pattern
            logger.debug(f"[编号渲染] pattern={pattern!r} a={counters['a']} is_cn={is_cn}")
            result = result.replace("{a}", num_fn(counters["a"]))
            result = result.replace("{b}", num_fn(counters["b"]))
            result = result.replace("{c}", _ar(counters["c"]))
            result = result.replace("{d}", _ar(counters["d"]))

            pd.meta["numbering"] = result
            logger.debug(f"[编号] {pd.type_id} → \"{result}\" (a={counters['a']} b={counters['b']} c={counters['c']} d={counters['d']})")

    def _strip_auto_numbering(self, paragraph) -> None:
        """删除段落中的 Word 自动编号标记 <w:numPr>。"""
        try:
            from docx.oxml.ns import qn
            pPr = paragraph._element.find(qn('w:pPr'))
            if pPr is not None:
                numPr = pPr.find(qn('w:numPr'))
                if numPr is not None:
                    pPr.remove(numPr)
                    logger.debug(f"[导入] 剥离自动编号: '{paragraph.text[:30]}'")
        except Exception:
            pass

    def _merge_siblings(self, paragraphs: list) -> None:
        """A. 同级合并：父标题下全是同模式子项 → 提升为父+1级。"""
        PARENT_KEYS = {"heading1", "heading2", "heading3"}
        changed = True
        while changed:
            changed = False
            for i in range(len(paragraphs)):
                pd = paragraphs[i]
                if pd.type_id not in PARENT_KEYS:
                    continue
                parent_lvl = int(pd.type_id[-1])
                parent_key = pd.type_id
                j = i + 1
                siblings = []
                while j < len(paragraphs):
                    t = paragraphs[j].type_id
                    if t in PARENT_KEYS and int(t[-1]) <= parent_lvl:
                        break
                    if t.startswith("heading"):
                        siblings.append(j)
                    j += 1
                if len(siblings) >= 2:
                    levels = {int(paragraphs[s].type_id[-1]) for s in siblings}
                    if len(levels) == 1:
                        target = f"heading{min(parent_lvl + 1, 4)}"
                        # 保护：已有编号的段落不合并（防止吃掉并列标题如（一）（二）（三））
                        if any(paragraphs[s].meta.get("numbering") for s in siblings):
                            logger.debug("[同级合并] 跳过：siblings 已有编号")
                            continue
                        if any(paragraphs[s].type_id != target for s in siblings):
                            for s in siblings:
                                paragraphs[s].type_id = target
                                paragraphs[s].meta["numbering"] = ""
                            logger.info(f"[同级合并] {parent_key}下{len(siblings)}项L{max(levels)}→{target}")
                            changed = True

    def _fix_numbering_gaps(self, paragraphs: list) -> None:
        """C. 编号连续性检查 + 自动修正跳号（heading1/2/3）。"""
        _CN = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}
        _NC = {v:k for k,v in _CN.items()}
        expected = {"a": 1, "b": {}, "c": {}, "d": {}}

        for pd in paragraphs:
            # 附件页边界 → 重置期望值
            if pd.type_id == "attachment_page_mark":
                expected = {"a": 1, "b": {}, "c": {}, "d": {}}
                continue
            tid = pd.type_id
            if tid not in ("heading1", "heading2", "heading3", "heading4"):
                continue
            key = tid[-1]
            num = pd.meta.get("numbering", "")
            if not num:
                continue

            if key == "1":
                ch = num[0]
                actual = _CN.get(ch)
                if actual and actual != expected["a"]:
                    fixed = _NC.get(expected["a"], str(expected["a"]))
                    pd.meta["numbering"] = num.replace(ch + "、", fixed + "、", 1)
                    logger.warning(f"[编号修正] heading1 {num}→{pd.meta['numbering']}")
                    actual = expected["a"]  # 用修正后的值
                if actual:
                    expected["a"] = actual + 1
                    expected["b"] = {actual: 1}
                    expected["c"] = {}
                    expected["d"] = {}
            elif key == "2":
                pa = expected["a"] - 1
                ch = num[1] if num.startswith("（") else num[0]
                actual = _CN.get(ch)
                exp = expected["b"].get(pa, 1)
                if actual and actual != exp:
                    fixed = _NC.get(exp, str(exp))
                    pd.meta["numbering"] = num.replace("（" + ch + "）", "（" + fixed + "）", 1).replace(ch + ".", fixed + ".", 1)
                    logger.warning(f"[编号修正] heading2 {num}→{pd.meta['numbering']}")
                    actual = exp
                if actual:
                    expected["b"][pa] = actual + 1
                expected["c"] = {}
                expected["d"] = {}
            elif key == "3":
                pa = expected["a"] - 1
                pb = expected["b"].get(pa, 1) - 1
                idx = (pa, pb)
                actual = int(num.rstrip(".")) if num.rstrip(".").isdigit() else None
                exp = expected["c"].get(idx, 1)
                if actual is not None and actual != exp:
                    pd.meta["numbering"] = str(exp) + "."
                    logger.warning(f"[编号修正] heading3 {num}→{pd.meta['numbering']}")
                    actual = exp
                if actual is not None:
                    expected["c"][idx] = actual + 1
                expected["d"] = {}
            elif key == "4":
                pa = expected["a"] - 1
                pb = expected["b"].get(pa, 1) - 1
                pc = expected["c"].get((pa, pb), 1) - 1
                idx = (pa, pb, pc)
                m = re.search(r'\d+', num)
                actual = int(m.group()) if m else None
                exp = expected["d"].get(idx, 1)
                if actual is not None and actual != exp:
                    pd.meta["numbering"] = num.replace(str(actual), str(exp), 1)
                    logger.warning(f"[编号修正] heading4 {num}→{pd.meta['numbering']}")
                    actual = exp
                if actual is not None:
                    expected["d"][idx] = actual + 1


if __name__ == "__main__":
    ctx = DetectionContext()
    ctx.doc_mode = "NORMAL"
    pf = ParagraphFeatures()
    tid, _, _ = detect_paragraph_type("一、加强政治建设", pf, ctx, [])
    assert tid == "heading1", f"一、→ heading1: got {tid}"
    tid, _, _ = detect_paragraph_type("（一）坚持党的领导", pf, ctx, [])
    assert tid == "heading2", f"（一）→ heading2: got {tid}"
    tid, _, _ = detect_paragraph_type("1.完善组织体系", pf, ctx, [])
    assert tid == "heading3", f"1.→ heading3: got {tid}"
    pf_lvl = ParagraphFeatures(numbering_prefix="@lvl_0")
    tid, _, _ = detect_paragraph_type("带头固本培元、增强党性方面。", pf_lvl, DetectionContext(has_seen_body=True), [])
    assert tid == "heading2", f"@lvl_0 应识别为 heading2: got {tid}"
    tid, meta, _ = detect_paragraph_type("一要党内组织生活实效还有待提升。", pf_lvl, DetectionContext(has_seen_body=True), [])
    assert tid == "body" and meta.get("numbered_bold"), f"一要正文不应被自动编号误判为标题: {tid}, {meta}"
    assert strip_numbering("一、改革", "一、") == "改革"
    assert _looks_like_heading("一，加强领导")

    # 附件结构识别回归：正文后进入附件说明 → 落款 → 附件页 → 标题 → 正文
    ctx2 = DetectionContext(
        has_seen_body=True,
        has_seen_real_body=True,
        prev_type_id="body",
        last_structural_type="body",
    )
    cases = [
        ("附件：1.基本情况", "1. 具体情况", "attachment_note"),
        ("1. 具体情况", "2. 超级情况", "attachment_note_item"),
        ("2. 超级情况", "区政府人才保障工作组", "attachment_note_item"),
        ("区政府人才保障工作组", "2025年十月15日", "sign_org"),
        ("2025年十月15日", "附件1", "sign_date"),
        ("附件1", "标题", "attachment_page_mark"),
        ("标题", "测试正文。", "attachment_title"),
        ("测试正文。", "", "attachment_body"),
    ]
    for idx, (line, next_line, expected) in enumerate(cases):
        actual, _, _, _ = detect_structural_type(line, next_line, ctx2)
        assert actual == expected, f"附件结构第{idx}行识别失败: {line} -> {actual}, 期望 {expected}"

    # 附件结构识别回归：附件续项只有 Word 自动编号时，也应进入 attachment_note_item
    ctx3 = DetectionContext(
        has_seen_body=True,
        has_seen_real_body=True,
        prev_type_id="body",
        last_structural_type="body",
    )
    note_type, _, _, _ = detect_structural_type(
        "附件：基本情况", "具体情况", ctx3,
        ParagraphFeatures(paragraph_index=0),
        ParagraphFeatures(numbering_prefix="@lvl_0", paragraph_index=1),
    )
    assert note_type == "attachment_note", f"自动编号附件首行识别失败: {note_type}"
    item_type, _, _, fixed_text = detect_structural_type(
        "具体情况", "区政府人才保障工作组", ctx3,
        ParagraphFeatures(numbering_prefix="@lvl_0", paragraph_index=1),
        ParagraphFeatures(paragraph_index=2),
    )
    assert item_type == "attachment_note_item", f"自动编号附件续项识别失败: {item_type}"
    assert fixed_text.startswith("2. "), f"自动编号附件续项补号失败: {fixed_text}"
    print("✅ DOCX 导入器验证全部通过")
