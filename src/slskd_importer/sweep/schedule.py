"""LIBRARY_SWEEP_SCHEDULE parsing and next/previous run times."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

DEFAULT_SCHEDULE = "weekly:sun:04:00"
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Schedule:
    """When scheduled sweeps start, in local time. *weekday* 0 = Monday; None = every day."""

    hour: int
    minute: int
    weekday: int | None = None

    def __str__(self) -> str:
        at = f"{self.hour:02d}:{self.minute:02d}"
        return f"daily:{at}" if self.weekday is None else f"weekly:{_DAYS[self.weekday]}:{at}"


def parse_schedule(text: str | None) -> Schedule | None:
    """LIBRARY_SWEEP_SCHEDULE: "weekly:<mon..sun>:HH:MM", "daily:HH:MM", or "off" (None). Empty = DEFAULT_SCHEDULE.

    Raises ValueError for anything else.
    """
    text = (text or "").strip().lower() or DEFAULT_SCHEDULE
    if text == "off":
        return None
    m = re.fullmatch(r"weekly:([a-z]{3}):(\d{1,2}):(\d{2})", text) or re.fullmatch(r"daily:(\d{1,2}):(\d{2})", text)
    if not m:
        raise ValueError(f"LIBRARY_SWEEP_SCHEDULE must be weekly:<mon..sun>:HH:MM, daily:HH:MM or off, not {text!r}")
    groups = m.groups()
    weekday = None
    if len(groups) == 3:
        if groups[0] not in _DAYS:
            raise ValueError(f"LIBRARY_SWEEP_SCHEDULE: unknown day {groups[0]!r} (mon, tue, wed, thu, fri, sat, sun)")
        weekday = _DAYS.index(groups[0])
        groups = groups[1:]
    hour, minute = int(groups[0]), int(groups[1])
    if hour > 23 or minute > 59:
        raise ValueError(f"LIBRARY_SWEEP_SCHEDULE: {hour:02d}:{minute:02d} is not a time of day")
    return Schedule(hour, minute, weekday)


def previous_run(schedule: Schedule, now: datetime.datetime) -> datetime.datetime:
    """The latest scheduled start at or before *now* (same tzinfo as *now*)."""
    at = now.replace(hour=schedule.hour, minute=schedule.minute, second=0, microsecond=0)
    if schedule.weekday is None:
        return at if at <= now else at - datetime.timedelta(days=1)
    at -= datetime.timedelta(days=(now.weekday() - schedule.weekday) % 7)
    return at if at <= now else at - datetime.timedelta(days=7)


def next_run(schedule: Schedule, now: datetime.datetime) -> datetime.datetime:
    """The first scheduled start strictly after *now*."""
    step = datetime.timedelta(days=1 if schedule.weekday is None else 7)
    return previous_run(schedule, now) + step
