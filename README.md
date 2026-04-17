# Spotify Playlist Exporter
A Python script that exports all tracks from a Spotify playlist to a JSON file, including song title, artist, album, duration, and genre. Genre data is sourced from Last.fm since Spotify has deprecated genre information from their API.

## Features
- Fetches all tracks from any Spotify playlist (unless curated by Spotify itself)
- Handles pagination automatically (playlists of any length)
- Skips non-track playlist items (podcast episodes, unavailable tracks)
- Looks up genre for each unique artist via Last.fm
- Detects global Last.fm API failures (invalid key, rate limiting) and stops with a clear error
- **Uses local caching to make subsequent API calls instantly fast**
- **Displays a live progress bar during data fetching**
- Exports track data to `music.json`
- Exports artist-to-genre mapping to `genres.json`
- Converts track duration from milliseconds to `MM:SS` format
- Logs errors to `log.log`

## Requirements
- Python 3.10+
- A Spotify Developer account with a registered app
- A Last.fm API account with an API key

## Installation

1. Clone this repository:
```bash
git clone https://github.com/QuothTheRaven42/Spotify-Playlist-Retrieval
cd Spotify-Playlist-Retrieval
```
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Create a `.env` file in the project root with your credentials:
```
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
LASTFM_API_KEY=your_lastfm_api_key
```

## Architecture

The script is organized as a linear pipeline of four functions orchestrated by `main()`:

1. `authenticate()` — loads credentials from `.env` and returns an authorized Spotify client and Last.fm API key
2. `fetch_tracks()` — pages through the playlist and returns a list of track dicts and a set of unique artist names
3. `fetch_genres()` — queries Last.fm once per unique artist and returns an artist-to-genre mapping and error metrics
4. `save_output()` — writes the enriched track list and genre mapping to JSON files

Artist deduplication happens at the `fetch_tracks` stage so that a playlist with 50 Metallica songs only triggers one Last.fm API call. Genre enrichment — merging the mapping back into the track list — happens in `main()` after both fetches are complete.

## Tradeoffs

- **One genre per artist** — Last.fm returns a ranked list of tags, but only the top tag is used. Artists that span genres (e.g., Neil Young) get a single label that may not reflect the current song.
- **Tag quality varies** — genre data is user-applied and crowdsourced. Some artists have well-agreed-upon tags; others have their own name as the top tag (e.g., "metallica" for Metallica).
- **Caching trades freshness for speed** — Last.fm responses are cached for 24 hours. Artists whose tags change within that window will return stale data until the cache expires.
- **1-second rate limit delay** — conservative but reliable. A large playlist takes time; roughly 2 minutes per 100 unique artists.
- **First artist per track only** — for multi-artist tracks, only the primary artist is used for genre lookup and attribution.

## Development / Testing

To install both runtime and test dependencies:
```bash
pip install -r requirements-dev.txt
```

Run the test suite:
```bash
pytest
```

Tests are also run automatically on push and pull request via GitHub Actions (`.github/workflows/tests.yml`).

## Spotify Developer Setup
1. Go to the Spotify Developer Dashboard and log in
2. Create a new app
3. In the app settings, add `http://127.0.0.1:8888/callback` as a Redirect URI and save
4. Copy the Client ID and Client Secret into your `.env` file

## Last.fm API Setup
1. Go to Last.fm API and create an account
2. Create an API application to receive an API key
3. Copy the API key into your `.env` file

## Usage
Run the script and enter your playlist ID when prompted:
```bash
python main.py
```
The playlist ID is the string at the end of a Spotify playlist URL, without the question mark or anything after it:
```
https://open.spotify.com/playlist/2qOyhfKK44u2USaxUyqDVn?si=c1a407e411294b71
                                  ^^^^^^^^^^^^^^^^^^^^^^
                                  This is the playlist ID
```

On first run, a browser window will open asking you to log in to Spotify and authorize the app. A `.cache` file will be created to store your token for future runs.

> **Note:** Spotify-curated playlists may return a 404 error and are not supported.

Genre lookup makes one API call per unique artist with a 1-second delay between requests. Expect about 2 minutes per 100 songs.

## Output
The script generates two JSON data files:

`music.json` -- one entry per track:
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

`genres.json` -- artist-to-genre mapping:
```json
{
    "Anthrax": "thrash metal",
    "Jefferson Airplane": "Psychedelic Rock"
}
```

## Notes
- Genre data comes from Last.fm user-applied tags. The highest-voted tag is used. Artists with no tags default to `"unknown"`.
- Some bands have top tags that are less than informative, such as Metallica's being "metallica."
- Playlists containing podcast episodes or other non-track items will have those items silently skipped -- only tracks are exported.
- Global Last.fm API failures such as an invalid API key, suspended key, or rate limiting will stop the genre lookup and display an error rather than silently exporting `"unknown"` for every artist.
- The `.env`, `.cache`, `lastfm_cache.sqlite`, `.venv/`, `.pytest_cache/`, and `.mypy_cache/` are excluded from version control via `.gitignore`.
- Errors are appended to `log.log` in the project directory.

## Dependencies
- **Spotipy** -- Python library for the Spotify Web API
- **python-dotenv** -- Loads environment variables from a `.env` file
- **requests** -- HTTP library for the Last.fm API calls
- **tqdm** -- Generates the CLI progress bar
- **requests-cache** -- Caches Last.fm API responses to prevent rate limiting

## License
MIT
