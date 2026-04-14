import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import json
import requests
import time


def ms_to_time(ms: int) -> str:
    seconds, _ = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def main():

    load_dotenv()

    # playlist = input("Enter playlist ID: ")
    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI")
    lastfm_api = os.getenv("LASTFM_API_ID")
    playlist = "4oCMnGMB2N5OwAKU6zm02F"
    short_playlist = "1O0P1PNKtlc4SWYzAhxecN"

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
    )

    # The first time this runs, it will open a browser window for you to log in
    results = sp.playlist_tracks(short_playlist)

    songs = []
    unique_artists = set()
    artists_genres = {}
    while True:
        for num in range(len(results["items"])):
            song = {}
            song["song"] = results["items"][num]["item"]["name"]
            song["artist"] = results["items"][num]["item"]["artists"][0]["name"]
            song["album"] = results["items"][num]["item"]["album"]["name"]
            song["duration"] = ms_to_time(results["items"][num]["item"]["duration_ms"])
            unique_artists.add(results["items"][num]["item"]["artists"][0]["name"])
            songs.append(song)
        if results["next"]:
            results = sp.next(results)
        else:
            break
    unique_artists = list(unique_artists)

    for artist in unique_artists:
        try:
            params = {"method": "artist.gettoptags", "artist": artist, "api_key": lastfm_api, "format": "json"}
            response = requests.get("https://ws.audioscrobbler.com/2.0/", params=params)
            time.sleep(0.25)
            tags = response.json()["toptags"]["tag"]
            genre = tags[0]["name"] if tags else "unknown"
            artists_genres[artist] = genre
        except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError):
            artists_genres[artist] = "unknown"

    for song in songs:
        song["genre"] = artists_genres[song["artist"]]

    with open("genres.json", "w", encoding="utf-8") as f:
        json.dump(artists_genres, f, indent=4, ensure_ascii=False)

    with open("music.json", "w", encoding="utf-8") as f:
        json.dump(songs, f, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    main()





