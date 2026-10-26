"""Treble and clipping measures for sweep proposals."""

from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass

from slskd_importer.sweep.audit import _nice

logger = logging.getLogger(__name__)

TREBLE_BAND_HZ = (5000, 15000)
# A proposal this much duller than the owner's copy is never offered.
TREBLE_MAX_LOSS_DB = 3.0
# Clipping is counted as flat tops: runs of three or more equal samples above
# -6 dBFS. A clipped file keeps its flat tops when it is turned down later.
# A clean 16-bit CD shows a few dozen from loud bass (43 on the Zombies CD);
# the same file clipped by 4 dB showed 8166.
CLIP_LEVEL = 2**30  # -6 dBFS in 32-bit samples
# A proposal with more flat tops per minute than this, and more than CLIP_FACTOR
# times the owner's, is never offered.
CLIP_MAX_PER_MIN = 100
CLIP_FACTOR = 4
SOUND_TIMEOUT_SECS = 900
# A decode that stops before this share of the file's length is not judged.
SOUND_MIN_COVERAGE = 0.9


@dataclass
class Sound:
    """How a file sounds: *treble* in dB (see TREBLE_BAND_HZ), *clips* flat tops per minute."""

    treble: float
    clips: float


def sound(path: str) -> Sound | None:
    """Measure the treble and the clipping of *path* in one streamed decode.

    None when it cannot be decoded, when the decode covers less than
    SOUND_MIN_COVERAGE of the file's length (a partial measure could refuse a
    good copy), or when it takes over SOUND_TIMEOUT_SECS: a timer kills ffmpeg
    then, so a stalled decode cannot block the read.
    """
    import json

    import numpy as np

    try:
        info = json.loads(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=sample_rate,channels:format=duration",
                    "-of",
                    "json",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout
            or "{}"
        )
        stream = (info.get("streams") or [{}])[0]
        rate, channels = int(stream.get("sample_rate") or 0), int(stream.get("channels") or 0)
        duration = float((info.get("format") or {}).get("duration") or 0)
        if rate <= 0 or channels <= 0:
            return None
        proc = subprocess.Popen(
            _nice(["ffmpeg", "-v", "error", "-i", path, "-f", "s32le", "-"]),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        logger.warning("Could not measure the sound of %s", path, exc_info=True)
        return None
    timer = threading.Timer(SOUND_TIMEOUT_SECS, proc.kill)
    timer.start()
    window = np.hanning(rate)
    spectrum = np.zeros(rate // 2 + 1)
    flat_tops = 0
    samples = 0
    frame = channels * 4
    try:
        while True:
            chunk = proc.stdout.read(rate * frame)
            if len(chunk) < frame:
                break
            x = np.frombuffer(chunk[: len(chunk) // frame * frame], dtype="<i4").reshape(-1, channels)
            samples += len(x)
            for c in range(channels):
                v = x[:, c].astype(np.int64)
                loud = np.abs(v) >= CLIP_LEVEL
                same = np.concatenate(([0], ((v[1:] == v[:-1]) & loud[1:] & loud[:-1]).astype(np.int8), [0]))
                edges = np.diff(same)
                lengths = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
                flat_tops += int((lengths >= 2).sum())
            if len(x) == rate:
                mono = x.astype(np.float64).mean(axis=1) / 2**31
                spectrum += np.abs(np.fft.rfft(mono * window)) ** 2
    finally:
        timed_out = not timer.is_alive()
        timer.cancel()
        proc.kill()
        proc.wait()
    if timed_out:
        logger.warning("Measuring the sound of %s took over %d s", path, SOUND_TIMEOUT_SECS)
        return None
    if duration and samples / rate < SOUND_MIN_COVERAGE * duration:
        logger.warning("Only %.0f of %.0f s of %s decoded; its sound is not judged", samples / rate, duration, path)
        return None
    freqs = np.fft.rfftfreq(rate, 1 / rate)
    total = spectrum[(freqs > 20) & (freqs < TREBLE_BAND_HZ[1])].sum()
    treble = spectrum[(freqs >= TREBLE_BAND_HZ[0]) & (freqs < TREBLE_BAND_HZ[1])].sum()
    if samples < rate or total <= 0 or treble <= 0:
        return None
    return Sound(
        treble=round(10 * float(np.log10(treble / total)), 1), clips=round(flat_tops / (samples / rate / 60), 1)
    )


def sounds_worse(original: Sound | None, candidate: Sound | None, original_lossy: bool = False) -> str | None:
    """Why the candidate sounds worse than the owner's copy (duller or clipped), or None.

    Nothing is judged when either file could not be measured. A lossy
    original's flat tops are not compared: its decoder never keeps them.
    """
    if original is None or candidate is None:
        return None
    if original.treble - candidate.treble > TREBLE_MAX_LOSS_DB:
        return f"duller than yours (treble {candidate.treble - original.treble:+.1f} dB)"
    if candidate.clips > CLIP_MAX_PER_MIN and (original_lossy or candidate.clips > CLIP_FACTOR * original.clips):
        return f"clipped ({candidate.clips:.0f} flat tops a minute, yours {original.clips:.0f})"
    return None


def clipping_words(clips: float) -> str:
    """Flat tops a minute in words: none, slight or heavy."""
    if clips < CLIP_MAX_PER_MIN / 4:
        return "none"
    return "slight" if clips <= CLIP_MAX_PER_MIN else "heavy"


def describe_sound(s: Sound | None, mine: Sound | None = None) -> str:
    """One line for a caption: "treble -17.1 dB, clipping none", with the gap to *mine* when given."""
    if s is None:
        return ""
    line = f"treble {s.treble:.1f} dB"
    if mine is not None:
        gap = s.treble - mine.treble
        line += (
            f" ({abs(gap):.1f} dB {'brighter' if gap > 0 else 'duller'} than yours)"
            if abs(gap) >= 0.5
            else (" (same as yours)")
        )
    line += f", clipping {clipping_words(s.clips)} ({s.clips:.0f}/min)"
    return line
