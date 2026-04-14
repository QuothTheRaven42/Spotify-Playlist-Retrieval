import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import json
import requests
import time


def ms_to_time(ms: int) -> str:
    """Convert milliseconds to a MM:SS formatted string."""
    seconds, _ = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def main():

    # Load credentials from .env file
    load_dotenv()

    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI")
    lastfm_api = os.getenv("LASTFM_API_ID")

    # Playlist ID to export — taken from the end of a Spotify playlist URL
    playlist = "4oCMnGMB2N5OwAKU6zm02F"

    # Authenticate with Spotify — opens a browser window on first run
    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
    )

    # Fetch the first page of tracks from the playlist
    results = sp.playlist_tracks(playlist)

    songs = []
    unique_artists = set()
    artists_genres = {}

    # Loop through all pages of results — Spotify returns max 50 tracks per request
    while True:
        for num in range(len(results["items"])):
            track = results["items"][num]["item"]

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

    unique_artists = list(unique_artists)

    # Look up the top genre tag for each unique artist via Last.fm
    # One API call per artist with a delay to avoid rate limiting
    for artist in unique_artists:
        try:
            params = {"method": "artist.gettoptags", "artist": artist, "api_key": lastfm_api, "format": "json"}
            response = requests.get("https://ws.audioscrobbler.com/2.0/", params=params)
            time.sleep(0.5)

            tags = response.json()["toptags"]["tag"]

            # Take the highest-voted tag as the genre, or "unknown" if no tags exist
            genre = tags[0]["name"] if tags else "unknown"
            artists_genres[artist] = genre

        except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError):
            # If the request fails for any reason, default to "unknown"
            artists_genres[artist] = "unknown"

    # Add genre to each song using the artist-to-genre dictionary
    for song in songs:
        song["genre"] = artists_genres[song["artist"]]

    # Save the artist-to-genre mapping for reference
    with open("genres.json", "w", encoding="utf-8") as f:
        json.dump(artists_genres, f, indent=4, ensure_ascii=False)

    # Save the full track list with all fields
    with open("music.json", "w", encoding="utf-8") as f:
        json.dump(songs, f, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    main()
