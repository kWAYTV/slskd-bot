"""Markdown escaping for Telegram legacy-Markdown (V1)."""

from __future__ import annotations

from music_downloader.telegram.ui.markdown import code_span, md_code_safe
from music_downloader.telegram.ui.markdown import escape_md as _escape_md


class TestEscapeMd:
    def test_escapes_v1_special_chars(self):
        assert _escape_md("hello_world") == "hello\\_world"
        assert _escape_md("*bold*") == "\\*bold\\*"
        assert _escape_md("[link](url)") == "\\[link](url)"
        assert _escape_md("`code`") == "\\`code\\`"

    def test_v1_ignores_other_chars(self):
        """V1 renders backslashes before non-special chars literally — don't add them."""
        assert _escape_md("Artist - Title (Remix)!") == "Artist - Title (Remix)!"
        assert _escape_md("A.B-C+D") == "A.B-C+D"

    def test_plain_text_unchanged(self):
        assert _escape_md("hello world") == "hello world"

    def test_empty_string(self):
        assert _escape_md("") == ""


class TestCodeSpan:
    def test_wraps_in_backticks(self):
        assert code_span("file.flac") == "`file.flac`"

    def test_neutralizes_inner_backticks(self):
        span = code_span("evil`name.flac")
        assert span.startswith("`") and span.endswith("`")
        assert "`" not in span[1:-1]

    def test_md_code_safe_replaces_backticks(self):
        assert "`" not in md_code_safe("a`b`c")
        assert md_code_safe("clean.flac") == "clean.flac"
