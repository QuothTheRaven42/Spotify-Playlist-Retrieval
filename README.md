# Spotify Playlist Exporter

A Python script that exports all tracks from a public Spotify playlist to a JSON file, including song title, artist, album, and duration.

## Features

- Fetches all tracks from any public Spotify playlist
- Handles pagination automatically (playlists of any length)
- Exports data to a clean, human-readable JSON file
- Converts track duration from milliseconds to `MM:SS` format

## Requirements

- Python 3.7+
- A [Spotify Developer account](https://developer.spotify.com) with a registered app

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/spotify-playlist-exporter
   cd spotify-playlist-exporter
   ```

2. Install dependencies:
   ```
   pip install spotipy python-dotenv
   ```

3. Create a `.env` file in the project root with your Spotify app credentials:
   ```
   SPOTIPY_CLIENT_ID=your_client_id_here
   SPOTIPY_CLIENT_SECRET=your_client_secret_here
   SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
   ```

## Spotify Developer Setup

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and log in
2. Create a new app (name it anything you like)
3. In the app settings, add `http://127.0.0.1:8888/callback` as a Redirect URI and save
4. Copy the Client ID and Client Secret into your `.env` file

## Usage

Run the script and provide the playlist ID when prompted:

```
python spotify_exporter.py
```

The playlist ID is the string of characters at the end of a Spotify playlist URL. For example:

```
https://open.spotify.com/playlist/2qOyhfKK44u2USaxUyqDVn
                                   ^^^^^^^^^^^^^^^^^^^^^^
                                   This is the playlist ID
```

On first run, a browser window will open asking you to log in to Spotify and authorize the app. After that, a `.cache` file will be created to store your token so you won't need to log in again.

## Output

The script generates a `music.json` file in the project directory. Each track is represented as a JSON object:

```json
[
    {
        "song": "Madhouse",
        "artist": "Anthrax",
        "album": "Spreading The Disease",
        "duration": "04:19"
    },
    ...
]
```

## Notes

- The `.env` file contains sensitive credentials and is excluded from version control via `.gitignore`. Never commit it to a public repository.
- The `.cache` file stores your Spotify auth token locally. It is also excluded from version control.

## Dependencies

- [Spotipy](https://spotipy.readthedocs.io/) — Lightweight Python library for the Spotify Web API
- [python-dotenv](https://pypi.org/project/python-dotenv/) — Loads environment variables from a `.env` file

## License

MIT
