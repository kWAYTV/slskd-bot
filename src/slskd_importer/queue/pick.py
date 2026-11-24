"""Soulseek copies as stored text: the copy picked for an item, and the copies found for it.

Both live in the database so a choice, and the list it was made from, survive a restart.
"""

from __future__ import annotations

import dataclasses
import json

from slskd_importer.soulseek.result import SearchResult

_FIELDS = tuple(field.name for field in dataclasses.fields(SearchResult))


def _from_dict(data: dict) -> SearchResult:
    return SearchResult(**{name: data[name] for name in _FIELDS if name in data})


def encode_pick(copy: SearchResult) -> str:
    return json.dumps(dataclasses.asdict(copy), ensure_ascii=False)


def decode_pick(text: str) -> SearchResult | None:
    """The stored copy, or None when the item has no pick (or an unreadable one)."""
    if not text:
        return None
    try:
        return _from_dict(json.loads(text))
    except (ValueError, TypeError):
        return None


def encode_copies(copies: list[SearchResult]) -> str:
    return json.dumps([dataclasses.asdict(copy) for copy in copies], ensure_ascii=False)


def decode_copies(text: str) -> list[SearchResult]:
    """The stored copies, best first; unreadable text gives an empty list."""
    try:
        return [_from_dict(data) for data in json.loads(text or "[]")]
    except (ValueError, TypeError):
        return []
