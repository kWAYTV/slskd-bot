"""Library file/folder ownership: mode and group matching OUTPUT_DIR."""

from __future__ import annotations

import contextlib
import logging
import os

logger = logging.getLogger(__name__)

LIBRARY_FILE_MODE = 0o664
LIBRARY_DIR_MODE = 0o775


def own_like_library(path: str, library: str) -> None:
    """Give *path* LIBRARY_FILE_MODE or LIBRARY_DIR_MODE and the library folder's group.

    The group change needs the process to be in that group (compose ``group_add``);
    without it the mode is still set. Symlinks are left alone.
    """
    if os.path.islink(path):
        logger.warning("Not changing the owner of %s: it is a symlink", path)
        return
    with contextlib.suppress(OSError):
        os.chmod(path, LIBRARY_DIR_MODE if os.path.isdir(path) else LIBRARY_FILE_MODE)
    # os.chown is Unix-only; Docker/Linux library mounts need the group match.
    if hasattr(os, "chown"):
        with contextlib.suppress(OSError):
            os.chown(path, -1, os.stat(library).st_gid)
