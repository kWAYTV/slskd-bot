"""Finding a song anywhere in the collection by file name."""

from __future__ import annotations

from pathlib import Path

import pytest

from slskd_importer.catalog.names import same_artist
from slskd_importer.library.index import LibraryIndex, split_name


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")


@pytest.fixture
def collection(tmp_path: Path) -> Path:
    touch(tmp_path / "soulseek" / "2026" / "Daft Punk - One More Time.flac")
    touch(tmp_path / "rekordbox" / "House" / "03 - Beyoncé - Halo.mp3")
    touch(tmp_path / "albums" / "Isaiah - Usually EP - Ain't Nobody Shake It Down.flac")
    touch(tmp_path / "edits" / "Fisher - Losing It (Extended Mix).flac")
    touch(tmp_path / "duos" / "Camelphat & Elderbrook - Cola.flac")
    touch(tmp_path / "soulseek" / "incoming" / "peer" / "Bicep - Glue.flac")
    touch(tmp_path / ".stversions" / "Old - Song.flac")
    touch(tmp_path / "loose" / "just a title.flac")
    touch(tmp_path / "notes" / "Artist - Notes.txt")
    return tmp_path


@pytest.mark.parametrize(
    ("artist", "title", "found"),
    [
        ("Daft Punk", "One More Time", "soulseek/2026/Daft Punk - One More Time.flac"),
        ("daft punk", "ONE MORE TIME", "soulseek/2026/Daft Punk - One More Time.flac"),
        ("Beyonce", "Halo", "rekordbox/House/03 - Beyoncé - Halo.mp3"),
        ("Isaiah", "Ain’t Nobody Shake It Down", "albums/Isaiah - Usually EP - Ain't Nobody Shake It Down.flac"),
        ("CamelPhat", "Cola", "duos/Camelphat & Elderbrook - Cola.flac"),
        ("Fisher", "Losing It (Extended Mix)", "edits/Fisher - Losing It (Extended Mix).flac"),
        ("Fisher", "Losing It", None),  # the extended mix is another version
        ("Someone Else", "One More Time", None),
        ("Bicep", "Glue", None),  # only in the raw downloads folder
        ("Old", "Song", None),  # hidden folder
        ("Artist", "Notes", None),  # not audio
        ("", "just a title", None),
    ],
)
def test_find(collection: Path, artist: str, title: str, found: str | None):
    index = LibraryIndex(str(collection), exclude=(str(collection / "soulseek" / "incoming"),))
    assert index.find(artist, title) == found


def test_new_files_show_after_forget_and_deleted_ones_never_match(collection: Path):
    index = LibraryIndex(str(collection))
    assert index.find("New", "Tune") is None
    touch(collection / "New - Tune.flac")
    assert index.find("New", "Tune") is None  # cached listing
    index.forget()
    assert index.find("New", "Tune") == "New - Tune.flac"
    (collection / "New - Tune.flac").unlink()
    assert index.find("New", "Tune") is None


def test_missing_root_is_empty(tmp_path: Path):
    assert LibraryIndex(str(tmp_path / "nope")).find("A", "B") is None


def test_name_parsing():
    assert split_name("01 - Artist - Title") == ("artist", "title")
    assert split_name("01. Artist - Title") == ("artist", "title")
    assert split_name("Artist - Album - 07 Title") == ("artist", "title")
    assert split_name("Title Only") is None
    assert same_artist("a", "a and b") and same_artist("a and b", "a") and not same_artist("a", "c")
