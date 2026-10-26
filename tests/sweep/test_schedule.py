"""Schedule parsing for LIBRARY_SWEEP_SCHEDULE."""

import datetime

import pytest

from slskd_importer.sweep.schedule import next_run, parse_schedule, previous_run


def test_default_weekly_sunday():
    s = parse_schedule("")
    assert s is not None
    assert s.weekday == 6
    assert s.hour == 4
    assert s.minute == 0


def test_off():
    assert parse_schedule("off") is None


def test_daily():
    s = parse_schedule("daily:09:30")
    assert s.weekday is None
    assert s.hour == 9
    assert s.minute == 30


def test_bad_raises():
    with pytest.raises(ValueError):
        parse_schedule("weekly:xxx:04:00")


def test_next_after_previous():
    s = parse_schedule("daily:04:00")
    now = datetime.datetime(2026, 10, 26, 5, 0, tzinfo=datetime.UTC)
    assert previous_run(s, now) < next_run(s, now)
