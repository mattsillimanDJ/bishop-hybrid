from app.services import focus_service


def test_set_and_get_active_focus_is_user_and_lane_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(focus_service, "DB_PATH", tmp_path / "focus.db")

    focus_service.set_active_focus("U123", "work", "stemlab")
    focus_service.set_active_focus("U123", "dj", "dj")
    focus_service.set_active_focus("U123", "matt", "events")
    focus_service.set_active_focus("U999", "work", "website")

    assert focus_service.get_active_focus("U123", "work") == "stemlab"
    assert focus_service.get_active_focus("U123", "dj") == "dj"
    assert focus_service.get_active_focus("U123", "matt") == "events"
    assert focus_service.get_active_focus("U999", "work") == "website"


def test_clear_active_focus_only_clears_matching_user_and_lane(tmp_path, monkeypatch):
    monkeypatch.setattr(focus_service, "DB_PATH", tmp_path / "focus.db")

    focus_service.set_active_focus("U123", "work", "stemlab")
    focus_service.set_active_focus("U123", "dj", "dj")

    assert focus_service.clear_active_focus("U123", "work") is True
    assert focus_service.get_active_focus("U123", "work") is None
    assert focus_service.get_active_focus("U123", "dj") == "dj"


def test_set_active_focus_rejects_unsupported_focus(tmp_path, monkeypatch):
    monkeypatch.setattr(focus_service, "DB_PATH", tmp_path / "focus.db")

    try:
        focus_service.set_active_focus("U123", "work", "finance")
    except ValueError as error:
        assert "Unsupported focus" in str(error)
    else:
        raise AssertionError("Expected unsupported focus to raise ValueError")
