"""Measure a library file: format, decode, spectrum cutoff, tier."""

from __future__ import annotations

import dataclasses
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

from slskd_importer.library.formats import LOSSY_EXTENSIONS
from slskd_importer.library.lossless import CHECKABLE_EXTENSIONS, HAS_ANALYSIS, analyze_lossless

logger = logging.getLogger(__name__)

TIER_DAMAGED = "damaged"  # lossless, but the strict decode found errors
TIER_FAKE = "fake"  # lossless file whose spectrum stops below FAKE_CUTOFF_KHZ: made from a lossy one
TIER_LOSSY = "lossy"  # MP3, AAC, Ogg...
TIER_UNCERTAIN = "uncertain"  # cutoff between FAKE_CUTOFF_KHZ and CD_CUTOFF_KHZ: a good MP3 or an old master
TIER_CD = "cd"  # genuine CD quality
TIER_HIRES = "hires"  # 24-bit above 48 kHz with real content above HIRES_CUTOFF_KHZ
TIERS = (TIER_DAMAGED, TIER_FAKE, TIER_LOSSY, TIER_UNCERTAIN, TIER_CD, TIER_HIRES)

# The tier comes from the measured cutoff, not from the analyzer's verdict: the
# verdict compares the cutoff with the file's Nyquist, so a genuine 24/96 master
# with nothing above 24 kHz reads as suspect, while the cutoff alone separates a
# lossless master from an MP3 inside a FLAC.
CD_CUTOFF_KHZ = 19.5
FAKE_CUTOFF_KHZ = 16.0
HIRES_CUTOFF_KHZ = 24.0
STRICT_DECODE_TIMEOUT_SECS = 900


@dataclass
class Audit:
    """One file measured. *strict* is None for lossy files (not decoded); *cutoff* in kHz, None when unknown."""

    ext: str
    length: float = 0.0
    depth: int | None = None
    rate: int | None = None
    kbps: int | None = None
    artist: str = ""
    title: str = ""
    album: str = ""
    strict: bool | None = None
    cutoff: float | None = None
    tier: str = TIER_UNCERTAIN

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Audit:
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


def tier_of(ext: str, depth: int | None, rate: int | None, strict: bool | None, cutoff: float | None) -> str:
    """The tier of a file from its format, depth, rate, strict decode and cutoff (kHz)."""
    if ext in LOSSY_EXTENSIONS:
        return TIER_LOSSY
    if strict is False:
        return TIER_DAMAGED
    if (depth or 0) >= 24 and (rate or 0) > 48000 and (cutoff or 0) > HIRES_CUTOFF_KHZ:
        return TIER_HIRES
    if cutoff is None:
        return TIER_UNCERTAIN
    if cutoff >= CD_CUTOFF_KHZ:
        return TIER_CD
    if cutoff >= FAKE_CUTOFF_KHZ:
        return TIER_UNCERTAIN
    return TIER_FAKE


def _nice(cmd: list[str]) -> list[str]:
    """*cmd* under `nice -n 19` when nice exists: a sweep must never slow the box down."""
    nice = shutil.which("nice")
    return [nice, "-n", "19", *cmd] if nice else cmd


def strict_decode_ok(path: str) -> bool | None:
    """True when ffmpeg decodes the whole file with CRC checks and stops at no error, False when it reports one.

    None when the decode could not run or did not finish (no ffmpeg, a
    timeout): a tool failure is not proof of damage. tier_of() then goes by the
    cutoff, and better() never accepts a copy that was not decoded.
    """
    try:
        r = subprocess.run(
            _nice(
                ["ffmpeg", "-v", "error", "-xerror", "-err_detect", "crccheck+explode", "-i", path, "-f", "null", "-"]
            ),
            capture_output=True,
            timeout=STRICT_DECODE_TIMEOUT_SECS,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("Strict decode of %s did not finish", path, exc_info=True)
        return None
    stderr = r.stderr.decode(errors="ignore").lower()
    return r.returncode == 0 and not any(
        h in stderr for h in ("decode_frame() failed", "invalid", "error while decoding")
    )


def probe(path: str) -> Audit:
    """Format, length, depth, rate, bitrate and the artist, title and album tags (no decode)."""
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    audit = Audit(ext=ext)
    try:
        import mutagen

        f = mutagen.File(path)
        if f is not None and f.info is not None:
            audit.length = round(float(getattr(f.info, "length", 0) or 0), 1)
            audit.depth = getattr(f.info, "bits_per_sample", None) or None
            audit.rate = getattr(f.info, "sample_rate", None) or None
            audit.kbps = round((getattr(f.info, "bitrate", 0) or 0) / 1000) or None
        easy = mutagen.File(path, easy=True)
        tags = (easy.tags if easy is not None else None) or {}
        audit.artist = (tags.get("artist") or [""])[0]
        audit.title = (tags.get("title") or [""])[0]
        audit.album = (tags.get("album") or [""])[0]
    except Exception:
        logger.debug("Could not read %s with mutagen", path, exc_info=True)
    return audit


def audit(path: str) -> Audit:
    """Measure *path*: probe, then for lossless files the strict decode and the spectral cutoff. Blocking."""
    result = probe(path)
    if result.ext not in LOSSY_EXTENSIONS:
        result.strict = strict_decode_ok(path)
        verdict = analyze_lossless(path) if result.ext in CHECKABLE_EXTENSIONS else None
        result.cutoff = verdict.cutoff_khz if verdict else None
        if verdict:
            result.depth = result.depth or verdict.bit_depth or None
            result.rate = result.rate or verdict.sample_rate or None
    result.tier = tier_of(result.ext, result.depth, result.rate, result.strict, result.cutoff)
    return result


def describe(a: Audit) -> str:
    """One line for a message: "FLAC 16/44.1, cutoff 21.9 kHz" or "MP3 320 kbps"."""
    fmt = a.ext.upper()
    if a.ext in LOSSY_EXTENSIONS:
        return f"{fmt} {a.kbps} kbps" if a.kbps else fmt
    quality = f" {a.depth}/{a.rate / 1000:g}" if a.depth and a.rate else ""
    cutoff = f", cutoff {a.cutoff:.1f} kHz" if a.cutoff is not None else ""
    damaged = ", decode errors" if a.strict is False else ""
    return f"{fmt}{quality}{cutoff}{damaged}"


def missing_tools() -> list[str]:
    """What the sweep cannot measure without: ffmpeg and the analysis extra.

    fpcalc is optional (judge falls back to length and tags), so it is not listed.
    """
    missing = []
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")
    if not HAS_ANALYSIS:
        missing.append("numpy, scipy and soundfile (pip install 'telegram-slskd-local-bot[analysis]')")
    return missing
