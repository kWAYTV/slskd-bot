"""Telegram legacy-Markdown (V1) escaping for dynamic text."""


def escape_md(text: str) -> str:
    """Escape Telegram legacy-Markdown (V1) special characters.

    V1 only honors backslash escapes for ``_ * ` [`` — escaping anything else
    renders the backslash literally (e.g. ``\\-`` shows up in the chat).
    """
    for ch in "_*`[":
        text = text.replace(ch, f"\\{ch}")
    return text


def bold(text: str) -> str:
    """*text* in bold. Legacy Markdown ignores backslash escapes inside an entity, so the
    characters that would break it are dropped instead of escaped."""
    return f"*{text.replace('*', '').replace('`', '').replace('_', ' ').strip() or '?'}*"


def md_code_safe(text: str) -> str:
    """Neutralize backticks in values interpolated into Markdown code spans."""
    return text.replace("`", "ʼ")


def code_span(text: str) -> str:
    """Wrap text in a Markdown code span, neutralizing backticks that would break it."""
    return f"`{md_code_safe(text)}`"
