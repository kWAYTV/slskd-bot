"""Lossless authenticity via spectral cutoff (FLAC, WAV, AIFF).

True lossless audio has energy up to Nyquist. Lossy-to-lossless transcodes
show a sharp cutoff between 16–20 kHz.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

try:
    import numpy as np
    import soundfile as sf
    from scipy import signal

    HAS_ANALYSIS = True
except ImportError:
    HAS_ANALYSIS = False

logger = logging.getLogger(__name__)

CHECKABLE_EXTENSIONS = frozenset({"flac", "wav", "aiff", "aif"})


def not_checked_display(extension: str) -> str:
    """Line shown when the spectrum check cannot read a lossless format."""
    return f"\u2754 Lossless check: not checked ({extension.upper()})"


@dataclass
class LosslessVerdict:
    """Result of the lossless spectrum check."""

    verdict: str  # AUTHENTIC, WARNING, SUSPICIOUS, FAKE
    cutoff_khz: float
    nyquist_khz: float
    sample_rate: int
    bit_depth: int

    @property
    def emoji(self) -> str:
        return {
            "AUTHENTIC": "\u2705",
            "WARNING": "\u26a0\ufe0f",
            "SUSPICIOUS": "\U0001f7e0",
            "FAKE": "\u274c",
        }.get(self.verdict, "\u2753")

    @property
    def display(self) -> str:
        if self.verdict == "AUTHENTIC":
            return f"{self.emoji} Lossless OK (spectrum to {self.cutoff_khz:.1f}kHz)"
        label = {
            "WARNING": "Possible transcode",
            "SUSPICIOUS": "Likely transcode",
            "FAKE": "Fake lossless",
        }.get(self.verdict, self.verdict)
        return f"{self.emoji} {label} (cutoff {self.cutoff_khz:.1f}kHz)"


def analyze_lossless(filepath: str, sample_duration: float = 30.0) -> LosslessVerdict | None:
    """Analyze a checkable lossless file for spectral authenticity."""
    if not HAS_ANALYSIS:
        return None
    try:
        return _analyze(filepath, sample_duration)
    except Exception:
        logger.exception("Lossless check failed: %s", filepath)
        return None


def _analyze(filepath: str, sample_duration: float) -> LosslessVerdict | None:
    info = sf.info(filepath)
    sample_rate = info.samplerate
    nyquist = sample_rate / 2
    bit_depth = _bit_depth(info)

    data = _read_mono_sample(filepath, info, sample_duration)
    cutoff = _spectral_cutoff(data, sample_rate, nyquist)
    if cutoff is None:
        logger.info("Lossless check skipped for %s: too few high-frequency bins", filepath)
        return None

    cutoff_khz = cutoff / 1000
    nyquist_khz = nyquist / 1000
    return LosslessVerdict(
        verdict=_classify(cutoff_khz, nyquist_khz),
        cutoff_khz=round(cutoff_khz, 2),
        nyquist_khz=round(nyquist_khz, 2),
        sample_rate=sample_rate,
        bit_depth=bit_depth,
    )


def _bit_depth(info) -> int:
    match = re.search(r"\d+", info.subtype or "")
    return int(match.group()) if match else 0


def _read_mono_sample(filepath: str, info, sample_duration: float):
    start_frame = max(0, info.frames // 3)
    frames_to_read = min(int(info.samplerate * sample_duration), info.frames - start_frame)
    data, _ = sf.read(filepath, start=start_frame, frames=frames_to_read, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data


def _spectral_cutoff(data, sample_rate: int, nyquist: float) -> float | None:
    """Frequency (Hz) where high-band energy drops; Nyquist when intact; None if unmeasurable."""
    rms = np.sqrt(np.mean(data**2))
    if rms < 0.001:
        return float(nyquist)

    nperseg = min(8192, len(data))
    freqs, psd = signal.welch(data, fs=sample_rate, nperseg=nperseg, noverlap=nperseg // 2)
    psd_db = 10 * np.log10(psd + 1e-30)

    high_mask = freqs >= 14000
    high_freqs = freqs[high_mask]
    high_psd = psd_db[high_mask]
    if len(high_freqs) < 10:
        return None

    mid_mask = (freqs >= 2000) & (freqs <= 8000)
    mid_energy = np.mean(psd_db[mid_mask]) if np.any(mid_mask) else -60
    dropout_idx = np.where(high_psd < mid_energy - 30)[0]
    return _first_sustained_dropout(high_freqs, dropout_idx, nyquist)


def _first_sustained_dropout(high_freqs, dropout_idx, nyquist: float) -> float:
    consecutive = 0
    for i in range(len(dropout_idx) - 1):
        if dropout_idx[i + 1] - dropout_idx[i] != 1:
            consecutive = 0
            continue
        consecutive += 1
        if consecutive >= 3:
            return float(high_freqs[dropout_idx[i - 2]])
    return float(nyquist)


def _classify(cutoff_khz: float, nyquist_khz: float) -> str:
    if cutoff_khz >= nyquist_khz * 0.92:
        return "AUTHENTIC"
    if cutoff_khz >= 19.0:
        return "WARNING"
    if cutoff_khz >= 17.0:
        return "SUSPICIOUS"
    return "FAKE"
