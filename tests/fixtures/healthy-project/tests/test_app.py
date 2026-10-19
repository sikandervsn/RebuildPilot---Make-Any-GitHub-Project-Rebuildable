from src.app import application_mode


def test_application_mode_has_a_safe_default() -> None:
    assert application_mode() in {"development", "production"}
