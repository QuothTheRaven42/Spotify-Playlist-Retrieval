import pytest
from unittest.mock import Mock, patch
import json
import os
import requests
from main import ms_to_time, authenticate, fetch_genres, save_output


def test_ms_to_time_various_durations():
    """Test the ms_to_time function with various edge cases."""
    assert ms_to_time(0) == "00:00"
    assert ms_to_time(60000) == "01:00"
    assert ms_to_time(61000) == "01:01"
    assert ms_to_time(3599000) == "59:59"
    assert ms_to_time(3600000) == "60:00"
    assert ms_to_time(3661000) == "61:01"


@patch("main.load_dotenv")  # Stop it from reading your real .env file!
def test_authenticate_missing_env_var(mock_load_dotenv, monkeypatch):
    """Test that authenticate() raises error when environment variables are missing."""
    monkeypatch.delenv("SPOTIPY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIPY_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("SPOTIPY_REDIRECT_URI", raising=False)
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)

    with pytest.raises(EnvironmentError) as exc_info:
        authenticate()

    assert "SPOTIPY_CLIENT_ID" in str(exc_info.value)


@patch("main.lastfm_session.get")  # Changed to lastfm_session!
def test_fetch_genres_success(mock_get):
    """Test successful genre fetching with mocked API response."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "toptags": {"tag": [{"name": "thrash metal", "count": 100}, {"name": "metal", "count": 50}]}
    }
    mock_get.return_value = mock_response

    songs = [{"artist": "Metallica"}]
    unique_artists = {"Metallica", "Anthrax"}
    artists_genres = fetch_genres("fake_api_key", unique_artists, songs)

    assert artists_genres["Metallica"] == "thrash metal"
    assert artists_genres["Anthrax"] == "thrash metal"
    assert songs[0]["genre"] == "thrash metal"


@patch("main.lastfm_session.get")  # Changed to lastfm_session!
def test_fetch_genres_handles_missing_tags(mock_get):
    """Test that fetch_genres defaults to 'unknown' when no tags are found."""
    mock_response = Mock()
    mock_response.json.return_value = {"toptags": {"tag": []}}
    mock_get.return_value = mock_response

    songs = [{"artist": "Unknown Band"}]
    unique_artists = {"Unknown Band"}
    artists_genres = fetch_genres("fake_api_key", unique_artists, songs)

    assert artists_genres["Unknown Band"] == "unknown"
    assert songs[0]["genre"] == "unknown"


@patch("main.lastfm_session.get")  # Changed to lastfm_session!
def test_fetch_genres_handles_api_error(mock_get):
    """Test that fetch_genres logs errors and continues gracefully."""
    mock_get.side_effect = requests.exceptions.RequestException("Network error")

    songs = [{"artist": "Some Band"}]
    unique_artists = {"Some Band"}
    artists_genres = fetch_genres("fake_api_key", unique_artists, songs)

    assert "Some Band" in artists_genres
    assert artists_genres["Some Band"] == "unknown"


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
