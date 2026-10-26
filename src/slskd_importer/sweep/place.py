"""Library filesystem helpers for the sweep: list, place, replace, tags."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import stat

from slskd_importer.library.formats import AUDIO_EXTENSIONS
from slskd_importer.library.ownership import own_like_library
from slskd_importer.records.sweep_models import SweepRun, SweepSong
from slskd_importer.sweep import audit as rules
from slskd_importer.sweep.outcomes import CD_RECHECK_SECS, PARKED_SUFFIX

logger = logging.getLogger(__name__)


def library_files(root: str) -> list[str]:
    """Audio files at the top level of *root* (hidden ones left out), by name."""
    try:
        entries = os.listdir(root)
    except OSError:
        return []
    names = []
    for name in entries:
        ext = os.path.splitext(name)[1].lstrip(".").lower()
        if not name.startswith(".") and ext in AUDIO_EXTENSIONS and os.path.isfile(os.path.join(root, name)):
            names.append(name)
    return sorted(names)


def is_due(song: SweepSong, run: SweepRun, now: float) -> bool:
    """Whether *song* is checked in *run*: not yet in this run, and its tier's recheck time has come."""
    if song.last_checked_at is not None and song.last_checked_at >= run.started_at:
        return False
    if run.force or song.last_checked_at is None:
        return True
    if song.tier == rules.TIER_HIRES:
        return False
    if song.tier == rules.TIER_CD:
        return now - song.last_checked_at >= CD_RECHECK_SECS
    return True


def free_path(path: str) -> str:
    """*path*, or "<base>.<n><suffix>" with the first n that is not taken (suffix = PARKED_SUFFIX or extension)."""
    if not os.path.exists(path):
        return path
    base, suffix = (
        (path[: -len(PARKED_SUFFIX)], PARKED_SUFFIX) if path.endswith(PARKED_SUFFIX) else os.path.splitext(path)
    )
    n = 2
    while os.path.exists(f"{base}.{n}{suffix}"):
        n += 1
    return f"{base}.{n}{suffix}"


def match_owner(path: str, like: str | None, library: str | None = None) -> None:
    """Give *path* the mode, owner and group of the file *like* (owner and group only when allowed).

    Without a *like* file, a *library* path gives it the library's own mode and group (own_like_library).
    """
    if not like or not os.path.isfile(like):
        if library:
            own_like_library(path, library)
        return
    try:
        st = os.stat(like)
    except OSError:
        return
    with contextlib.suppress(OSError):
        os.chmod(path, stat.S_IMODE(st.st_mode))
    if hasattr(os, "chown"):
        with contextlib.suppress(OSError):
            os.chown(path, st.st_uid, st.st_gid)


def _make_library_dir(path: str) -> None:
    """Create a sweep folder inside the library with the library's own mode and group (also when it exists)."""
    os.makedirs(path, exist_ok=True)
    own_like_library(path, os.path.dirname(os.path.normpath(path)))


def place(source: str, target: str, like: str | None, move: bool = False) -> str:
    """Put *source* at *target* atomically: copy (or move) to "<target>.importing", match *like*, rename.

    *move* is for a source on the library's own file system (a staged
    proposal); a download is copied. Raises FileExistsError when *target* is taken.
    """
    if os.path.exists(target):
        raise FileExistsError(target)
    tmp = target + ".importing"
    try:
        if move:
            os.replace(source, tmp)
        else:
            shutil.copyfile(source, tmp)
        match_owner(tmp, like, os.path.dirname(target))
        os.replace(tmp, target)
    except BaseException:
        if move and os.path.exists(tmp) and not os.path.exists(source):
            with contextlib.suppress(OSError):
                os.replace(tmp, source)
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    return target


def replace_in_library(original: str, source: str, ext: str, replaced_dir: str, move: bool = False) -> tuple[str, str]:
    """Replace the library file *original* with *source* (format *ext*); returns (new path, parked original).

    Same format: the new file takes the original's exact path and name. Different
    format: "<original's stem>.<ext>" next to it. Written atomically with the
    original's mode and owner. The original is parked as
    <replaced_dir>/<its name>.sweep (a free name). When the new file cannot be
    put in place, the original goes back where it was. A *target* of another
    format that already exists is never overwritten (FileExistsError).
    """
    folder = os.path.dirname(original)
    base, orig_dot_ext = os.path.splitext(os.path.basename(original))
    if orig_dot_ext.lstrip(".").lower() == ext.lower():
        # Keep the exact library filename (casing, spelling) when the format matches.
        target = original
    else:
        target = os.path.join(folder, f"{base}.{ext}")
    if os.path.normpath(target) != os.path.normpath(original) and os.path.exists(target):
        raise FileExistsError(target)
    tmp = target + ".importing"
    try:
        if move:
            os.replace(source, tmp)
        else:
            shutil.copyfile(source, tmp)
        match_owner(tmp, original)
        _make_library_dir(replaced_dir)
        parked = free_path(os.path.join(replaced_dir, os.path.basename(original) + PARKED_SUFFIX))
        os.replace(original, parked)
        try:
            os.replace(tmp, target)
        except BaseException:
            os.replace(parked, original)
            raise
    except BaseException:
        if move and os.path.exists(tmp) and not os.path.exists(source):
            with contextlib.suppress(OSError):
                os.replace(tmp, source)
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    return target, parked


_CARRIED_TAGS = ("artist", "title", "album", "date", "tracknumber", "genre", "albumartist")


def carry_tags_and_cover(original: str, candidate: str) -> None:
    """Copy into *candidate* the original's tags it lacks, and the original's cover when it has none. Best effort."""
    import mutagen

    from slskd_importer.library.artwork import embed_artwork_into_file

    try:
        o = mutagen.File(original, easy=True)
        c = mutagen.File(candidate, easy=True)
        if o is not None and c is not None and o.tags is not None:
            if c.tags is None:
                c.add_tags()
            changed = False
            for key in _CARRIED_TAGS:
                value = o.tags.get(key)
                if value and not c.tags.get(key):
                    c.tags[key] = value
                    changed = True
            if changed:
                c.save()
    except Exception:
        logger.warning("Sweep: tags of %s not carried over", original, exc_info=True)
    try:
        cover = _cover_of(original)
        if cover:
            embed_artwork_into_file(candidate, cover)
    except Exception:
        logger.warning("Sweep: cover of %s not carried over", original, exc_info=True)


def _cover_of(path: str) -> bytes | None:
    import base64

    import mutagen
    import mutagen.flac

    f = mutagen.File(path)
    if f is None:
        return None
    if getattr(f, "pictures", None):
        return f.pictures[0].data
    tags = f.tags
    if tags is None:
        return None
    for key in list(tags.keys()):
        if key.startswith("APIC"):
            return tags[key].data
    if "covr" in tags and tags["covr"]:
        return bytes(tags["covr"][0])
    blocks = tags.get("metadata_block_picture") if hasattr(tags, "get") else None
    if blocks:
        return mutagen.flac.Picture(base64.b64decode(blocks[0])).data
    return None


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------
