import pytest
from unittest.mock import Mock, MagicMock, patch
import json
import os
import requests
from main import (
    ms_to_time,
    authenticate,
    fetch_tracks,
    fetch_genres,
    save_output,
    main,
)

# ──────────────────────────────────────────────────────────────────────
# ms_to_time tests
# ──────────────────────────────────────────────────────────────────────


def test_ms_to_time_various_durations():
    """Test the ms_to_time function with various edge cases."""
    assert ms_to_time(0) == "00:00"
    assert ms_to_time(60000) == "01:00"
    assert ms_to_time(61000) == "01:01"
    assert ms_to_time(3599000) == "59:59"
    assert ms_to_time(3600000) == "60:00"
    assert ms_to_time(3661000) == "61:01"


# ──────────────────────────────────────────────────────────────────────
# authenticate tests
# ──────────────────────────────────────────────────────────────────────


@patch("main.load_dotenv")  # Stop it from reading your real .env file!
def test_authenticate_missing_env_var(mock_load_dotenv, monkeypatch):
    """Test that authenticate() raises error when environment variables are missing."""
    monkeypatch.delenv("SPOTIPY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIPY_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("SPOTIPY_REDIRECT_URI", raising=False)
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)

    monkeypatch.setattr("main.load_dotenv", lambda: None)
    with pytest.raises(ValueError) as exc_info:
        authenticate()

    assert "SPOTIPY_CLIENT_ID" in str(exc_info.value)


def make_track_item(name="Song", artist="Artist", album="Album", duration_ms=200000):
    """Helper: build a minimal Spotify track item dict.

    Mirrors the shape returned by sp.playlist_items()["items"][n]
    for a standard track. Only includes fields that fetch_tracks()
    actually reads, keeping the test fixtures small and intention-clear.
    """
    return {
        "item": {
            "type": "track",
            "name": name,
            "artists": [{"name": artist}],
            "album": {"name": album},
            "duration_ms": duration_ms,
        }
    }


def make_episode_item():
    """Helper: build a minimal Spotify episode item dict.

    Episode objects do NOT have "artists" or "album" keys — that's the
    exact shape difference that causes the crash this test guards against.
    """
    return {
        "item": {
            "type": "episode",
            "name": "Some Podcast",
            "duration_ms": 360000,
        }
    }


def make_results(items, has_next=False):
    """Helper: wrap items in the paginated response structure Spotify uses.

    Spotify's playlist_items endpoint returns a paging object with an
    "items" list and a "next" URL (or None on the last page). This
    helper lets us simulate single-page and multi-page responses.
    """
    return {"items": items, "next": "http://next-page" if has_next else None}


def test_fetch_tracks_normal_track():
    """A standard track item should be extracted with correct fields."""
    sp = MagicMock()
    sp.playlist_items.return_value = make_results([make_track_item()])

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert len(songs) == 1
    assert songs[0]["song"] == "Song"
    assert songs[0]["artist"] == "Artist"
    assert songs[0]["album"] == "Album"
    assert songs[0]["duration"] == "03:20"  # 200000ms = 3 min 20 sec
    assert "Artist" in artists


def test_fetch_tracks_skips_none():
    """Null items (locally added or unavailable tracks) should be silently skipped.

    Spotify can return null entries for tracks that were added from local
    files or that have been removed from the catalogue. fetch_tracks()
    must not crash on these.
    """
    sp = MagicMock()
    sp.playlist_items.return_value = make_results([{"item": None}])

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == []
    assert artists == set()


def test_fetch_tracks_skips_episodes():
    """Podcast episodes in a playlist should be skipped, not crash the export.

    This is the core regression test for the mixed-content playlist bug.
    Spotify's API returns item as TrackObject | EpisodeObject. Episode
    objects lack "artists" and "album", so accessing those keys without
    a type check raises KeyError/TypeError. The fix is:
        if track.get("type") != "track": continue
    """
    sp = MagicMock()
    sp.playlist_items.return_value = make_results([make_episode_item()])

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == []
    assert artists == set()


def test_fetch_tracks_mixed_playlist():
    """A playlist with tracks, episodes, and null items should only export tracks.

    This simulates a real-world "mixed content" playlist — the most
    common scenario where the original bug would have surfaced. We
    verify that:
      - The valid track is included
      - The null item is skipped
      - The episode is skipped
      - No crash occurs
    """
    sp = MagicMock()
    items = [
        make_track_item(name="Real Song", artist="Real Artist"),
        {"item": None},
        make_episode_item(),
    ]
    sp.playlist_items.return_value = make_results(items)

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert len(songs) == 1
    assert songs[0]["song"] == "Real Song"
    assert artists == {"Real Artist"}


def test_fetch_tracks_pagination():
    """fetch_tracks() must follow Spotify's pagination to collect all tracks.

    Spotify returns a maximum of 50 items per request. When more items
    exist, results["next"] contains the URL for the next page. We
    simulate a two-page response and verify both pages' tracks appear
    in the output.
    """
    sp = MagicMock()
    page1 = make_results([make_track_item(name="Song 1", artist="A")], has_next=True)
    page2 = make_results([make_track_item(name="Song 2", artist="B")], has_next=False)

    sp.playlist_items.return_value = page1
    sp.next.return_value = page2

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert len(songs) == 2
    assert songs[0]["song"] == "Song 1"
    assert songs[1]["song"] == "Song 2"
    assert artists == {"A", "B"}
    # Verify sp.next was called exactly once (for the second page)
    sp.next.assert_called_once_with(page1)


def test_fetch_tracks_empty_playlist():
    """An empty but valid playlist should return empty results without error.

    This is distinct from a failed fetch — main() checks for empty
    results and prints "Playlist is empty" rather than writing empty files.
    """
    sp = MagicMock()
    sp.playlist_items.return_value = make_results([])

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == []
    assert artists == set()


def test_fetch_tracks_deduplicates_artists():
    """Multiple tracks by the same artist should produce only one entry in unique_artists.

    This matters because unique_artists drives the Last.fm genre lookup —
    duplicate entries would cause redundant API calls.
    """
    sp = MagicMock()
    items = [
        make_track_item(name="Song 1", artist="Same Artist"),
        make_track_item(name="Song 2", artist="Same Artist"),
        make_track_item(name="Song 3", artist="Different Artist"),
    ]
    sp.playlist_items.return_value = make_results(items)

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert len(songs) == 3
    assert artists == {"Same Artist", "Different Artist"}


# ──────────────────────────────────────────────────────────────────────
# fetch_genres tests
# ──────────────────────────────────────────────────────────────────────


@patch("main.lastfm_session.get")
def test_fetch_genres_success(mock_get):
    """Test successful genre fetching with mocked API response."""
    mock_response = Mock()
    mock_response.from_cache = True
    mock_response.json.return_value = {
        "toptags": {"tag": [{"name": "thrash metal", "count": 100}, {"name": "metal", "count": 50}]}
    }
    mock_get.return_value = mock_response

    songs = [{"artist": "Metallica"}]
    unique_artists = {"Metallica", "Anthrax"}
    artists_genres = fetch_genres("fake_api_key", unique_artists)

    assert artists_genres["Metallica"] == "thrash metal"
    assert artists_genres["Anthrax"] == "thrash metal"


@patch("main.lastfm_session.get")
def test_fetch_genres_handles_missing_tags(mock_get):
    """Test that fetch_genres defaults to 'unknown' when no tags are found."""
    mock_response = Mock()
    mock_response.from_cache = True
    mock_response.json.return_value = {"toptags": {"tag": []}}
    mock_get.return_value = mock_response

    songs = [{"artist": "Unknown Band"}]
    unique_artists = {"Unknown Band"}
    artists_genres = fetch_genres("fake_api_key", unique_artists)

    assert artists_genres["Unknown Band"] == "unknown"


@patch("main.lastfm_session.get")
def test_fetch_genres_handles_api_error(mock_get):
    """Test that fetch_genres logs errors and continues gracefully."""
    mock_get.side_effect = requests.exceptions.RequestException("Network error")

    songs = [{"artist": "Some Band"}]
    unique_artists = {"Some Band"}
    artists_genres = fetch_genres("fake_api_key", unique_artists)

    assert "Some Band" in artists_genres
    assert artists_genres["Some Band"] == "unknown"


@patch("main.lastfm_session.get")
def test_fetch_genres_global_api_error_aborts(mock_get):
    """A global Last.fm API error (e.g., invalid key) should raise RuntimeError.

    Last.fm returns HTTP 200 with an error payload for issues like invalid
    API keys or rate limiting. These errors affect ALL requests, so continuing
    would just repeat the same failure for every artist. fetch_genres() should
    raise RuntimeError so main() can report the issue and stop.

    See: https://www.last.fm/api/errorcodes
    """
    mock_response = Mock()
    mock_response.from_cache = True
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "error": 10,
        "message": "Invalid API key",
    }
    mock_get.return_value = mock_response

    with pytest.raises(RuntimeError, match="Invalid API key"):
        fetch_genres("bad_api_key", {"Metallica"})


@patch("main.lastfm_session.get")
def test_fetch_genres_per_artist_error_continues(mock_get):
    """A per-artist Last.fm error should log and default to 'unknown', not abort.

    Error code 6 ("Artist not found") only affects a single lookup.
    The function should mark that artist as 'unknown' and continue
    processing the remaining artists.
    """
    mock_response = Mock()
    mock_response.from_cache = True
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "error": 6,
        "message": "Artist not found",
    }
    mock_get.return_value = mock_response

    artists_genres = fetch_genres("fake_api_key", {"Nonexistent Band"})

    assert artists_genres["Nonexistent Band"] == "unknown"


@patch("main.lastfm_session.get")
def test_fetch_genres_rate_limit_error_aborts(mock_get):
    """Rate limiting (error 29) is a global failure and should abort.

    Last.fm rate-limit lockouts can last over an hour. Continuing would
    just produce 'unknown' for every remaining artist while hammering
    an API that's already rejecting us.
    """
    mock_response = Mock()
    mock_response.from_cache = True
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "error": 29,
        "message": "Rate limit exceeded",
    }
    mock_get.return_value = mock_response

    with pytest.raises(RuntimeError, match="Rate limit exceeded"):
        fetch_genres("fake_api_key", {"Some Artist"})


# ──────────────────────────────────────────────────────────────────────
# save_output tests
# ──────────────────────────────────────────────────────────────────────


def test_save_output_creates_files(tmp_path):
    """Test that save_output creates both JSON files correctly."""
    songs = [
        {
            "song": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "duration": "03:45",
            "genre": "test genre",
        }
    ]
    genres = {"Test Artist": "test genre"}

    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        save_output(songs, genres)

        assert (tmp_path / "music.json").exists()
        music_data = json.loads((tmp_path / "music.json").read_text())
        assert len(music_data) == 1
        assert music_data[0]["song"] == "Test Song"

        assert (tmp_path / "genres.json").exists()
        genre_data = json.loads((tmp_path / "genres.json").read_text())
        assert genre_data["Test Artist"] == "test genre"
    finally:
        os.chdir(old_cwd)


@patch("main.fetch_genres", side_effect=RuntimeError("Last.fm API error 29: Rate limit exceeded"))
@patch("main.fetch_tracks")
@patch("main.authenticate")
@patch("main.argparse.ArgumentParser.parse_args")
def test_main_handles_lastfm_global_error(mock_args, mock_auth, mock_fetch, mock_genres, capsys):
    """main() should catch RuntimeError from fetch_genres and exit cleanly.

    When Last.fm returns a global failure like rate limiting or an invalid
    API key, fetch_genres() raises RuntimeError. main() should catch it,
    print a user-facing message, and return — not crash with a traceback
    or print "Export complete!".

    The decorators are ordered bottom-up: the last @patch is the first
    parameter after self/capsys. We patch at the main module level
    because that's where main() imports and calls these functions.
    """
    mock_args.return_value = Mock(playlist_id="test_playlist")
    mock_auth.return_value = (MagicMock(), "fake_api_key")
    mock_fetch.return_value = (
        [{"song": "Song", "artist": "Artist", "album": "Album", "duration": "03:20"}],
        {"Artist"},
    )

    main()

    captured = capsys.readouterr()
    assert "Rate limit exceeded" in captured.out
    assert "Export complete!" not in captured.out
