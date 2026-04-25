import argparse
import json
import logging
import os
import time

import requests
import requests_cache
import spotipy  # type: ignore
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError  # type: ignore
from tqdm import tqdm

GENRES_OUTPUT_FILE = "genres.json"
MUSIC_OUTPUT_FILE = "music.json"
LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
LASTFM_CACHE_NAME = "lastfm_cache"
LASTFM_CACHE_TTL_SECONDS = 86400
LOG_FILE = "log.log"
SPOTIFY_SCOPE = "playlist-read-private playlist-read-collaborative"
UNKNOWN_GENRE = "unknown"

SongRecord = dict[str, str]
GenreMetrics = dict[str, float | int]

logging.basicConfig(filename=LOG_FILE, level=logging.ERROR)

# Cache only Last.fm calls so repeated runs do not hammer the API.
lastfm_session = requests_cache.CachedSession(
    LASTFM_CACHE_NAME,
    expire_after=LASTFM_CACHE_TTL_SECONDS,
)

GLOBAL_LASTFM_ERROR_CODES = {
    2,  # Invalid service
    3,  # Invalid authentication method
    4,  # Authentication failed
    8,  # Operation failed
    10,  # Invalid API key
    11,  # Service offline
    16,  # Temporary error
    26,  # API key suspended
    29,  # Rate limit exceeded
}


def ms_to_time(ms: int) -> str:
    """Convert milliseconds to an MM:SS formatted string."""
    if ms < 0:
        raise ValueError("Track duration cannot be negative.")

    total_seconds = ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def authenticate() -> tuple[spotipy.Spotify, str]:
    """Return an authenticated Spotify client and the Last.fm API key."""
    load_dotenv()

    required_keys = (
        "SPOTIPY_CLIENT_ID",
        "SPOTIPY_CLIENT_SECRET",
        "SPOTIPY_REDIRECT_URI",
        "LASTFM_API_KEY",
    )

    try:
        client_id, client_secret, redirect_uri, lastfm_api = (
            os.environ[key] for key in required_keys
        )
    except KeyError as error:
        missing_key = error.args[0]
        raise ValueError(
            f"Missing {missing_key} environment variable. Check your .env file."
        ) from None

    spotify_client = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPE,
        )
    )
    return spotify_client, lastfm_api


def normalize_playlist_id(playlist_value: str) -> str:
    """Normalize raw CLI input to a Spotify playlist ID."""
    playlist_id = playlist_value.strip()

    if "/playlist/" in playlist_id:
        playlist_id = playlist_id.split("/playlist/", maxsplit=1)[1]

    if "?" in playlist_id:
        playlist_id = playlist_id.split("?", maxsplit=1)[0]

    return playlist_id.strip("/ ")


def build_song_record(track: dict) -> SongRecord | None:
    """Build a song record from a Spotify track object."""
    track_name = track.get("name")
    artists = track.get("artists")
    album = track.get("album")
    duration_ms = track.get("duration_ms")

    if not isinstance(track_name, str) or not isinstance(duration_ms, int):
        return None
    if duration_ms < 0:
        return None
    if not isinstance(artists, list) or not artists:
        return None
    if not isinstance(artists[0], dict) or not isinstance(album, dict):
        return None

    primary_artist = artists[0].get("name")
    album_name = album.get("name")
    if not isinstance(primary_artist, str) or not isinstance(album_name, str):
        return None

    return {
        "song": track_name,
        "artist": primary_artist,
        "album": album_name,
        "duration": ms_to_time(duration_ms),
    }


def fetch_tracks(
    sp: spotipy.Spotify, playlist: str
) -> tuple[list[SongRecord], set[str]]:
    """Fetch playlist tracks and return song records plus unique artist names."""
    songs: list[SongRecord] = []
    unique_artists: set[str] = set()
    results = sp.playlist_items(playlist)

    while True:
        for item in results.get("items", []):
            track = item.get("item")
            if not isinstance(track, dict) or track.get("type") != "track":
                continue

            song = build_song_record(track)
            if song is None:
                logging.error(
                    "Skipping malformed track data for playlist '%s': %s",
                    playlist,
                    track.get("name", "<unknown>"),
                )
                continue

            unique_artists.add(song["artist"])
            songs.append(song)

        if not results.get("next"):
            break
        results = sp.next(results)

    return songs, unique_artists


def fetch_genres(
    lastfm_api: str, unique_artists: set[str]
) -> tuple[dict[str, str], GenreMetrics]:
    """Look up a top Last.fm tag for each artist and return lookup metrics."""
    artists_genres: dict[str, str] = {}
    error_count = 0
    total_artists = len(unique_artists)

    if not unique_artists:
        return artists_genres, {
            "error_count": 0,
            "total": 0,
            "error_rate": 0,
        }

    print("Fetching genres via Last.fm API...")
    for artist in tqdm(sorted(unique_artists), desc="Artists Processed"):
        try:
            response = lastfm_session.get(
                LASTFM_API_URL,
                params={
                    "method": "artist.gettoptags",
                    "artist": artist,
                    "api_key": lastfm_api,
                    "format": "json",
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise json.JSONDecodeError(
                    "Last.fm returned a non-object response.",
                    str(data),
                    0,
                )

            if "error" in data:
                error_code = data.get("error")
                message = data.get("message", "Unknown Last.fm error")

                if error_code in GLOBAL_LASTFM_ERROR_CODES:
                    raise RuntimeError(f"Last.fm API error {error_code}: {message}")

                logging.error(
                    "Last.fm API error for %s: %s - %s",
                    artist,
                    error_code,
                    message,
                )
                artists_genres[artist] = UNKNOWN_GENRE
                print(f"Genre lookup failed for {artist}.")
                error_count += 1
                continue

            tags = data.get("toptags", {}).get("tag", [])
            if isinstance(tags, list) and tags and isinstance(tags[0], dict):
                tag_name = tags[0].get("name")
                if isinstance(tag_name, str) and tag_name:
                    artists_genres[artist] = tag_name
                else:
                    artists_genres[artist] = UNKNOWN_GENRE
                    error_count += 1
            else:
                artists_genres[artist] = UNKNOWN_GENRE
                error_count += 1

            if not getattr(response, "from_cache", False):
                time.sleep(1)

        except (requests.exceptions.RequestException, json.JSONDecodeError) as error:
            logging.error("Failed to get genre for %s: %s", artist, error)
            artists_genres[artist] = UNKNOWN_GENRE
            error_count += 1

    return artists_genres, {
        "error_count": error_count,
        "total": total_artists,
        "error_rate": error_count / total_artists,
    }


def save_output(songs: list[SongRecord], artists_genres: dict[str, str]) -> None:
    """Write playlist output files to disk."""
    with open(GENRES_OUTPUT_FILE, "w", encoding="utf-8") as genre_file:
        json.dump(artists_genres, genre_file, indent=4, ensure_ascii=False)

    with open(MUSIC_OUTPUT_FILE, "w", encoding="utf-8") as music_file:
        json.dump(songs, music_file, indent=4, ensure_ascii=False)


def main() -> None:
    """Export a Spotify playlist and enrich it with Last.fm genres."""
    parser = argparse.ArgumentParser(
        description="Export Spotify playlist tracks to JSON"
    )
    parser.add_argument("playlist_id", nargs="?", help="Spotify playlist ID or URL")
    args = parser.parse_args()

    try:
        sp, lastfm_api = authenticate()
    except (SpotifyOauthError, ValueError) as error:
        logging.error("Failed to authenticate Spotify authorization: %s", error)
        print("Error: Could not authenticate API data. Please check the .env file.")
        return

    raw_playlist_value = (
        args.playlist_id
        if args.playlist_id
        else input("Enter Spotify playlist ID or URL: ")
    )
    playlist_id = normalize_playlist_id(raw_playlist_value)
    if not playlist_id:
        print("Error: Playlist ID cannot be blank.")
        return

    try:
        songs, unique_artists = fetch_tracks(sp, playlist_id)
    except spotipy.exceptions.SpotifyException as error:
        logging.error("Failed to fetch tracks for %s: %s", playlist_id, error)
        print(
            "Error: Could not retrieve playlist. Verify the playlist ID and that your account has access to it."
        )
        return

    if not songs:
        print(
            "Playlist is empty or only contains unsupported items. Nothing to export."
        )
        return

    try:
        artists_genres, genre_metrics = fetch_genres(lastfm_api, unique_artists)
    except KeyboardInterrupt:
        print("Export cancelled.")
        return
    except RuntimeError as error:
        logging.error("Last.fm API failure: %s", error)
        print(f"Error: {error}")
        print("Genre lookup aborted. Please try again or check your Last.fm API key.")
        return

    print(
        f"{genre_metrics['error_rate'] * 100:.1f}% genre lookup failure rate "
        f"({genre_metrics['error_count']}/{genre_metrics['total']})"
    )

    for song in songs:
        song["genre"] = artists_genres.get(song["artist"], UNKNOWN_GENRE)

    try:
        save_output(songs, artists_genres)
    except OSError as error:
        logging.error("Failed to save output for %s: %s", playlist_id, error)
        print("Unable to save file.")
        return

    print(
        f"Export complete! Playlist data saved to {MUSIC_OUTPUT_FILE} and {GENRES_OUTPUT_FILE}."
    )


if __name__ == "__main__":
    main()
