"""DJ tracklist pages: HTML becomes a mix tracklist. Fixtures are trimmed copies of real pages."""

from __future__ import annotations

import httpx
import pytest

from slskd_importer.sources import tracklist_pages
from slskd_importer.sources.tracklist import SourceError
from slskd_importer.sources.tracklist_pages import (
    BLOCKED_1001,
    NO_TRACKS,
    UNREADABLE,
    is_tracklist_page_url,
    resolve_tracklist_page,
)

URL_1001 = (
    "https://www.1001tracklists.com/tracklist/140z3slt/timmy-trumpet-one-world-radio-full-moon-083-2026-11-24.html"
)


def _recording(name: str) -> str:
    return (
        '<div id="tlp0_content" class="fontL" itemprop="tracks" itemscope itemtype="http://schema.org/MusicRecording"> '
        f'<meta itemprop="name" content="{name}"><meta itemprop="byArtist" content="x">'
        '<meta itemprop="publisher" content="&lt;span class=&quot;blueTxt&quot;&gt;LABEL&lt;/span&gt;">'
        '<meta itemprop="duration" content="PT5M3S"> <span class="trackValue notranslate">…</span></div>'
    )


PAGE_1001 = f"""<!DOCTYPE html><html><head>
<title>Timmy Trumpet - One World Radio Full Moon 083 2026-11-24</title>
<meta itemprop="name" content="Timmy Trumpet - One World Radio Full Moon 083 2026-11-24">
</head><body>
<div itemscope itemtype="http://schema.org/Organization"><meta itemprop="name" content="1001Tracklists"></div>
{_recording("FISHER &amp; LAUREL - Staring At The Sun")}
{_recording("Wuki - Nothing&#39;s Gonna Stop Us Now")}
{_recording("ID - ID")}
{_recording("Timmy Trumpet - ID")}
{_recording("HUGEL &amp; Imael Angel &amp; Ultra Naté - Movin' To The Sun")}
{_recording("FISHER &amp; LAUREL - Staring At The Sun")}
</body></html>"""

# What 1001Tracklists really serves (HTTP 206) when it wants a Turnstile check first.
CHALLENGE_1001 = """<html><head>
<title>1001Tracklists &sdot; The World's Leading DJ Tracklist/Playlist Database</title></head><body>
<form method="POST"><h1>Please wait, you will be forwarded to the requested page</h1>
<input type="hidden" name="captcha" value="1"><div id="turnstile-container" class="c"></div></form></body></html>"""

CLOUDFLARE_CHALLENGE = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"


def _resolve(page: str, url: str = URL_1001):
    return resolve_tracklist_page(url, fetch=lambda _url: page)


@pytest.mark.parametrize("url", [URL_1001, "1001tracklists.com/tracklist/2uz9wx21/gorillaz.html", f"  {URL_1001} "])
def test_is_tracklist_page_url_accepts_tracklist_pages(url: str) -> None:
    assert is_tracklist_page_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.1001tracklists.com/",
        "https://www.1001tracklists.com/dj/timmytrumpet/index.html",
        "https://www.mixesdb.com/w/2026-10-24_-_Miss_Monique_-_Essential_Mix",
        "https://evil1001tracklists.com/tracklist/140z3slt/x.html",
        "https://1001tracklists.com.evil.example/tracklist/140z3slt/x.html",
        "https://example.com/?next=https://www.1001tracklists.com/tracklist/140z3slt/x.html",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "https://example.com/tracklist/1001tracklists.com",
        "some artist - some title",
    ],
)
def test_is_tracklist_page_url_rejects_other_links(url: str) -> None:
    assert not is_tracklist_page_url(url)


def test_1001tracklists_reads_music_recording_names() -> None:
    tracklist = _resolve(PAGE_1001)

    assert tracklist.kind == "mix"
    assert tracklist.name == "Timmy Trumpet - One World Radio Full Moon 083 2026-11-24"
    assert tracklist.url == URL_1001
    assert [entry.query for entry in tracklist.entries] == [
        "FISHER & LAUREL - Staring At The Sun",
        "Wuki - Nothing's Gonna Stop Us Now",
        "HUGEL & Imael Angel & Ultra Naté - Movin' To The Sun",
    ]


@pytest.mark.parametrize("page", [CHALLENGE_1001, CLOUDFLARE_CHALLENGE])
def test_1001tracklists_challenge_page_is_reported_as_blocked(page: str) -> None:
    with pytest.raises(SourceError) as excinfo:
        _resolve(page)

    assert str(excinfo.value) == BLOCKED_1001


@pytest.mark.parametrize(
    ("page", "url"),
    [
        ("<html><head><title>Empty set</title></head><body></body></html>", URL_1001),
        (f"<html><body>{_recording('ID - ID')}</body></html>", URL_1001),
    ],
)
def test_page_without_identified_tracks_is_a_source_error(page: str, url: str) -> None:
    with pytest.raises(SourceError) as excinfo:
        _resolve(page, url)

    assert str(excinfo.value) == NO_TRACKS


def test_page_without_title_gets_a_default_name() -> None:
    assert _resolve(_recording("Artist - Song")).name == "Tracklist"


def _stub_httpx(monkeypatch: pytest.MonkeyPatch, status: int, text: str = "") -> dict:
    seen: dict = {}

    def fake_get(url: str, **kwargs) -> httpx.Response:
        seen.update(url=url, **kwargs)
        return httpx.Response(status, text=text, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    return seen


def test_default_fetch_sends_a_browser_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _stub_httpx(monkeypatch, 200, PAGE_1001)

    tracklist = resolve_tracklist_page(URL_1001)

    assert len(tracklist.entries) == 3
    assert seen["url"] == URL_1001
    assert seen["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert seen["follow_redirects"] is True
    assert seen["timeout"] == 20


@pytest.mark.parametrize(
    ("status", "url", "message"),
    [
        (403, URL_1001, BLOCKED_1001),
        (429, URL_1001, BLOCKED_1001),
        (404, URL_1001, UNREADABLE),
        (500, URL_1001, UNREADABLE),
    ],
)
def test_default_fetch_maps_http_errors(monkeypatch: pytest.MonkeyPatch, status: int, url: str, message: str) -> None:
    _stub_httpx(monkeypatch, status)

    with pytest.raises(SourceError) as excinfo:
        resolve_tracklist_page(url)

    assert str(excinfo.value) == message


def test_default_fetch_maps_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **_kwargs) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(SourceError) as excinfo:
        tracklist_pages.resolve_tracklist_page(URL_1001)

    assert str(excinfo.value) == UNREADABLE
