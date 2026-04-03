import logging
import os
import sys


def _redirect_lark_sdk_to_stderr() -> None:
    """lark SDK's core/log.py registers a StreamHandler(sys.stdout) at import time.
    Replace it with stderr so MCP stdio is not corrupted."""
    lark_logger = logging.getLogger("Lark")
    for h in list(lark_logger.handlers):
        if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout:
            lark_logger.removeHandler(h)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("[Lark] [%(asctime)s] [%(levelname)s] %(message)s"))
    lark_logger.addHandler(stderr_handler)
    lark_logger.setLevel(logging.WARNING)


_redirect_lark_sdk_to_stderr()


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        level_str = os.environ.get("TASKARENA_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)
        logger.setLevel(level)

        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        formatter = logging.Formatter("[taskarena] %(levelname)s %(asctime)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        lark_oapi_logger = logging.getLogger("lark_oapi")
        lark_oapi_logger.setLevel(logging.WARNING)
        if not lark_oapi_logger.handlers:
            lark_oapi_logger.addHandler(handler)

    return logger