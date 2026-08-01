"""Signature text normalization helpers."""

from __future__ import annotations

import re


def normalize_sign_org(text: str) -> str:
    """规范化已识别的落款单位文本。

    传入数据是最终识别为 `sign_org` 的段落文本。返回值只移除误粘在
    落款单位前的中文一级编号前缀，并保留单位名称本身。
    """
    return re.sub(r"^\s*[一二三四五六七八九十百]+、\s*", "", text or "", count=1).strip()
