"""Small text building blocks shared by cards and commands."""

BUTTON_MAX = 64


def progress_bar(percent: float, width: int = 10) -> str:
    """Render a text progress bar like ▰▰▰▱▱▱▱▱▱▱ for a 0-100 percent value."""
    clamped = max(0.0, min(100.0, percent))
    filled = round(clamped / 100 * width)
    return "▰" * filled + "▱" * (width - filled)


def clip(text: str, limit: int = BUTTON_MAX) -> str:
    """*text* within Telegram's button-label limit, ending in an ellipsis when cut."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
