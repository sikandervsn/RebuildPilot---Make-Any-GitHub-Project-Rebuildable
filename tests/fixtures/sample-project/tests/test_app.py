from src.app import configured_database


def test_configuration_is_readable() -> None:
    assert configured_database() is None or isinstance(configured_database(), str)
