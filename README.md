# Spotify Playlist Exporter

A small Python CLI that exports tracks from a Spotify playlist and enriches each track with a genre label from Last.fm.

## Why This Exists

I built this for a practical use case: pulling structured data from my own playlists so I could inspect listening patterns and use that data elsewhere. It also gave me a compact project for showing a few core skills that matter in junior portfolio work:

- working with two external APIs
- handling pagination and mixed-content responses safely
- writing tests for error paths instead of only the happy path
- documenting tradeoffs and setup clearly

## Features

- exports playlist tracks to `music.json`
- exports artist-to-genre mappings to `genres.json`
- supports playlist IDs and full Spotify playlist URLs
- skips podcast episodes, unavailable items, and malformed track payloads
- looks up each unique artist once to avoid redundant Last.fm calls
- caches Last.fm responses locally for 24 hours
- prints a progress bar during genre lookup
- logs handled API and file-write failures to `log.log`

## Requirements

- Python 3.10+
- Spotify Developer app credentials
- Last.fm API key

## Setup

1. Clone the repository and enter the project directory.

```bash
git clone https://github.com/QuothTheRaven42/Spotify-Playlist-Retrieval
cd Spotify-Playlist-Retrieval
```

2. Create and activate a virtual environment.

```bash
python -m venv .venv
```

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

3. Install the package.

```bash
pip install .
```

4. Create a local `.env` file from the example template.

```powershell
Copy-Item .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

5. Fill in your credentials inside `.env`.

```text
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
LASTFM_API_KEY=your_lastfm_api_key
```

## Usage

Run the installed console command:

```bash
spotify-playlist-retrieval
```

Or run the script directly:

```bash
python main.py
```

You can also pass a playlist ID or a full playlist URL:

```bash
spotify-playlist-retrieval 2qOyhfKK44u2USaxUyqDVn
spotify-playlist-retrieval https://open.spotify.com/playlist/2qOyhfKK44u2USaxUyqDVn?si=abc123
```

On first run, Spotify opens a browser window for OAuth approval. Spotipy stores a local `.cache` token file so later runs do not need to re-authorize unless the token expires.

## Output

`music.json`

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

`genres.json`

```json
{
    "Anthrax": "thrash metal",
    "Jefferson Airplane": "psychedelic rock"
}
```

## Design Notes

- Spotify playlist items are not guaranteed to be normal tracks. The script explicitly skips episodes, null items, and malformed track payloads.
- Last.fm genres are user-generated tags, so they are useful but imperfect.
- Only the primary artist is used for genre lookup.
- The script uses one top tag per artist to keep the output simple and consistent.
- A 1-second delay is applied to uncached Last.fm requests to stay conservative with rate limits.

## Testing

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Or use the compatibility file:

```bash
pip install -r requirements-dev.txt
```

Run tests:

```bash
python -m pytest
```

GitHub Actions runs the test suite on pushes and pull requests via `.github/workflows/tests.yml`.

## Repo Hygiene

The following are local-only files and should not be committed:

- `.env`
- `.cache`
- `.venv/`
- `.mypy_cache/`
- `lastfm_cache.sqlite`
- `music.json`
- `genres.json`
- `log.log`

## Limitations

- Spotify-curated playlists may not be readable through the API.
- Genre labels are only as good as Last.fm tag quality.
- Large playlists can still take time on the first uncached run because lookups are intentionally conservative.

## License

MIT. See `LICENSE`.
