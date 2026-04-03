import os
from unittest import mock
from taskarena.config import Config

@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test_id", "FEISHU_APP_SECRET": "test_secret"})
def test_config_load():
    config = Config.load()
    assert config.app_id == "test_id"
    assert config.app_secret == "test_secret"
    assert config.log_level == "INFO"