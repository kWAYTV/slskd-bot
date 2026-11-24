"""Media sources: yt-dlp info dicts become free-text tracklists.

Fixtures are trimmed copies of real yt-dlp output (flat for YouTube, full for the rest).
"""

from __future__ import annotations

import pytest

from slskd_importer.sources.media import NO_TRACKS, UNREADABLE, is_media_url, resolve_media
from slskd_importer.sources.tracklist import SourceError

URL = "https://www.youtube.com/playlist?list=PL123"


def _resolve(info: dict | None, url: str = URL):
    return resolve_media(url, extract=lambda _url: info)


def _queries(info: dict) -> list[str]:
    return [entry.query for entry in _resolve(info).entries]


# Flat YouTube playlist entries carry only title + channel/uploader — never artist/track.
YOUTUBE_PLAYLIST = {
    "_type": "playlist",
    "id": "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
    "title": "Popular Music Videos",
    "extractor_key": "YoutubeTab",
    "entries": [
        {
            "_type": "url",
            "title": "Real Boston Richey - The Type (Official Music Video) ft. YTB Fatt",
            "channel": "RBR",
        },
        {"_type": "url", "title": "La Diabla", "uploader": "Xavi Oficial", "channel": "Xavi Oficial", "duration": 173},
        {"_type": "url", "title": "Arcángel – FN8 ( Video Lyric )", "channel": "Arcangel"},
        {"_type": "url", "title": "[Private video]", "channel": None},
        {"_type": "url", "title": "[Deleted video]"},
        None,
        {"_type": "url", "title": "La Diabla", "channel": "Xavi Oficial"},
    ],
}

YOUTUBE_MUSIC_ALBUM = {
    "_type": "playlist",
    "id": "OLAK5uy_kNhM2yaBTOVwrcZJepB1C9P3-n5_Sfy5c",
    "title": "Album - Random Access Memories",
    "extractor_key": "YoutubeTab",
    "entries": [
        {"_type": "url", "title": "Give Life Back to Music", "uploader": "Daft Punk", "channel": "Daft Punk"},
        {"_type": "url", "title": "Instant Crush (feat. Julian Casablancas)", "channel": "Daft Punk - Topic"},
    ],
}

# Full SoundCloud extraction: "track" repeats the upload title; "artist" is only sometimes present.
SOUNDCLOUD_SET = {
    "_type": "playlist",
    "title": "Major Lazer - Peace Is The Mission",
    "album_type": "album",
    "album_artist": "Major Lazer",
    "extractor_key": "SoundcloudSet",
    "entries": [
        {"title": "Major Lazer - Be Together (feat. Wild Belle)", "uploader": "Major Lazer"},
        {
            "title": "Major Lazer & DJ Snake - Lean On (feat. MØ)",
            "track": "Major Lazer & DJ Snake - Lean On (feat. MØ)",
            "artist": "Major Lazer",
            "artists": ["Major Lazer"],
            "uploader": "Major Lazer",
        },
        {"title": "Roll The Bass"},
    ],
}

BANDCAMP_ALBUM = {
    "_type": "playlist",
    "id": "in-rainbows",
    "title": "In Rainbows",
    "extractor_key": "BandcampAlbum",
    "entries": [
        {"title": "Radiohead - 15 Step", "artist": "Radiohead", "artists": ["Radiohead"], "track": "15 Step"},
        {"title": "Radiohead - Nude", "artist": "Radiohead", "artists": ["Radiohead"], "track": "Nude"},
    ],
}

YOUTUBE_MIX = {
    "id": "ZtA-S-3a7XM",
    "title": "MELODIC TECHNO & PEAK TIME MIX 2026",
    "channel": "Some Mix Channel",
    "duration": 5681,
    "chapters": [
        {"start_time": 0, "title": "Intro", "end_time": 39},
        {"start_time": 39, "title": "ArioVistus - Close To Me", "end_time": 308},
        {"start_time": 308, "title": "01. CALIAN & Synoco - Chasing Love", "end_time": 554},
        {"start_time": 554, "title": "[12:30] FVBLS - Sit Back", "end_time": 771},
        {"start_time": 771, "title": "5) Lombardo - Light In The Dark (Extended Mix)", "end_time": 993},
        {"start_time": 993, "title": "06 - OZO (UA) - The Rhythm", "end_time": 1225},
        {"start_time": 1225, "title": "YellowHeads - Cosmic Grid (Peak Mode Mix) @YellowHeadsTechno", "end_time": 1462},
        {"start_time": 1462, "title": "ID - ID", "end_time": 1722},
        {"start_time": 1722, "title": "ID - BELLE", "end_time": 1974},
        {"start_time": 1974, "title": "Outro", "end_time": 2181},
    ],
}


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://music.youtube.com/playlist?list=OLAK5uy_abc",
        "https://m.youtube.com/playlist?list=PL123",
        "https://soundcloud.com/majorlazer/sets/peace-is-the-mission",
        "https://radiohead.bandcamp.com/album/in-rainbows",
        "youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_is_media_url_accepts_supported_hosts(url: str) -> None:
    assert is_media_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
        "spotify:track:4uLU6hMCjMI75M1A2tKUQC",
        "https://www.1001tracklists.com/tracklist/140z3slt/some-set.html",
        "https://www.mixesdb.com/w/2026-10-24_-_Miss_Monique_-_Essential_Mix",
        "https://notyoutube.com/watch?v=1",
        "https://example.com/?next=youtube.com",
        "daft punk - one more time",
        "",
    ],
)
def test_is_media_url_rejects_other_links(url: str) -> None:
    assert not is_media_url(url)


def test_youtube_playlist_builds_queries_from_title_and_channel() -> None:
    tracklist = _resolve(YOUTUBE_PLAYLIST)

    assert tracklist.kind == "playlist"
    assert tracklist.name == "Popular Music Videos"
    assert tracklist.url == URL
    assert [entry.query for entry in tracklist.entries] == [
        "Real Boston Richey - The Type ft. YTB Fatt",
        "Xavi Oficial - La Diabla",
        "Arcángel – FN8",
    ]
    assert all(entry.track is None for entry in tracklist.entries)


def test_youtube_music_album_strips_prefix_and_topic_suffix() -> None:
    tracklist = _resolve(YOUTUBE_MUSIC_ALBUM)

    assert tracklist.kind == "album"
    assert tracklist.name == "Random Access Memories"
    assert [entry.query for entry in tracklist.entries] == [
        "Daft Punk - Give Life Back to Music",
        "Daft Punk - Instant Crush (feat. Julian Casablancas)",
    ]


def test_soundcloud_set_keeps_upload_titles_and_falls_back_to_album_artist() -> None:
    tracklist = _resolve(SOUNDCLOUD_SET)

    assert tracklist.kind == "album"
    assert [entry.query for entry in tracklist.entries] == [
        "Major Lazer - Be Together (feat. Wild Belle)",
        "Major Lazer & DJ Snake - Lean On (feat. MØ)",
        "Major Lazer - Roll The Bass",
    ]


def test_bandcamp_album_prefers_structured_artist_and_track() -> None:
    tracklist = _resolve(BANDCAMP_ALBUM)

    assert tracklist.kind == "album"
    assert [entry.query for entry in tracklist.entries] == ["Radiohead - 15 Step", "Radiohead - Nude"]


def test_structured_artist_is_kept_when_the_track_name_has_its_own_dash() -> None:
    info = {"title": "Heroes - 2017 Remaster", "track": "Heroes - 2017 Remaster", "artists": ["David Bowie"]}

    assert _queries(info) == ["David Bowie - Heroes - 2017 Remaster"]


def test_single_video_is_one_track() -> None:
    info = {
        "id": "dQw4w9WgXcQ",
        "title": "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)",
        "channel": "Rick Astley",
        "duration": 213,
    }

    tracklist = _resolve(info)

    assert tracklist.kind == "track"
    assert tracklist.name == info["title"]
    assert [entry.query for entry in tracklist.entries] == ["Rick Astley - Never Gonna Give You Up"]


def test_single_topic_video_uses_first_structured_artist() -> None:
    info = {
        "title": "Fragments of Time (feat. Todd Edwards)",
        "channel": "Daft Punk",
        "artist": "Daft Punk, Todd Edwards",
        "artists": ["Daft Punk", "Todd Edwards"],
        "track": "Fragments of Time (feat. Todd Edwards)",
    }

    assert _queries(info) == ["Daft Punk - Fragments of Time (feat. Todd Edwards)"]


def test_single_item_without_any_artist_uses_the_title() -> None:
    assert _queries({"title": "Mil Townley - 4th November 2026", "duration": 3578}) == [
        "Mil Townley - 4th November 2026"
    ]
    assert _queries({"title": "Untitled jam"}) == ["Untitled jam"]


def test_long_mix_with_chapters_yields_one_entry_per_identified_track() -> None:
    tracklist = _resolve(YOUTUBE_MIX)

    assert tracklist.kind == "mix"
    assert tracklist.name == "MELODIC TECHNO & PEAK TIME MIX 2026"
    assert [entry.query for entry in tracklist.entries] == [
        "ArioVistus - Close To Me",
        "CALIAN & Synoco - Chasing Love",
        "FVBLS - Sit Back",
        "Lombardo - Light In The Dark (Extended Mix)",
        "OZO (UA) - The Rhythm",
        "YellowHeads - Cosmic Grid (Peak Mode Mix)",
    ]


@pytest.mark.parametrize(
    "override",
    [
        {"duration": 600},  # short video with chapters: a song, not a mix
        {"chapters": YOUTUBE_MIX["chapters"][1:4]},  # too few chapters
        {"chapters": [{"title": f"Part {n}"} for n in range(6)]},  # chapters that are not tracks
        {"chapters": None},
    ],
)
def test_items_that_are_not_chaptered_mixes_stay_single_tracks(override: dict) -> None:
    tracklist = _resolve({**YOUTUBE_MIX, **override})

    assert tracklist.kind == "track"
    assert [entry.query for entry in tracklist.entries] == ["Some Mix Channel - MELODIC TECHNO & PEAK TIME MIX 2026"]


def test_entries_are_capped_at_500() -> None:
    info = {"_type": "playlist", "title": "Huge", "entries": [{"title": f"Artist - Song {n}"} for n in range(650)]}

    entries = _resolve(info).entries

    assert len(entries) == 500
    assert entries[-1].query == "Artist - Song 499"


def test_extract_receives_the_url() -> None:
    seen: list[str] = []

    def extract(url: str) -> dict:
        seen.append(url)
        return {"title": "Artist - Song"}

    resolve_media("https://youtu.be/abc", extract=extract)

    assert seen == ["https://youtu.be/abc"]


def test_extractor_failure_becomes_a_source_error() -> None:
    def extract(_url: str) -> dict:
        raise RuntimeError("ERROR: [youtube] abc: Private video")

    with pytest.raises(SourceError) as excinfo:
        resolve_media(URL, extract=extract)

    assert str(excinfo.value) == UNREADABLE


@pytest.mark.parametrize(
    "info",
    [
        None,
        {},
        {"id": "abc", "title": ""},
        {"id": "00000000000", "title": "youtube video #00000000000"},  # yt-dlp's stub for an unavailable video
        {"id": "abc", "title": "[Private video]"},
    ],
)
def test_unreadable_single_item_becomes_a_source_error(info: dict | None) -> None:
    with pytest.raises(SourceError) as excinfo:
        _resolve(info)

    assert str(excinfo.value) == UNREADABLE


@pytest.mark.parametrize(
    "info",
    [
        {"_type": "playlist", "title": "Empty", "entries": []},
        {"_type": "playlist", "title": "Gone", "entries": [{"title": "[Private video]"}, {"title": "[Deleted video]"}]},
        {"_type": "playlist", "title": "Untitled", "entries": [{"id": "432697509", "album": "X"}, None]},
    ],
)
def test_no_usable_entries_becomes_a_source_error(info: dict) -> None:
    with pytest.raises(SourceError) as excinfo:
        _resolve(info)

    assert str(excinfo.value) == NO_TRACKS


def test_share_links_are_followed_to_the_real_page(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from slskd_importer.sources.media import expand_short_link

    def landed(url: str, status: int = 200):
        return lambda *args, **kwargs: httpx.Response(status, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", landed("https://soundcloud.com/isaiah/usually?si=abc&utm_source=clipboard"))
    assert expand_short_link("https://on.soundcloud.com/CfGDY4rx7Azp") == "https://soundcloud.com/isaiah/usually"
    assert expand_short_link("https://soundcloud.com/isaiah/usually") == "https://soundcloud.com/isaiah/usually"

    monkeypatch.setattr(httpx, "get", landed("https://on.soundcloud.com/gone", 404))
    assert expand_short_link("https://on.soundcloud.com/gone") == "https://on.soundcloud.com/gone"

    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", offline)
    assert expand_short_link("https://on.soundcloud.com/x") == "https://on.soundcloud.com/x"
