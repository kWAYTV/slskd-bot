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
        info = sf.info(filepath)
        sr = info.samplerate
        nyquist = sr / 2

        bit_match = re.search(r"\d+", info.subtype or "")
        bit_depth = int(bit_match.group()) if bit_match else 0

        total_frames = info.frames
        start_frame = max(0, total_frames // 3)
        frames_to_read = min(int(sr * sample_duration), total_frames - start_frame)

        data, _ = sf.read(filepath, start=start_frame, frames=frames_to_read, dtype="float32")

        if data.ndim > 1:
            data = data.mean(axis=1)

        rms = np.sqrt(np.mean(data**2))
        if rms < 0.001:
            return FlacVerdict(
                verdict="AUTHENTIC",
                cutoff_khz=nyquist / 1000,
                nyquist_khz=nyquist / 1000,
                sample_rate=sr,
                bit_depth=bit_depth,
            )

        nperseg = min(8192, len(data))
        freqs, psd = signal.welch(data, fs=sr, nperseg=nperseg, noverlap=nperseg // 2)
        psd_db = 10 * np.log10(psd + 1e-30)

        high_freq_mask = freqs >= 14000
        high_freqs = freqs[high_freq_mask]
        high_psd = psd_db[high_freq_mask]

        if len(high_freqs) < 10:
            return FlacVerdict(
                verdict="AUTHENTIC",
                cutoff_khz=nyquist / 1000,
                nyquist_khz=nyquist / 1000,
                sample_rate=sr,
                bit_depth=bit_depth,
            )

        mid_mask = (freqs >= 2000) & (freqs <= 8000)
        mid_energy = np.mean(psd_db[mid_mask]) if np.any(mid_mask) else -60

        threshold = mid_energy - 30
        cutoff_idx = np.where(high_psd < threshold)[0]

        cutoff_freq = float(nyquist)
        if len(cutoff_idx) > 0:
            consecutive = 0
            for i in range(len(cutoff_idx) - 1):
                if cutoff_idx[i + 1] - cutoff_idx[i] == 1:
                    consecutive += 1
                    if consecutive >= 3:
                        cutoff_freq = float(high_freqs[cutoff_idx[i - 2]])
                        break
                else:
                    consecutive = 0

        cutoff_khz = cutoff_freq / 1000
        nyquist_khz = nyquist / 1000

        if cutoff_khz >= nyquist_khz * 0.92:
            verdict = "AUTHENTIC"
        elif cutoff_khz >= 19.0:
            verdict = "WARNING"
        elif cutoff_khz >= 17.0:
            verdict = "SUSPICIOUS"
        else:
            verdict = "FAKE"

        return FlacVerdict(
            verdict=verdict,
            cutoff_khz=round(cutoff_khz, 2),
            nyquist_khz=round(nyquist_khz, 2),
            sample_rate=sr,
            bit_depth=bit_depth,
        )

    except Exception:
        logger.exception("Failed to analyze FLAC: %s", filepath)
        return None
