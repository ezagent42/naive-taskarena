import importlib


def test_feishu_module_imports():
    module = importlib.import_module("taskarena.feishu")
    assert module is not None


def test_runtime_modules_import():
    for module_name in [
        "taskarena.tools",
        "taskarena.channel",
        "taskarena.events",
        "taskarena.scheduler",
        "taskarena.__main__",
    ]:
        assert importlib.import_module(module_name) is not None
