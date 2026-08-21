"""FLAC authenticity analysis via spectral cutoff detection.

True lossless audio has energy up to the Nyquist frequency (~22.05 kHz at
44.1 kHz). Lossy-to-lossless transcodes show a sharp cutoff between 16-20 kHz.

Verdicts:
    AUTHENTIC  - spectrum extends to Nyquist
    WARNING    - cutoff 19-20 kHz
    SUSPICIOUS - cutoff 17-19 kHz
    FAKE       - cutoff <17 kHz
"""

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


@dataclass
class FlacVerdict:
    """Result of FLAC authenticity analysis."""

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
        """One-line human-readable summary for Telegram."""
        if self.verdict == "AUTHENTIC":
            return f"{self.emoji} Lossless OK (spectrum to {self.cutoff_khz:.1f}kHz)"
        label = {
            "WARNING": "Possible transcode",
            "SUSPICIOUS": "Likely transcode",
            "FAKE": "Fake lossless",
        }.get(self.verdict, self.verdict)
        return f"{self.emoji} {label} (cutoff {self.cutoff_khz:.1f}kHz)"


def analyze_flac(filepath: str, sample_duration: float = 30.0) -> FlacVerdict | None:
    """Analyze a FLAC file for losslessness via spectral cutoff detection."""
    if not HAS_ANALYSIS:
        return None
    try:
        return _analyze(filepath, sample_duration)
    except Exception:
        logger.exception("Failed to analyze FLAC: %s", filepath)
        return None


def _analyze(filepath: str, sample_duration: float) -> FlacVerdict:
    info = sf.info(filepath)
    sample_rate = info.samplerate
    nyquist = sample_rate / 2

    data = _read_mono_sample(filepath, info, sample_duration)
    cutoff_khz = _spectral_cutoff(data, sample_rate, nyquist) / 1000
    nyquist_khz = nyquist / 1000

    return FlacVerdict(
        verdict=_classify(cutoff_khz, nyquist_khz),
        cutoff_khz=round(cutoff_khz, 2),
        nyquist_khz=round(nyquist_khz, 2),
        sample_rate=sample_rate,
        bit_depth=_bit_depth(info),
    )


def _bit_depth(info) -> int:
    match = re.search(r"\d+", info.subtype or "")
    return int(match.group()) if match else 0


def _read_mono_sample(filepath: str, info, sample_duration: float):
    """Read a mono sample starting a third of the way into the file."""
    start_frame = max(0, info.frames // 3)
    frames_to_read = min(int(info.samplerate * sample_duration), info.frames - start_frame)

    data, _ = sf.read(filepath, start=start_frame, frames=frames_to_read, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data


def _spectral_cutoff(data, sample_rate: int, nyquist: float) -> float:
    """Frequency (Hz) where high-band energy drops off; Nyquist when it doesn't."""
    rms = np.sqrt(np.mean(data**2))
    if rms < 0.001:
        # Near-silence: nothing to measure, assume the spectrum is intact.
        return float(nyquist)

    nperseg = min(8192, len(data))
    freqs, psd = signal.welch(data, fs=sample_rate, nperseg=nperseg, noverlap=nperseg // 2)
    psd_db = 10 * np.log10(psd + 1e-30)

    high_freqs = freqs[freqs >= 14000]
    high_psd = psd_db[freqs >= 14000]
    if len(high_freqs) < 10:
        return float(nyquist)

    mid_mask = (freqs >= 2000) & (freqs <= 8000)
    mid_energy = np.mean(psd_db[mid_mask]) if np.any(mid_mask) else -60
    dropout_idx = np.where(high_psd < mid_energy - 30)[0]
    return _first_sustained_dropout(high_freqs, dropout_idx, nyquist)


def _first_sustained_dropout(high_freqs, dropout_idx, nyquist: float) -> float:
    """First frequency where at least 4 consecutive bins fall below threshold."""
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
