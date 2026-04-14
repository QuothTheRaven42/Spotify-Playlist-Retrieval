# Spotify Playlist Exporter

A Python script that exports all tracks from a Spotify playlist to a JSON file, including song title, artist, album, duration, and genre. Genre data is sourced from Last.fm since Spotify has deprecated genre information from their API.

## Features

- Fetches all tracks from any Spotify playlist
- Handles pagination automatically (playlists of any length)
- Looks up genre for each unique artist via Last.fm
- Exports track data to `music.json`
- Exports artist-to-genre mapping to `genres.json`
- Converts track duration from milliseconds to `MM:SS` format

## Requirements

- Python 3.7+
- A [Spotify Developer account](https://developer.spotify.com) with a registered app
- A [Last.fm API account](https://www.last.fm/api/account/create) with an API key

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/QuothTheRaven42/Spotify-Playlist-Retrieval
   cd spotify-playlist-exporter
   ```

2. Install dependencies:
   ```
   pip install spotipy python-dotenv requests
   ```

3. Create a `.env` file in the project root with your credentials:
   ```
   SPOTIPY_CLIENT_ID=your_spotify_client_id
   SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
   SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
   LASTFM_API_ID=your_lastfm_api_key
   ```

## Spotify Developer Setup

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and log in
2. Create a new app
3. In the app settings, add `http://127.0.0.1:8888/callback` as a Redirect URI and save
4. Copy the Client ID and Client Secret into your `.env` file

## Last.fm API Setup

1. Go to [Last.fm API](https://www.last.fm/api/account/create) and create an account
2. Create an API application to receive an API key
3. Copy the API key into your `.env` file

## Usage

Set the playlist ID in `main()`:

```python
playlist = "your_playlist_id_here"
```

The playlist ID is the string at the end of a Spotify playlist URL without the question mark or anything after it:

```
https://open.spotify.com/playlist/2qOyhfKK44u2USaxUyqDVn?si=c1a407e411294b71
                                  ^^^^^^^^^^^^^^^^^^^^^^
                                  This is the playlist ID
```

Then run the script:

```
python spotify_exporter.py
```

On first run, a browser window will open asking you to log in to Spotify and authorize the app. A `.cache` file will be created to store your token for future runs.

Genre lookup makes one API call per unique artist with a 0.25 second delay between requests. For large playlists with many unique artists this may take a few minutes.

## Output

The script generates two files:

`music.json` — one entry per track:
```json
[
    {
        "song": "Madhouse",
        "artist": "Anthrax",
        "album": "Spreading The Disease",
        "duration": "04:19",
        "genre": "thrash metal"
    }
]
```

`genres.json` — artist-to-genre mapping:
```json
{
    "Anthrax": "thrash metal",
    "Metallica": "thrash metal"
}
```

## Notes

- Genre data comes from Last.fm user-applied tags. The highest-voted tag is used. Artists with no tags default to `"unknown"`.
- The `.env` and `.cache` files are excluded from version control via `.gitignore`. Never commit them to a public repository.

## Dependencies

- [Spotipy](https://spotipy.readthedocs.io/) — Python library for the Spotify Web API
- [python-dotenv](https://pypi.org/project/python-dotenv/) — Loads environment variables from a `.env` file
- [requests](https://pypi.org/project/requests/) — HTTP library for the Last.fm API calls

## License

MIT
