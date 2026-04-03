from __future__ import annotations

from typing import Any


def build_channel_xml(content: str, **attrs: Any) -> str:
    attr_text = " ".join(f'{key}="{_escape_attr(value)}"' for key, value in attrs.items() if value is not None)
    if attr_text:
        return f"<channel {attr_text}>{_escape_text(content)}</channel>"
    return f"<channel>{_escape_text(content)}</channel>"


def _escape_attr(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_text(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
