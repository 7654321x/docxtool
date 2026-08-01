from docxtool.document.normalization.signature import normalize_sign_org


def test_normalize_sign_org_removes_only_leading_chinese_heading_number() -> None:
    """落款单位规范化只移除前导中文编号，不改单位名称正文。"""
    assert normalize_sign_org("一、某区工作办公室") == "某区工作办公室"
    assert normalize_sign_org("  十、区政府人才保障工作组") == "区政府人才保障工作组"
    assert normalize_sign_org("区政府人才保障工作组") == "区政府人才保障工作组"
    assert normalize_sign_org("责任单位：办公室") == "责任单位：办公室"
