import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import json
import requests
import time
from datetime import timedelta
import logging

logging.basicConfig(filename="log.log", level=logging.ERROR)


def ms_to_time(ms: int) -> str:
    """Convert milliseconds to a MM:SS formatted string."""
    delta = timedelta(milliseconds=ms)
    seconds = int(delta.total_seconds())
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def authenticate() -> tuple[spotipy.Spotify, str]:
    """Load credentials from .env file and return an authenticated Spotify client and Last.fm API key."""
    load_dotenv()

    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI")
    lastfm_api = os.getenv("LASTFM_API_KEY")
    api_responses = {
        "SPOTIPY_CLIENT_ID": client_id,
        "SPOTIPY_CLIENT_SECRET": client_secret,
        "SPOTIPY_REDIRECT_URI": redirect_uri,
        "LASTFM_API_KEY": lastfm_api,
    }

    # checks for None in any os.getenv calls
    for key, value in api_responses.items():
        if value is None:
            raise EnvironmentError(
                f"Error: Missing {key} environment variable. Check your .env file."
            )

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
        )
    )

    return sp, lastfm_api


def fetch_tracks(sp: spotipy.Spotify, playlist: str) -> tuple[list[dict], set[str]]:
    """Fetch all tracks from a Spotify playlist and return a list of song dicts and a set of unique artist names."""
    try:
        songs = []
        unique_artists = set()
        # Fetch the first page of tracks from the playlist
        results = sp.playlist_tracks(playlist)

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
    except Exception as e:
        logging.error(f"Failed to fetch tracks for {playlist}: {e}")
        return [], set()


def fetch_genres(lastfm_api: str, unique_artists: set, songs: list[dict]) -> dict[str, str]:
    """Look up the top genre tag for each artist via Last.fm and add it to each song dict. Returns artist-to-genre mapping."""
    artists_genres = {}
    # Look up the top genre tag for each unique artist via Last.fm
    # One API call per artist with a delay to avoid rate limiting
    for artist in unique_artists:
        try:
            params = {
                "method": "artist.gettoptags",
                "artist": artist,
                "api_key": lastfm_api,
                "format": "json",
            }
            response = requests.get("https://ws.audioscrobbler.com/2.0/", params=params)
            tags = response.json()["toptags"]["tag"]

            # Take the highest-voted tag as the genre, or "unknown" if no tags exist
            genre = tags[0]["name"] if tags else "unknown"
            artists_genres[artist] = genre

            # avoids overloading last.fm's API, they will shut you down for over an hour
            time.sleep(1)

        except Exception as e:
            # If the request fails for any reason, default to "unknown"
            logging.error(f"Failed to get genre for {artist}: {e}")
            artists_genres[artist] = "unknown"

    # Add genre to each song using the artist-to-genre dictionary
    for song in songs:
        song["genre"] = artists_genres[song["artist"]]

    return artists_genres


def save_output(songs: list[dict], artists_genres: dict[str, str]):
    """Save the full track list to music.json and the artist-genre mapping to genres.json."""
    # Save the artist-to-genre mapping for reference
    with open("genres.json", "w", encoding="utf-8") as f:
        json.dump(artists_genres, f, indent=4)

    # Save the full track list with all fields
    with open("music.json", "w", encoding="utf-8") as f:
        json.dump(songs, f, indent=4)


def main():
    """Orchestrate track fetching, genre lookup, and file output."""
    sp, lastfm_api = authenticate()

    # Playlist ID to export — between "/" and "?" in the URL
    playlist = input("Enter Spotify playlist ID: ")

    songs, unique_artists = fetch_tracks(sp, playlist)

    artists_genres = fetch_genres(lastfm_api, unique_artists, songs)

    save_output(songs, artists_genres)


if __name__ == "__main__":
    main()
