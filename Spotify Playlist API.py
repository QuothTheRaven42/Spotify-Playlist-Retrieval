import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import json


def ms_to_time(ms: int) -> str:
    seconds, milliseconds = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    return f"{minutes:02d}:{seconds:02d}"


load_dotenv()

scope = "playlist-read-public"

client_id = os.getenv("SPOTIPY_CLIENT_ID")
client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI")

sp = spotipy.Spotify(
    auth_manager=SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
)

# The first time this runs, it will open a browser window for you to log in
songs = []

results = sp.playlist_tracks("2qOyhfKK44u2USaxUyqDVn")

while True:
    for num in range(len(results["items"])):
        song = {}
        song["song"] = results["items"][num]["item"]["name"]
        song["artist"] = results["items"][num]["item"]["artists"][0]["name"]
        song["album"] = results["items"][num]["item"]["album"]["name"]
        song["duration"] = ms_to_time(results["items"][num]["item"]["duration_ms"])
        songs.append(song)
    if results["next"]:
        results = sp.next(results)
    else:
        break

with open("music.json", "w") as f:
    json.dump(songs, f, indent=4)

# print(songs)
