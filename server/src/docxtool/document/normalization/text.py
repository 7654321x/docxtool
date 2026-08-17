"""Text cleanup helpers shared by import-time normalization paths."""

from __future__ import annotations

import re


def normalize_basic_text(text: str) -> str:
    """执行基础文本清理。

    传入数据是段落或 run 的可见文本。返回值会转换中文语境中的括号，
    并移除零宽空格、全角空格和不换行空格。
    """
    text = re.sub(r"\(([\u4e00-\u9fff][^)]*[\u4e00-\u9fff])\)", r"（\1）", text)
    text = re.sub(r"[\u200b\u3000\u00a0]", "", text)
    return text


def to_chinese_punctuation(text: str) -> str:
    """执行旧 importer 兼容标点转换。

    传入数据是已做基础清理的文本。返回值只在中文上下文中转换常见
    半角标点，并保留损坏一级标题中的结构点号。
    """
    if not text:
        return text
    text = re.sub(r"(?<=[\u4e00-\u9fff])[:：]", "：", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff]),\s*", "，", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff0-9]);\s*", "；", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\?", "？", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])!", "！", text)

    def full_stop(match: re.Match[str]) -> str:
        """判断句点应保留为编号点还是转换为中文句号。"""
        prefix = text[:match.start()]
        if re.fullmatch(r"[一二三四五六七八九十百千零〇]{1,5}", prefix):
            return "."
        return "。"

    text = re.sub(r"(?<=[\u4e00-\u9fff])\.(?=$|[\s\u4e00-\u9fff”’）》）】」』])", full_stop, text)
    return text


def normalize_quotes(text: str) -> str:
    """执行旧 importer 兼容引号转换。

    传入数据是段落或 run 文本。返回值将中文语境中的半角引号转换为
    中文引号，并保留英文单词内部撇号。
    """
    if not text:
        return text
    text = re.sub(r"''(?=\S)", "\u201c", text)
    text = re.sub(r"(?<=\S)''", "\u201d", text)
    parts = text.split('"')
    if len(parts) > 1:
        result = [parts[0]]
        for index in range(1, len(parts)):
            result.append("\u201c" if index % 2 == 1 else "\u201d")
            result.append(parts[index])
        text = "".join(result)
    text = re.sub(r"(?<![A-Za-z])'(?=[\u4e00-\u9fff])", "\u2018", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])'(?![A-Za-z])", "\u2019", text)
    return text


def normalize_legacy_punctuation_text(text: str) -> str:
    """执行旧 importer 的完整兼容文本规范化。

    传入数据是段落或 run 文本。返回值按历史顺序执行基础清理、引号
    规范化和中文上下文标点转换。
    """
    return to_chinese_punctuation(normalize_quotes(normalize_basic_text(text)))
