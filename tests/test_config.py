import os
from unittest import mock
from taskarena.config import Config, ReminderConfig


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test_id", "FEISHU_APP_SECRET": "test_secret"})
def test_config_load():
    config = Config.load()
    assert config.app_id == "test_id"
    assert config.app_secret == "test_secret"
    assert config.log_level == "INFO"


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_reminders_absent_by_default():
    config = Config.load()
    assert config.reminders is None


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_reminders_loaded_from_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".taskarena").mkdir()
    (tmp_path / ".taskarena" / "config.yaml").write_text(
        "reminders:\n  morning_time: '08:30'\n  timezone: 'Asia/Tokyo'\n  tasklists:\n    - 'abc123'\n"
    )
    config = Config.load()
    assert config.reminders is not None
    assert config.reminders.morning_time == "08:30"
    assert config.reminders.timezone == "Asia/Tokyo"
    assert config.reminders.tasklists == ["abc123"]


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_reminders_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".taskarena").mkdir()
    (tmp_path / ".taskarena" / "config.yaml").write_text("reminders: {}\n")
    config = Config.load()
    assert config.reminders is not None
    assert config.reminders.morning_time == "09:00"
    assert config.reminders.timezone == "Asia/Shanghai"
    assert config.reminders.tasklists == []
