"""Chromaprint same-recording check (fpcalc)."""

from __future__ import annotations

import logging
import shutil
import subprocess

from slskd_importer.sweep.audit import _nice

logger = logging.getLogger(__name__)

FP_ITEM_SECS = 4096 / 3 / 11025
FP_LENGTH_SECS = 150
# How far one file may be shifted against the other (silence or an intro at the start).
FP_MAX_LAG_SECS = 50
# Least overlap a lag needs to count, so a few seconds of luck cannot score high.
FP_MIN_OVERLAP_SECS = 20
# Bit similarity of the same recording: one recording under another master scored 0.92,
# another performance of the song 0.60, unrelated audio sits near 0.5.
SAME_RECORDING_SIMILARITY = 0.85
# Below this a copy is another performance of the song, not another master: the owner kept their own file
# over 12 of 14 such copies and over 12 of 227 closer ones. The sweep tries the other copies first and
# offers one of these only when nothing closer qualifies.
FAR_SIMILARITY = 0.6
FPCALC_TIMEOUT_SECS = 120

def fpcalc_available() -> bool:
    return shutil.which("fpcalc") is not None


def missing_tools() -> list[str]:
    """What the sweep cannot measure without: ffmpeg (strict decode) and the analysis extra (cutoff, fingerprint math).

    fpcalc is optional (judge() falls back to length and tags), so it is not listed.
    """
    from music_downloader.processor.lossless_analyzer import HAS_ANALYSIS

    missing = []
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")
    if not HAS_ANALYSIS:
        missing.append("numpy, scipy and soundfile (pip install 'telegram-slskd-local-bot[analysis]')")
    return missing


def fingerprint(path: str, length_secs: int = FP_LENGTH_SECS) -> list[int] | None:
    """The raw Chromaprint fingerprint of the first *length_secs* of *path*; None without fpcalc or on failure."""
    if not fpcalc_available():
        return None
    try:
        r = subprocess.run(
            _nice(["fpcalc", "-raw", "-length", str(length_secs), path]),
            capture_output=True,
            text=True,
            timeout=FPCALC_TIMEOUT_SECS,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("fpcalc did not finish on %s", path, exc_info=True)
        return None
    for line in r.stdout.splitlines():
        if line.startswith("FINGERPRINT="):
            items = [int(x) for x in line.split("=", 1)[1].split(",") if x.strip()]
            return items or None
    logger.warning("fpcalc gave no fingerprint for %s: %s", path, r.stderr.strip()[:200])
    return None


def similarity(a: list[int], b: list[int], max_lag_secs: float = FP_MAX_LAG_SECS) -> float:
    """Best share of equal bits between two raw fingerprints, one shifted against the other by up to *max_lag_secs*.

    1.0 is the same audio; unrelated audio sits near 0.5. A shift counts only
    with FP_MIN_OVERLAP_SECS of overlap (or half the shorter fingerprint,
    for very short files).
    """
    import numpy as np

    if not a or not b:
        return 0.0
    x = np.asarray(a, dtype=np.int64).astype(np.uint32)
    y = np.asarray(b, dtype=np.int64).astype(np.uint32)
    max_lag = int(max_lag_secs / FP_ITEM_SECS)
    min_overlap = max(1, min(int(FP_MIN_OVERLAP_SECS / FP_ITEM_SECS), min(len(x), len(y)) // 2))
    table = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)
    best = 0.0
    for lag in range(-max_lag, max_lag + 1):
        # x[i] against y[i + lag]
        start_x = max(0, -lag)
        start_y = max(0, lag)
        n = min(len(x) - start_x, len(y) - start_y)
        if n < min_overlap:
            continue
        diff = np.bitwise_xor(x[start_x : start_x + n], y[start_y : start_y + n])
        errors = int(table[diff.view(np.uint8)].sum())
        score = 1.0 - errors / (32.0 * n)
        best = max(best, score)
    return best
