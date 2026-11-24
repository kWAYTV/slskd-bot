"""The sweep covers a whole folder tree: listing, naming, and replacing in place."""

from __future__ import annotations

from pathlib import Path

from slskd_importer.sweep.audit import Audit
from slskd_importer.sweep.identity import identity, leaf, parse_stem
from slskd_importer.sweep.judge import keep_both_name
from slskd_importer.sweep.place import library_files, replace_in_library


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")
    return path


def test_library_files_walks_subfolders_and_skips_hidden(tmp_path: Path):
    touch(tmp_path / "Top - Song.flac")
    touch(tmp_path / "soulseek" / "2026" / "Artist - Title.flac")
    touch(tmp_path / "rekordbox" / "House" / "B - Two.mp3")
    touch(tmp_path / "notes.txt")
    touch(tmp_path / ".hidden.flac")
    touch(tmp_path / ".sweep-review" / "Artist - Title.flac.sweep")
    touch(tmp_path / ".stversions" / "Old - Copy.flac")
    assert library_files(str(tmp_path)) == [
        "Top - Song.flac",
        "rekordbox/House/B - Two.mp3",
        "soulseek/2026/Artist - Title.flac",
    ]
    assert library_files(str(tmp_path / "missing")) == []


def test_folders_are_not_part_of_the_song_name():
    assert leaf("soulseek/2026/Artist - Title") == "Artist - Title"
    assert leaf("Artist - Title") == "Artist - Title"
    assert parse_stem("soulseek/2026/Artist - Title") == ("Artist", "Title")
    assert identity(Audit(ext="flac"), "Some - Folder/Artist - Title") == ("Artist", "Title")


def test_keep_both_name_stays_in_the_songs_folder():
    name = keep_both_name(
        "soulseek/2026/Artist - Title", "flac", Audit(ext="mp3"), Audit(ext="flac", album="Hits"), lambda n: False
    )
    assert name == "soulseek/2026/Artist - Title (Hits).flac"


def test_take_new_replaces_the_song_in_its_own_folder(tmp_path: Path):
    original = touch(tmp_path / "rekordbox" / "House" / "Artist - Title.mp3")
    proposal = touch(tmp_path / ".sweep-review" / "Artist - Title.flac.sweep")
    target, parked = replace_in_library(
        str(original), str(proposal), "flac", str(tmp_path / ".sweep-replaced"), move=True
    )
    assert Path(target) == tmp_path / "rekordbox" / "House" / "Artist - Title.flac"
    assert Path(parked) == tmp_path / ".sweep-replaced" / "Artist - Title.mp3.sweep"
    assert not original.exists()
