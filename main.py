import spotipy  # type: ignore
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError  # type: ignore
from dotenv import load_dotenv
import argparse
import os
import json
import requests  # type: ignore[import-untyped]
import time
from tqdm import tqdm  # type: ignore[import-untyped]
import requests_cache
import logging

logging.basicConfig(filename="log.log", level=logging.ERROR)

# CachedSession scopes the cache to this session rather than patching requests globally,
# which prevents side effects in other parts of the program or test suite
lastfm_session = requests_cache.CachedSession("lastfm_cache", expire_after=86400)


def ms_to_time(ms: int) -> str:
    """Convert milliseconds to an MM:SS formatted string."""
    total_seconds = ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def authenticate() -> tuple[spotipy.Spotify, str]:
    """Load credentials from .env file and return an authenticated Spotify client and Last.fm API key."""
    load_dotenv()

    required_keys = [
        "SPOTIPY_CLIENT_ID",
        "SPOTIPY_CLIENT_SECRET",
        "SPOTIPY_REDIRECT_URI",
        "LASTFM_API_KEY",
    ]
    # os.environ raises KeyError on missing keys; os.getenv would silently return None
    # and produce a cryptic error later inside Spotipy — failing fast here is cleaner
    try:
        client_id, client_secret, redirect_uri, lastfm_api = [
            os.environ[key] for key in required_keys
        ]
    except KeyError as e:
        raise ValueError(f"Error: Missing {e.args[0]} environment variable. Check your .env file.")

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="playlist-read-private playlist-read-collaborative",
        )
    )

    return sp, lastfm_api


def fetch_tracks(sp: spotipy.Spotify, playlist: str) -> tuple[list[dict], set[str]]:
    """Fetch all tracks from a Spotify playlist and return a list of song dicts and a set of unique artist names."""

    songs = []
    unique_artists = set()
    results = sp.playlist_items(playlist)

    # Spotify returns a maximum of 50 tracks per request; results["next"] is None on the last page
    while True:
        for item in results["items"]:
            track = item["item"]
            if track is None or track.get("type") != "track":
                # Spotify can return null entries for locally added or unavailable tracks
                continue

            song = {
                "song": track["name"],
                "artist": track["artists"][0]["name"],
                "album": track["album"]["name"],
                "duration": ms_to_time(track["duration_ms"]),
            }

            # set() deduplicates artists so we only make one Last.fm call per artist
            unique_artists.add(track["artists"][0]["name"])
            songs.append(song)

        if results["next"]:
            results = sp.next(results)
        else:
            break

    # SpotifyException is intentionally not caught here — main() handles it so the
    # error can be logged and reported to the user without a raw traceback
    return songs, unique_artists


def fetch_genres(
    lastfm_api: str, unique_artists: set[str]
) -> tuple[dict[str, str], dict[str, float | int]]:
    """Look up the top genre tag for each artist via Last.fm. Returns artist-to-genre mapping."""
    artists_genres = {}
    error_count = 0

    # Last.fm error codes that indicate a global failure affecting all requests,
    # not just a single artist lookup. Continuing would just repeat the same error.
    # See: https://www.last.fm/api/errorcodes
    GLOBAL_ERROR_CODES = {
        2,  # Invalid service
        3,  # Invalid authentication method
        4,  # Authentication failed (bad API key)
        8,  # Operation failed (temporary backend error)
        10,  # Invalid API key
        11,  # Service offline
        16,  # Temporary error - try again
        26,  # API key suspended
        29,  # Rate limit exceeded
    }

    print("Fetching genres via Last.fm API...")
    for artist in tqdm(unique_artists, desc="Artists Processed"):
        try:
            params = {
                "method": "artist.gettoptags",
                "artist": artist,
                "api_key": lastfm_api,
                "format": "json",
            }

            response = lastfm_session.get(
                "https://ws.audioscrobbler.com/2.0/", params=params, timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                error_code = data.get("error")
                message = data.get("message", "Unknown Last.fm error")

                if error_code in GLOBAL_ERROR_CODES:
                    raise RuntimeError(f"Last.fm API error {error_code}: {message}")

                # Per-artist errors (e.g., artist not found) — log and continue
                logging.error(f"Last.fm API error for {artist}: {error_code} - {message}")
                artists_genres[artist] = "unknown"
                print(f"Genre-lookup failure for {artist} via Last.fm API.")
                error_count += 1
                continue

            tags = data.get("toptags", {}).get("tag", [])

            # Last.fm returns tags sorted by vote count — index 0 is the most agreed-upon genre
            if tags:
                genre = tags[0]["name"]
                artists_genres[artist] = genre
            else:
                artists_genres[artist] = "unknown"
                error_count += 1

            # Last.fm rate-limits aggressively; exceeding it causes lockouts of over an hour.
            # getattr checks for a cached response so we skip the delay on cache hits —
            # defaults to False to ensure the sleep runs when the attribute is absent
            if not getattr(response, "from_cache", False):
                time.sleep(1)

        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            # A single failed lookup shouldn't abort the whole export —
            # log it and continue with "unknown" so the rest of the data is still saved
            logging.error(f"Failed to get genre for {artist}: {e}")
            error_count += 1
            artists_genres[artist] = "unknown"

    return artists_genres, {
        "error_count": error_count,
        "total": len(unique_artists),
        "error_rate": error_count / len(unique_artists) if unique_artists else 0,
    }


def save_output(songs: list[dict], artists_genres: dict[str, str]) -> None:
    """Save the full track list to music.json and the artist-genre mapping to genres.json."""
    with open("genres.json", "w", encoding="utf-8") as f:
        json.dump(artists_genres, f, indent=4)

    with open("music.json", "w", encoding="utf-8") as f:
        json.dump(songs, f, indent=4)


def main() -> None:
    """Orchestrate track fetching, genre lookup, and file output."""
    parser = argparse.ArgumentParser(description="Export Spotify playlist tracks to JSON")
    parser.add_argument("playlist_id", nargs="?", help="Spotify playlist ID")
    args = parser.parse_args()

    # authenticate() can raise ValueError if .env keys are missing, or SpotifyOauthError
    # if credentials are malformed or OAuth flow fails — both produce raw tracebacks without this
    try:
        sp, lastfm_api = authenticate()
    except (SpotifyOauthError, ValueError) as e:
        logging.error(f"Failed to authenticate Spotify authorization: {e}")
        print("Error: Could not authenticate API data. Please check the .env file.")
        return

    playlist = args.playlist_id if args.playlist_id else input("Enter Spotify playlist ID: ")

    # SpotifyException is caught here rather than inside fetch_tracks so that main()
    # controls user-facing output — log the error, print a clean message, exit gracefully
    try:
        songs, unique_artists = fetch_tracks(sp, playlist)
    except spotipy.exceptions.SpotifyException as e:
        logging.error(f"Failed to fetch tracks for {playlist}: {e}")
        print(
            "Error: Could not retrieve playlist. Verify the playlist ID and that your account has access to it."
        )
        return

    # Distinguishes a valid but empty playlist from a fetch failure,
    # since both would otherwise produce empty output with no explanation
    if not songs:
        print("Playlist is empty. Nothing to export.")
        return

    # fetch_genres() contains a long-running tqdm loop — Ctrl+C would otherwise print
    # a full traceback, making it look like a crash rather than a deliberate cancellation
    try:
        artists_genres, genre_metrics = fetch_genres(lastfm_api, unique_artists)
    except KeyboardInterrupt:
        print("Export cancelled.")
        return
    except RuntimeError as e:
        logging.error(f"Last.fm API failure: {e}")
        print(f"Error: {e}")
        print("Genre lookup aborted. Please try again or check your Last.fm API key.")
        return

    if unique_artists:
        print(
            f"{genre_metrics['error_rate'] * 100:.1f}% genre lookup failure rate "
            f"({genre_metrics['error_count']}/{genre_metrics['total']})"
        )
    else:
        print("No artists to process.")

    # Genre mapping happens here rather than inside fetch_genres to keep
    # that function focused on one job: talking to the API
    for song in songs:
        song["genre"] = artists_genres.get(song["artist"], "unknown")

    # OSError covers PermissionError and FileNotFoundError — if either file can't be written
    # after a full successful fetch, log the cause and exit cleanly rather than crashing
    try:
        save_output(songs, artists_genres)
    except OSError as e:
        logging.error(f"Failed to save output for {playlist}: {e}")
        print("Unable to save file.")
        return

    print("Export complete! Files saved to music.json and genres.json.")


if __name__ == "__main__":
    main()

"""
Future Improvements:
- Replace song dicts with a Track dataclass
Dataclasses have autocomplete, catch typos at definition time, and make data contract explicit.

- Standardize logging (add INFO + structured messages)
Only logging at error level, so there's no visibility into normal execution. 
Adding INFO logs at key milestones (authenticated, fetched N tracks, saved output) would make debugging less blind. 
Structured messages (including the playlist ID, counts, etc.) would make the log file more useful.

- Add CLI flags (argparse upgrade)
'--output-dir' or '--no-genres' would make the tool meaningfully more flexible.

- Add retry/backoff for API calls (even simple exponential)
A simple exponential backoff on transient Last.fm errors (codes 8, 16 especially) 
would make the tool more robust on longer playlists.
"""
