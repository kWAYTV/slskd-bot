"""own_like_library sets mode (and group when os.chown exists)."""

import os
import stat
from pathlib import Path

from slskd_importer.library.ownership import LIBRARY_FILE_MODE, own_like_library


def test_own_like_library_sets_file_mode(tmp_path: Path):
    library = tmp_path / "music"
    library.mkdir()
    target = library / "song.flac"
    target.write_bytes(b"x")
    os.chmod(target, 0o600)
    own_like_library(str(target), str(library))
    mode = stat.S_IMODE(target.stat().st_mode)
    # Unix: exact LIBRARY_FILE_MODE. Windows: chmod is limited; just ensure no raise.
    if os.name != "nt":
        assert mode == LIBRARY_FILE_MODE
    else:
        assert mode != 0


def test_own_like_library_skips_symlink(tmp_path: Path):
    library = tmp_path / "music"
    library.mkdir()
    real = library / "real.flac"
    real.write_bytes(b"x")
    link = library / "link.flac"
    try:
        link.symlink_to(real)
    except OSError:
        # Windows without symlink privilege
        return
    own_like_library(str(link), str(library))  # must not raise
