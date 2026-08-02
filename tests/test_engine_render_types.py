from docxtool.document.engine.render_types import (
    is_body_flow_type,
    is_head_gap_follow_type,
    is_head_type_requiring_gap,
    rule_index_for_type,
)


def test_rule_index_for_type_keeps_existing_renderer_mapping() -> None:
    assert rule_index_for_type("title") == 0
    assert rule_index_for_type("heading1") == 1
    assert rule_index_for_type("heading2") == 2
    assert rule_index_for_type("heading3") == 3
    assert rule_index_for_type("heading4") == 4
    assert rule_index_for_type("body") == 5
    assert rule_index_for_type("sign_date") == 23
    assert rule_index_for_type("unknown") is None


def test_renderer_flow_type_helpers_keep_gap_and_body_flow_boundaries() -> None:
    assert is_head_type_requiring_gap("role_name") is True
    assert is_head_type_requiring_gap("body") is False
    assert is_head_gap_follow_type("heading1") is True
    assert is_head_gap_follow_type("sign_date") is False
    assert is_body_flow_type("attachment_note") is True
    assert is_body_flow_type("title") is False
