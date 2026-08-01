from __future__ import annotations

from docxtool.document.importer import DetectionContext as ImporterDetectionContext
from docxtool.document.importer import ScoreBoard as ImporterScoreBoard
from docxtool.document.importer import ScoreDetail as ImporterScoreDetail
from docxtool.document.recognition.legacy import DetectionContext, ScoreBoard, ScoreDetail


def test_importer_reexports_legacy_scoring_models() -> None:
    assert ImporterDetectionContext is DetectionContext
    assert ImporterScoreBoard is ScoreBoard
    assert ImporterScoreDetail is ScoreDetail


def test_score_board_default_and_explain_order() -> None:
    board = ScoreBoard()
    type_id, detail = board.winner()

    assert type_id == "body"
    assert detail.total == 10.0
    assert detail.reasons == [("default", 10.0)]

    board.add_pattern("heading1", 30)
    board.add_rules({"body": 5, "heading1": 3})
    board.add_context("body", 2)

    assert board.winner()[0] == "heading1"
    assert board.explain()[0]["type"] == "heading1"
    assert board.explain()[1]["type"] == "body"


def test_detection_context_defaults_are_compatible() -> None:
    context = DetectionContext()

    assert context.para_index == 0
    assert context.prev_type_id == ""
    assert context.title_texts == []
    assert context.attachment_note_next_no == 1
