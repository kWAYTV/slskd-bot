"""replace_in_library keeps the exact library filename."""

from __future__ import annotations

from pathlib import Path

from slskd_importer.sweep.place import replace_in_library


def test_take_new_same_format_keeps_exact_name(tmp_path: Path):
    library = tmp_path / "music"
    library.mkdir()
    replaced = library / ".sweep-replaced"
    original = library / "Artist - Title.flac"
    original.write_bytes(b"old")
    proposal = library / ".sweep-review" / "Artist - Title.flac.sweep"
    proposal.parent.mkdir()
    proposal.write_bytes(b"new-flac")

    target, parked = replace_in_library(str(original), str(proposal), "flac", str(replaced), move=True)

    assert Path(target) == original
    assert original.read_bytes() == b"new-flac"
    assert Path(parked).name == "Artist - Title.flac.sweep"
    assert Path(parked).read_bytes() == b"old"
    assert not proposal.exists()


def test_take_new_format_upgrade_keeps_stem(tmp_path: Path):
    library = tmp_path / "music"
    library.mkdir()
    replaced = library / ".sweep-replaced"
    original = library / "Artist - Title.mp3"
    original.write_bytes(b"old-mp3")
    proposal = library / "cand.flac"
    proposal.write_bytes(b"new-flac")

    target, parked = replace_in_library(str(original), str(proposal), "flac", str(replaced), move=True)

    assert Path(target) == library / "Artist - Title.flac"
    assert Path(target).read_bytes() == b"new-flac"
    assert not original.exists()
    assert Path(parked).read_bytes() == b"old-mp3"
