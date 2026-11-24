"""A hand-picked copy, stored on its queue item so the choice survives a restart."""

from __future__ import annotations

import dataclasses
import json

from slskd_importer.soulseek.result import SearchResult

_FIELDS = tuple(field.name for field in dataclasses.fields(SearchResult))


def encode_pick(copy: SearchResult) -> str:
    return json.dumps(dataclasses.asdict(copy), ensure_ascii=False)


def decode_pick(text: str) -> SearchResult | None:
    """The stored copy, or None when the item has no pick (or an unreadable one)."""
    if not text:
        return None
    try:
        data = json.loads(text)
        return SearchResult(**{name: data[name] for name in _FIELDS if name in data})
    except (ValueError, TypeError):
        return None
