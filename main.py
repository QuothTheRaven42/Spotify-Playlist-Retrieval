import spotipy  # type: ignore
from spotipy.oauth2 import SpotifyOAuth  # type: ignore
from dotenv import load_dotenv
import argparse
import os
import json
import requests
import time
from datetime import timedelta
from tqdm import tqdm
import requests_cache
import logging

logging.basicConfig(filename="log.log", level=logging.ERROR)

# adds a caching layer to reduce API calls and improve performance
# 'CachedSession' prevents global side effects by scoping cache to session
lastfm_session = requests_cache.CachedSession("lastfm_cache", expire_after=86400)


def ms_to_time(ms: int) -> str:
    """Convert milliseconds to an MM:SS formatted string."""
    delta = timedelta(milliseconds=ms)
    seconds = int(delta.total_seconds())
    minutes, seconds = divmod(seconds, 60)
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
    try:
        client_id, client_secret, redirect_uri, lastfm_api = [
            os.environ[key] for key in required_keys
        ]
    except KeyError as e:
        raise EnvironmentError(
            f"Error: Missing {e.args[0]} environment variable. Check your .env file."
        )

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
        )
    )

    return sp, lastfm_api


def fetch_tracks(sp: spotipy.Spotify, playlist: str) -> tuple[list[dict], set[str]]:
    """Fetch all tracks from a Spotify playlist and return a list of song dicts and a set of unique artist names."""

    songs = []
    unique_artists = set()
    # Fetch the first page of tracks from the playlist
    results = sp.playlist_items(playlist)

    # Loop through all pages of results — Spotify returns max 50 tracks per request
    while True:
        for item in results["items"]:
            track = item["item"]
            if track is None:
                continue

            # Build a dictionary for each track with the fields we want
            song = {
                "song": track["name"],
                "artist": track["artists"][0]["name"],
                "album": track["album"]["name"],
                "duration": ms_to_time(track["duration_ms"]),
            }

            # Collect unique artist names for the genre lookup
            unique_artists.add(track["artists"][0]["name"])
            songs.append(song)

        # If there's another page of results, fetch it — otherwise stop
        if results["next"]:
            results = sp.next(results)
        else:
            break
    return songs, unique_artists


def fetch_genres(lastfm_api: str, unique_artists: set[str]) -> dict[str, str]:
    """Look up the top genre tag for each artist via Last.fm. Returns artist-to-genre mapping."""
    artists_genres = {}

    # Look up the top genre tag for each unique artist via Last.fm
    # One API call per artist with a delay to avoid rate limiting
    print("Fetching genres via Last.fm API...")
    for artist in tqdm(unique_artists, desc="Artists Processed"):
        try:
            params = {
                "method": "artist.gettoptags",
                "artist": artist,
                "api_key": lastfm_api,
                "format": "json",
            }

            response = lastfm_session.get("https://ws.audioscrobbler.com/2.0/", params=params)
            data = response.json()
            tags = data.get("toptags", {}).get("tag", [])

            # Take the highest-voted tag as the genre, or "unknown" if no tags exist
            genre = tags[0]["name"] if tags else "unknown"
            artists_genres[artist] = genre

            # avoids overloading last.fm's API, they will shut you down for over an hour
            # if-statement checks for cached version to skip sleep, 'False' when nothing found to protect testing
            if not getattr(response, "from_cache", False):
                time.sleep(1)

        except requests.exceptions.RequestException as e:
            # If the request fails for any reason, default to "unknown"
            logging.error(f"Failed to get genre for {artist}: {e}")
            artists_genres[artist] = "unknown"

    return artists_genres


def save_output(songs: list[dict], artists_genres: dict[str, str]):
    """Save the full track list to music.json and the artist-genre mapping to genres.json."""
    with open("genres.json", "w", encoding="utf-8") as f:
        json.dump(artists_genres, f, indent=4)

    with open("music.json", "w", encoding="utf-8") as f:
        json.dump(songs, f, indent=4)


def main():
    """Orchestrate track fetching, genre lookup, and file output."""
    # runs from CLI with playlist ID and adds --help functionality
    parser = argparse.ArgumentParser(description="Export Spotify playlist tracks to JSON")
    parser.add_argument("playlist_id", nargs="?", help="Spotify playlist ID")
    args = parser.parse_args()

    sp, lastfm_api = authenticate()

    # Playlist ID to export — between "/" and "?" in the URL
    playlist = args.playlist_id if args.playlist_id else input("Enter Spotify playlist ID: ")

    # Fetches data from Spotify, logs issues
    try:
        songs, unique_artists = fetch_tracks(sp, playlist)
    except spotipy.exceptions.SpotifyException as e:
        logging.error(f"Failed to fetch tracks for {playlist}: {e}")
        print("Error: Could not retrieve playlist. Check the playlist ID.")
        return

    # Guards against valid but empty playlists
    if not songs:
        print("Playlist is empty. Nothing to export.")
        return

    # fetches from Last.fm
    artists_genres = fetch_genres(lastfm_api, unique_artists)

    # Maps genres to the songs
    for song in songs:
        song["genre"] = artists_genres.get(song["artist"], "unknown")

    save_output(songs, artists_genres)
    print("Export complete! Files saved to music.json and genres.json.")


if __name__ == "__main__":
    main()
