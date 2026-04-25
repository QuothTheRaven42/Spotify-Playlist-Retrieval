import json
import os
import tempfile
from unittest.mock import MagicMock, Mock, call, mock_open, patch

import pytest
import requests

from main import (
    authenticate,
    fetch_genres,
    fetch_tracks,
    main,
    ms_to_time,
    normalize_playlist_id,
    save_output,
)


@pytest.fixture(autouse=True)
def disable_tqdm(monkeypatch):
    """Replace tqdm with a pass-through iterator for deterministic tests."""
    monkeypatch.setattr("main.tqdm", lambda iterable, **_: iterable)


@pytest.mark.parametrize(
    ("milliseconds", "expected"),
    [
        (0, "00:00"),
        (60000, "01:00"),
        (61000, "01:01"),
        (3599000, "59:59"),
        (3600000, "60:00"),
        (3661000, "61:01"),
    ],
)
def test_ms_to_time_formats_durations(milliseconds, expected):
    assert ms_to_time(milliseconds) == expected


def test_ms_to_time_rejects_negative_values():
    with pytest.raises(ValueError, match="cannot be negative"):
        ms_to_time(-1)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("2qOyhfKK44u2USaxUyqDVn", "2qOyhfKK44u2USaxUyqDVn"),
        (" 2qOyhfKK44u2USaxUyqDVn ", "2qOyhfKK44u2USaxUyqDVn"),
        (
            "https://open.spotify.com/playlist/2qOyhfKK44u2USaxUyqDVn?si=abc123",
            "2qOyhfKK44u2USaxUyqDVn",
        ),
        ("/playlist/2qOyhfKK44u2USaxUyqDVn/", "2qOyhfKK44u2USaxUyqDVn"),
    ],
)
def test_normalize_playlist_id_handles_ids_and_urls(raw_value, expected):
    assert normalize_playlist_id(raw_value) == expected


@patch("main.load_dotenv")
def test_authenticate_missing_env_var(_mock_load_dotenv, monkeypatch):
    monkeypatch.delenv("SPOTIPY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIPY_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("SPOTIPY_REDIRECT_URI", raising=False)
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)

    with pytest.raises(ValueError) as exc_info:
        authenticate()

    assert "SPOTIPY_CLIENT_ID" in str(exc_info.value)


@patch("main.load_dotenv")
@patch("main.spotipy.Spotify")
@patch("main.SpotifyOAuth")
def test_authenticate_returns_client_and_lastfm_key(
    mock_oauth,
    mock_spotify_client,
    _mock_load_dotenv,
    monkeypatch,
):
    monkeypatch.setenv("SPOTIPY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SPOTIPY_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    auth_manager = Mock()
    spotify_client = Mock()
    mock_oauth.return_value = auth_manager
    mock_spotify_client.return_value = spotify_client

    actual_client, lastfm_key = authenticate()

    assert actual_client is spotify_client
    assert lastfm_key == "lastfm-key"
    mock_oauth.assert_called_once_with(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://127.0.0.1:8888/callback",
        scope="playlist-read-private playlist-read-collaborative",
    )
    mock_spotify_client.assert_called_once_with(auth_manager=auth_manager)


def make_track_item(name="Song", artist="Artist", album="Album", duration_ms=200000):
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
    return {
        "item": {
            "type": "episode",
            "name": "Some Podcast",
            "duration_ms": 360000,
        }
    }


def make_results(items, has_next=False):
    return {"items": items, "next": "http://next-page" if has_next else None}


def test_fetch_tracks_normal_track():
    sp = MagicMock()
    sp.playlist_items.return_value = make_results([make_track_item()])

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == [
        {
            "song": "Song",
            "artist": "Artist",
            "album": "Album",
            "duration": "03:20",
        }
    ]
    assert artists == {"Artist"}


def test_fetch_tracks_skips_none_items():
    sp = MagicMock()
    sp.playlist_items.return_value = make_results([{"item": None}])

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == []
    assert artists == set()


def test_fetch_tracks_skips_episodes():
    sp = MagicMock()
    sp.playlist_items.return_value = make_results([make_episode_item()])

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == []
    assert artists == set()


def test_fetch_tracks_skips_malformed_track():
    sp = MagicMock()
    malformed_track = {
        "item": {
            "type": "track",
            "name": "Broken Song",
            "artists": [],
            "album": {"name": "Album"},
            "duration_ms": 123000,
        }
    }
    sp.playlist_items.return_value = make_results([malformed_track])

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == []
    assert artists == set()


def test_fetch_tracks_skips_negative_duration():
    sp = MagicMock()
    sp.playlist_items.return_value = make_results(
        [make_track_item(name="Impossible Song", duration_ms=-1)]
    )

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == []
    assert artists == set()


def test_fetch_tracks_mixed_playlist():
    sp = MagicMock()
    items = [
        make_track_item(name="Real Song", artist="Real Artist"),
        {"item": None},
        make_episode_item(),
    ]
    sp.playlist_items.return_value = make_results(items)

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == [
        {
            "song": "Real Song",
            "artist": "Real Artist",
            "album": "Album",
            "duration": "03:20",
        }
    ]
    assert artists == {"Real Artist"}


def test_fetch_tracks_pagination():
    sp = MagicMock()
    page_one = make_results([make_track_item(name="Song 1", artist="A")], has_next=True)
    page_two = make_results([make_track_item(name="Song 2", artist="B")])

    sp.playlist_items.return_value = page_one
    sp.next.return_value = page_two

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs[0]["song"] == "Song 1"
    assert songs[1]["song"] == "Song 2"
    assert artists == {"A", "B"}
    sp.next.assert_called_once_with(page_one)


def test_fetch_tracks_empty_playlist():
    sp = MagicMock()
    sp.playlist_items.return_value = make_results([])

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert songs == []
    assert artists == set()


def test_fetch_tracks_deduplicates_artists():
    sp = MagicMock()
    sp.playlist_items.return_value = make_results(
        [
            make_track_item(name="Song 1", artist="Same Artist"),
            make_track_item(name="Song 2", artist="Same Artist"),
            make_track_item(name="Song 3", artist="Different Artist"),
        ]
    )

    songs, artists = fetch_tracks(sp, "playlist_id")

    assert len(songs) == 3
    assert artists == {"Same Artist", "Different Artist"}


def make_lastfm_response(payload, *, from_cache=True):
    response = Mock()
    response.from_cache = from_cache
    response.raise_for_status = Mock()
    response.json.return_value = payload
    return response


@patch("main.lastfm_session.get")
def test_fetch_genres_success(mock_get):
    mock_get.return_value = make_lastfm_response(
        {
            "toptags": {
                "tag": [
                    {"name": "thrash metal", "count": 100},
                    {"name": "metal", "count": 50},
                ]
            }
        }
    )

    artist_genre, metrics = fetch_genres("fake_api_key", {"Metallica", "Anthrax"})

    assert artist_genre == {
        "Anthrax": "thrash metal",
        "Metallica": "thrash metal",
    }
    assert metrics == {"error_count": 0, "total": 2, "error_rate": 0}


@patch("main.lastfm_session.get")
def test_fetch_genres_handles_missing_tags(mock_get):
    mock_get.return_value = make_lastfm_response({"toptags": {"tag": []}})

    artist_genre, metrics = fetch_genres("fake_api_key", {"Unknown Band"})

    assert artist_genre["Unknown Band"] == "unknown"
    assert metrics == {"error_count": 1, "total": 1, "error_rate": 1.0}


@patch("main.lastfm_session.get")
def test_fetch_genres_handles_invalid_json_response(mock_get):
    response = make_lastfm_response({"unused": "value"})
    response.json.side_effect = json.JSONDecodeError("bad json", "doc", 0)
    mock_get.return_value = response

    artist_genre, metrics = fetch_genres("fake_api_key", {"Some Band"})

    assert artist_genre["Some Band"] == "unknown"
    assert metrics == {"error_count": 1, "total": 1, "error_rate": 1.0}


@patch("main.lastfm_session.get")
def test_fetch_genres_handles_non_object_json_payload(mock_get):
    response = make_lastfm_response({"unused": "value"})
    response.json.return_value = ["unexpected", "payload"]
    mock_get.return_value = response

    artist_genre, metrics = fetch_genres("fake_api_key", {"Some Band"})

    assert artist_genre["Some Band"] == "unknown"
    assert metrics == {"error_count": 1, "total": 1, "error_rate": 1.0}


@patch("main.lastfm_session.get")
def test_fetch_genres_handles_network_error(mock_get):
    mock_get.side_effect = requests.exceptions.RequestException("Network error")

    artist_genre, metrics = fetch_genres("fake_api_key", {"Some Band"})

    assert artist_genre["Some Band"] == "unknown"
    assert metrics == {"error_count": 1, "total": 1, "error_rate": 1.0}


@patch("main.lastfm_session.get")
def test_fetch_genres_global_api_error_aborts(mock_get):
    mock_get.return_value = make_lastfm_response(
        {"error": 10, "message": "Invalid API key"}
    )

    with pytest.raises(RuntimeError, match="Invalid API key"):
        fetch_genres("bad_api_key", {"Metallica"})


@patch("main.lastfm_session.get")
def test_fetch_genres_per_artist_error_continues(mock_get):
    mock_get.return_value = make_lastfm_response(
        {"error": 6, "message": "Artist not found"}
    )

    artist_genre, metrics = fetch_genres("fake_api_key", {"Nonexistent Band"})

    assert artist_genre["Nonexistent Band"] == "unknown"
    assert metrics == {"error_count": 1, "total": 1, "error_rate": 1.0}


@patch("main.lastfm_session.get")
def test_fetch_genres_rate_limit_error_aborts(mock_get):
    mock_get.return_value = make_lastfm_response(
        {"error": 29, "message": "Rate limit exceeded"}
    )

    with pytest.raises(RuntimeError, match="Rate limit exceeded"):
        fetch_genres("fake_api_key", {"Some Artist"})


@patch("main.time.sleep")
@patch("main.lastfm_session.get")
def test_fetch_genres_sleeps_only_for_uncached_requests(mock_get, mock_sleep):
    mock_get.return_value = make_lastfm_response(
        {"toptags": {"tag": [{"name": "metal"}]}},
        from_cache=False,
    )

    artist_genre, metrics = fetch_genres("fake_api_key", {"Metallica"})

    assert artist_genre["Metallica"] == "metal"
    assert metrics == {"error_count": 0, "total": 1, "error_rate": 0}
    mock_sleep.assert_called_once_with(1)


@patch("main.lastfm_session.get")
def test_fetch_genres_handles_empty_artist_set(mock_get):
    artist_genre, metrics = fetch_genres("fake_api_key", set())

    assert artist_genre == {}
    assert metrics == {"error_count": 0, "total": 0, "error_rate": 0}
    mock_get.assert_not_called()


def test_save_output_creates_files():
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

    with (
        patch("builtins.open", mock_open()) as mocked_open,
        patch("main.json.dump") as mock_dump,
    ):
        save_output(songs, genres)

    assert mocked_open.call_args_list == [
        call("genres.json", "w", encoding="utf-8"),
        call("music.json", "w", encoding="utf-8"),
    ]
    assert mock_dump.call_args_list[0].args[0] == genres
    assert mock_dump.call_args_list[0].kwargs == {"indent": 4, "ensure_ascii": False}
    assert mock_dump.call_args_list[1].args[0] == songs
    assert mock_dump.call_args_list[1].kwargs == {"indent": 4, "ensure_ascii": False}


def test_save_output_writes_real_json_files(monkeypatch):
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

    music_fd, music_path = tempfile.mkstemp(dir=".", suffix=".json")
    genres_fd, genres_path = tempfile.mkstemp(dir=".", suffix=".json")
    os.close(music_fd)
    os.close(genres_fd)

    try:
        monkeypatch.setattr("main.MUSIC_OUTPUT_FILE", music_path)
        monkeypatch.setattr("main.GENRES_OUTPUT_FILE", genres_path)

        save_output(songs, genres)

        with open(music_path, encoding="utf-8") as music_file:
            saved_songs = json.load(music_file)
        with open(genres_path, encoding="utf-8") as genres_file:
            saved_genres = json.load(genres_file)

        assert saved_songs == songs
        assert saved_genres == genres
    finally:
        os.remove(music_path)
        os.remove(genres_path)


def test_main_normalizes_playlist_url_and_saves_output(capsys):
    with (
        patch(
            "main.argparse.ArgumentParser.parse_args",
            return_value=Mock(
                playlist_id="https://open.spotify.com/playlist/test_playlist?si=123"
            ),
        ),
        patch("main.authenticate", return_value=(MagicMock(), "fake_api_key")),
        patch(
            "main.fetch_tracks",
            return_value=(
                [
                    {
                        "song": "Song",
                        "artist": "Artist",
                        "album": "Album",
                        "duration": "03:20",
                    }
                ],
                {"Artist"},
            ),
        ) as mock_fetch_tracks,
        patch(
            "main.fetch_genres",
            return_value=(
                {"Artist": "metal"},
                {"error_count": 0, "total": 1, "error_rate": 0},
            ),
        ),
        patch("main.save_output"),
    ):
        main()

    captured = capsys.readouterr()
    assert "Export complete!" in captured.out
    mock_fetch_tracks.assert_called_once()
    assert mock_fetch_tracks.call_args.args[1] == "test_playlist"


def test_main_integration_writes_expected_files(monkeypatch, capsys):
    class FakeSpotifyClient:
        def __init__(self):
            self.requested_playlist = None
            self._page_one = {
                "items": [
                    {
                        "item": {
                            "type": "track",
                            "name": "Song 1",
                            "artists": [{"name": "Artist One"}],
                            "album": {"name": "Album 1"},
                            "duration_ms": 200000,
                        }
                    },
                    {"item": None},
                ],
                "next": "http://next-page",
            }
            self._page_two = {
                "items": [
                    {
                        "item": {
                            "type": "episode",
                            "name": "Podcast Episode",
                            "duration_ms": 360000,
                        }
                    },
                    {
                        "item": {
                            "type": "track",
                            "name": "Broken Song",
                            "artists": [],
                            "album": {"name": "Album 2"},
                            "duration_ms": 100000,
                        }
                    },
                    {
                        "item": {
                            "type": "track",
                            "name": "Song 2",
                            "artists": [{"name": "Artist Two"}],
                            "album": {"name": "Album 2"},
                            "duration_ms": 180000,
                        }
                    },
                ],
                "next": None,
            }

        def playlist_items(self, playlist):
            self.requested_playlist = playlist
            return self._page_one

        def next(self, results):
            assert results is self._page_one
            return self._page_two

    fake_spotify = FakeSpotifyClient()
    genre_responses = [
        make_lastfm_response({"toptags": {"tag": [{"name": "metal"}]}}),
        make_lastfm_response({"toptags": {"tag": [{"name": "rock"}]}}),
    ]

    music_fd, music_path = tempfile.mkstemp(dir=".", suffix=".json")
    genres_fd, genres_path = tempfile.mkstemp(dir=".", suffix=".json")
    os.close(music_fd)
    os.close(genres_fd)

    try:
        monkeypatch.setattr("main.MUSIC_OUTPUT_FILE", music_path)
        monkeypatch.setattr("main.GENRES_OUTPUT_FILE", genres_path)

        with (
            patch(
                "main.argparse.ArgumentParser.parse_args",
                return_value=Mock(
                    playlist_id="https://open.spotify.com/playlist/test_playlist?si=123"
                ),
            ),
            patch("main.authenticate", return_value=(fake_spotify, "fake_api_key")),
            patch("main.lastfm_session.get", side_effect=genre_responses),
        ):
            main()

        with open(music_path, encoding="utf-8") as music_file:
            music_data = json.load(music_file)
        with open(genres_path, encoding="utf-8") as genres_file:
            genres_data = json.load(genres_file)

        captured = capsys.readouterr()
        assert fake_spotify.requested_playlist == "test_playlist"
        assert "0.0% genre lookup failure rate (0/2)" in captured.out
        assert "Export complete!" in captured.out
        assert music_data == [
            {
                "song": "Song 1",
                "artist": "Artist One",
                "album": "Album 1",
                "duration": "03:20",
                "genre": "metal",
            },
            {
                "song": "Song 2",
                "artist": "Artist Two",
                "album": "Album 2",
                "duration": "03:00",
                "genre": "rock",
            },
        ]
        assert genres_data == {
            "Artist One": "metal",
            "Artist Two": "rock",
        }
    finally:
        os.remove(music_path)
        os.remove(genres_path)


def test_main_handles_lastfm_global_error(capsys):
    with (
        patch(
            "main.argparse.ArgumentParser.parse_args",
            return_value=Mock(playlist_id="test_playlist"),
        ),
        patch("main.authenticate", return_value=(MagicMock(), "fake_api_key")),
        patch(
            "main.fetch_tracks",
            return_value=(
                [
                    {
                        "song": "Song",
                        "artist": "Artist",
                        "album": "Album",
                        "duration": "03:20",
                    }
                ],
                {"Artist"},
            ),
        ),
        patch(
            "main.fetch_genres",
            side_effect=RuntimeError("Last.fm API error 29: Rate limit exceeded"),
        ),
    ):
        main()

    captured = capsys.readouterr()
    assert "Rate limit exceeded" in captured.out
    assert "Export complete!" not in captured.out


def test_main_handles_authentication_failure(capsys):
    with (
        patch(
            "main.argparse.ArgumentParser.parse_args",
            return_value=Mock(playlist_id="playlist_id"),
        ),
        patch("main.authenticate", side_effect=ValueError("Missing LASTFM_API_KEY")),
    ):
        main()

    captured = capsys.readouterr()
    assert "Could not authenticate API data" in captured.out


def test_main_rejects_blank_playlist_id(capsys):
    with (
        patch(
            "main.argparse.ArgumentParser.parse_args",
            return_value=Mock(playlist_id="   "),
        ),
        patch("main.authenticate", return_value=(MagicMock(), "fake_api_key")),
    ):
        main()

    captured = capsys.readouterr()
    assert "Playlist ID cannot be blank" in captured.out


def test_main_reports_empty_playlist(capsys):
    with (
        patch(
            "main.argparse.ArgumentParser.parse_args",
            return_value=Mock(playlist_id="playlist_id"),
        ),
        patch("main.authenticate", return_value=(MagicMock(), "fake_api_key")),
        patch("main.fetch_tracks", return_value=([], set())),
    ):
        main()

    captured = capsys.readouterr()
    assert "Playlist is empty or only contains unsupported items" in captured.out


def test_main_handles_save_output_error(capsys):
    with (
        patch(
            "main.argparse.ArgumentParser.parse_args",
            return_value=Mock(playlist_id="playlist_id"),
        ),
        patch("main.authenticate", return_value=(MagicMock(), "fake_api_key")),
        patch(
            "main.fetch_tracks",
            return_value=(
                [
                    {
                        "song": "Song",
                        "artist": "Artist",
                        "album": "Album",
                        "duration": "03:20",
                    }
                ],
                {"Artist"},
            ),
        ),
        patch(
            "main.fetch_genres",
            return_value=(
                {"Artist": "metal"},
                {"error_count": 0, "total": 1, "error_rate": 0},
            ),
        ),
        patch("main.save_output", side_effect=OSError("disk full")),
    ):
        main()

    captured = capsys.readouterr()
    assert "Unable to save file." in captured.out
