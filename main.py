import argparse
import json
import logging
import os
import time
import tkinter as tk
from tkinter import filedialog

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
SPOTIFY_SCOPE = (
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-private playlist-modify-public"
)
UNKNOWN_GENRE = "unknown"
SPOTIFY_ADD_TRACKS_BATCH_SIZE = 100

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


def _build_spotify_client() -> spotipy.Spotify:
    """Build an authenticated Spotify client from environment variables."""
    load_dotenv()

    required_keys = ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI")
    try:
        client_id, client_secret, redirect_uri = (os.environ[key] for key in required_keys)
    except KeyError as error:
        missing_key = error.args[0]
        raise ValueError(
            f"Missing {missing_key} environment variable. Check your .env file."
        ) from None

    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPE,
        )
    )


def authenticate() -> tuple[spotipy.Spotify, str]:
    """Return an authenticated Spotify client and the Last.fm API key."""
    sp = _build_spotify_client()

    try:
        lastfm_api = os.environ["LASTFM_API_KEY"]
    except KeyError:
        raise ValueError(
            "Missing LASTFM_API_KEY environment variable. Check your .env file."
        ) from None

    return sp, lastfm_api


def authenticate_for_import() -> spotipy.Spotify:
    """Return an authenticated Spotify client (import mode; no Last.fm key needed)."""
    return _build_spotify_client()


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

    record: SongRecord = {
        "song": track_name,
        "artist": primary_artist,
        "album": album_name,
        "duration": ms_to_time(duration_ms),
    }

    uri = track.get("uri")
    if isinstance(uri, str) and uri:
        record["uri"] = uri

    return record


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


def search_track_uri(sp: spotipy.Spotify, song: str, artist: str) -> str | None:
    """Search Spotify for a track by name and artist, returning its URI or None."""
    results = sp.search(q=f"track:{song} artist:{artist}", type="track", limit=1)
    tracks = results.get("tracks", {}).get("items", [])
    if tracks and isinstance(tracks[0], dict):
        return tracks[0].get("uri")
    return None


def _collect_track_uris(
    sp: spotipy.Spotify, songs: list[SongRecord]
) -> tuple[list[str], int]:
    """Search Spotify for each song record and return (uris, not_found_count)."""
    uris: list[str] = []
    not_found = 0

    print(f"Searching for {len(songs)} tracks on Spotify...")
    for song in tqdm(songs, desc="Tracks Searched"):
        if not isinstance(song, dict):
            not_found += 1
            continue
        existing_uri = song.get("uri", "")
        if isinstance(existing_uri, str) and existing_uri:
            uris.append(existing_uri)
            continue
        name = song.get("song", "")
        artist = song.get("artist", "")
        if not name or not artist:
            not_found += 1
            continue
        uri = search_track_uri(sp, name, artist)
        if uri:
            uris.append(uri)
        else:
            logging.warning("Track not found on Spotify: %s by %s", name, artist)
            not_found += 1

    return uris, not_found


def _push_uris_to_playlist(
    sp: spotipy.Spotify, playlist_id: str, uris: list[str]
) -> None:
    """Add URIs to a playlist in batches."""
    for i in range(0, len(uris), SPOTIFY_ADD_TRACKS_BATCH_SIZE):
        sp.playlist_add_items(playlist_id, uris[i : i + SPOTIFY_ADD_TRACKS_BATCH_SIZE])


def create_playlist_from_json(
    sp: spotipy.Spotify, songs: list[SongRecord], playlist_name: str
) -> dict[str, int]:
    """Create a new private Spotify playlist from a list of song records."""
    playlist = sp.current_user_playlist_create(playlist_name, public=False)
    uris, not_found = _collect_track_uris(sp, songs)
    _push_uris_to_playlist(sp, playlist["id"], uris)
    return {"found": len(uris), "not_found": not_found}


def add_tracks_to_existing_playlist(
    sp: spotipy.Spotify, songs: list[SongRecord], playlist_id: str
) -> dict[str, int]:
    """Add songs from a JSON list to an existing Spotify playlist."""
    uris, not_found = _collect_track_uris(sp, songs)
    _push_uris_to_playlist(sp, playlist_id, uris)
    return {"found": len(uris), "not_found": not_found}


def _run_export(args) -> bool:
    """Handle the export subcommand."""
    try:
        sp, lastfm_api = authenticate()
    except (SpotifyOauthError, ValueError) as error:
        logging.error("Failed to authenticate Spotify authorization: %s", error)
        print("Error: Could not authenticate API data. Please check the .env file.")
        return True

    raw_playlist_value = getattr(args, "playlist_id", None)
    if not raw_playlist_value:
        raw_playlist_value = input("Enter Spotify playlist ID or URL: ")

    playlist_id = normalize_playlist_id(raw_playlist_value)
    if not playlist_id:
        print("Error: Playlist ID cannot be blank.")
        return True

    try:
        songs, unique_artists = fetch_tracks(sp, playlist_id)
    except spotipy.exceptions.SpotifyException as error:
        logging.error("Failed to fetch tracks for %s: %s", playlist_id, error)
        print(
            "Error: Could not retrieve playlist. Verify the playlist ID and that your account has access to it."
        )
        return True

    if not songs:
        print(
            "Playlist is empty or only contains unsupported items. Nothing to export."
        )
        return True

    try:
        artists_genres, genre_metrics = fetch_genres(lastfm_api, unique_artists)
    except KeyboardInterrupt:
        print("Export cancelled.")
        return True
    except RuntimeError as error:
        logging.error("Last.fm API failure: %s", error)
        print(f"Error: {error}")
        print("Genre lookup aborted. Please try again or check your Last.fm API key.")
        return True

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
        return True

    print(
        f"Export complete! Playlist data saved to {MUSIC_OUTPUT_FILE} and {GENRES_OUTPUT_FILE}."
    )
    return True


def _run_import(args) -> bool:
    """Handle the import subcommand."""
    try:
        sp = authenticate_for_import()
    except (SpotifyOauthError, ValueError) as error:
        logging.error("Failed to authenticate: %s", error)
        print("Error: Could not authenticate. Please check the .env file.")
        return True

    json_path = getattr(args, "json_file", None)
    if not json_path:
        root = tk.Tk()
        root.withdraw()
        json_path = filedialog.askopenfilename(
            title="Select music.json file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        root.destroy()
    if not json_path:
        print("Error: No file selected.\n")
        return False

    try:
        with open(json_path, encoding="utf-8") as f:
            songs = json.load(f)
    except FileNotFoundError:
        print(f"Error: File '{json_path}' not found.")
        return True
    except (json.JSONDecodeError, OSError) as error:
        print(f"Error reading JSON file: {error}")
        return True

    if not isinstance(songs, list) or not songs:
        print("Error: JSON file must contain a non-empty list of songs.")
        return True

    playlist_name = getattr(args, "playlist_name", None)
    if not playlist_name:
        playlist_name = input("Enter playlist name: ").strip()
    if not playlist_name:
        print("Error: Playlist name cannot be blank.")
        return

    try:
        stats = create_playlist_from_json(sp, songs, playlist_name)
    except spotipy.exceptions.SpotifyException as error:
        logging.error("Failed to create playlist '%s': %s", playlist_name, error)
        print(f"Error: Could not create playlist. Spotify said: {error}")
        return True

    print(
        f"Done! Playlist '{playlist_name}' created with {stats['found']} tracks "
        f"({stats['not_found']} not found on Spotify)."
    )
    return True


def _run_add(args) -> bool:
    """Handle the add subcommand — append songs from JSON to an existing playlist."""
    try:
        sp = authenticate_for_import()
    except (SpotifyOauthError, ValueError) as error:
        logging.error("Failed to authenticate: %s", error)
        print("Error: Could not authenticate. Please check the .env file.")
        return True

    json_path = getattr(args, "json_file", None)
    if not json_path:
        root = tk.Tk()
        root.withdraw()
        json_path = filedialog.askopenfilename(
            title="Select music.json file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        root.destroy()
    if not json_path:
        print("Error: No file selected.")
        return False

    try:
        with open(json_path, encoding="utf-8") as f:
            songs = json.load(f)
    except FileNotFoundError:
        print(f"Error: File '{json_path}' not found.")
        return True
    except (json.JSONDecodeError, OSError) as error:
        print(f"Error reading JSON file: {error}")
        return True

    if not isinstance(songs, list) or not songs:
        print("Error: JSON file must contain a non-empty list of songs.")
        return True

    raw_playlist_value = getattr(args, "playlist_id", None)
    if not raw_playlist_value:
        raw_playlist_value = input("Enter Spotify playlist ID or URL: ").strip()
    playlist_id = normalize_playlist_id(raw_playlist_value)
    if not playlist_id:
        print("Error: Playlist ID cannot be blank.")
        return True

    try:
        stats = add_tracks_to_existing_playlist(sp, songs, playlist_id)
    except spotipy.exceptions.SpotifyException as error:
        logging.error("Failed to add tracks to playlist '%s': %s", playlist_id, error)
        print(f"Error: Could not add tracks to playlist. Spotify said: {error}")
        return True

    print(
        f"Done! Added {stats['found']} tracks to the playlist "
        f"({stats['not_found']} not found on Spotify)."
    )
    return True


def _run_interactive_menu() -> None:
    """Display the main menu until the user exits or completes an action."""
    while True:
        print("What would you like to do?")
        print("  1) Export a Spotify playlist to JSON")
        print("  2) Create a new Spotify playlist from a JSON file")
        print("  3) Add songs from a JSON file to an existing playlist")
        print("  4) Exit")
        choice = input("Enter 1, 2, 3, or 4: ").strip()

        match choice:
            case "1":
                if _run_export(argparse.Namespace(playlist_id=None)):
                    return
            case "2":
                if _run_import(argparse.Namespace(json_file=None, playlist_name=None)):
                    return
            case "3":
                if _run_add(argparse.Namespace(json_file=None, playlist_id=None)):
                    return
            case "4":
                return
            case _:
                print("Invalid choice.")


def main() -> None:
    """Spotify playlist tools: export a playlist to JSON, or create one from JSON."""
    parser = argparse.ArgumentParser(description="Spotify playlist tools")
    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser(
        "export", help="Export a Spotify playlist to JSON"
    )
    export_parser.add_argument(
        "playlist_id", nargs="?", help="Spotify playlist ID or URL"
    )

    import_parser = subparsers.add_parser(
        "import", help="Create a new Spotify playlist from a music.json file"
    )
    import_parser.add_argument(
        "json_file", nargs="?", help="Path to music.json file"
    )
    import_parser.add_argument(
        "playlist_name", nargs="?", help="Name for the new playlist"
    )

    add_parser = subparsers.add_parser(
        "add", help="Add songs from a music.json file to an existing playlist"
    )
    add_parser.add_argument(
        "json_file", nargs="?", help="Path to music.json file"
    )
    add_parser.add_argument(
        "playlist_id", nargs="?", help="Spotify playlist ID or URL"
    )

    args = parser.parse_args()

    command = getattr(args, "command", None)

    if command is None:
        _run_interactive_menu()
        return

    match command:
        case "import":
            _run_import(args)
        case "add":
            _run_add(args)
        case _:
            _run_export(args)


if __name__ == "__main__":
    main()
