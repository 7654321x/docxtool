from docxtool.document.engine.render_options import feature_enabled, feature_options


def test_feature_options_returns_dict_or_empty_dict() -> None:
    assert feature_options({"enabled": True}) == {"enabled": True}
    assert feature_options(None) == {}
    assert feature_options("enabled") == {}


def test_feature_enabled_accepts_known_truthy_and_falsy_values() -> None:
    assert feature_enabled({"enabled": "true"}) is True
    assert feature_enabled({"enabled": "启用"}) is True
    assert feature_enabled({"enabled": "0"}, default=True) is False
    assert feature_enabled({"enabled": "否"}, default=True) is False
    assert feature_enabled({"enabled": "unknown"}, default=True) is True
    assert feature_enabled(None, default=False) is False
