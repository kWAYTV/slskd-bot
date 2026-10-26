"""FLAC authenticity analysis — thin wrapper over ``library.lossless``.

Kept for Telegram delivery imports (`FlacVerdict`, `analyze_flac`).
"""

from __future__ import annotations

from slskd_importer.library.lossless import (
    HAS_ANALYSIS,
    LosslessVerdict,
    analyze_lossless,
)

FlacVerdict = LosslessVerdict


def analyze_flac(filepath: str, sample_duration: float = 30.0) -> FlacVerdict | None:
    """Analyze a FLAC (or other checkable lossless) file for spectral authenticity."""
    return analyze_lossless(filepath, sample_duration)


__all__ = ["HAS_ANALYSIS", "FlacVerdict", "analyze_flac"]
