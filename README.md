# Spotify Playlist Retrieval

A Python CLI for working with Spotify playlists: export tracks to JSON with genre data, create new playlists from JSON, or add songs from JSON to an existing playlist.

## Why This Exists

I built this for a practical use case: pulling structured data from my own playlists so I could inspect listening patterns and use that data elsewhere. It also gave me a compact project for showing a few core skills that matter in junior portfolio work:

- working with two external APIs
- handling pagination and mixed-content responses safely
- writing tests for error paths instead of only the happy path
- documenting tradeoffs and setup clearly

## Features

**Export**
- exports playlist tracks to `music.json` with song, artist, album, duration, and genre
- exports artist-to-genre mappings to `genres.json`
- supports playlist IDs and full Spotify playlist URLs
- skips podcast episodes, unavailable items, and malformed track payloads
- looks up each unique artist once to avoid redundant Last.fm calls
- caches Last.fm responses locally for 24 hours
- prints a progress bar during genre lookup
- logs handled API and file-write failures to `log.log`

**Import**
- creates a new private Spotify playlist from a `music.json` file
- opens a file picker dialog to select the JSON file
- searches Spotify for each track and adds all found tracks

**Add**
- appends songs from a `music.json` file to an existing Spotify playlist
- accepts a playlist ID or full URL

## Requirements

- Python 3.10+
- Spotify Developer app credentials
- Last.fm API key (export only)

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

> `LASTFM_API_KEY` is only required for the export command.

## Usage

### Interactive menu

Running with no arguments shows a menu:

```bash
python main.py
```

```
What would you like to do?
  1) Export a Spotify playlist to JSON
  2) Create a new Spotify playlist from a JSON file
  3) Add songs from a JSON file to an existing playlist
Enter 1, 2, or 3:
```

### Subcommands

All three modes are also available as direct subcommands.

**Export** a Spotify playlist to JSON:

```bash
python main.py export 2qOyhfKK44u2USaxUyqDVn
python main.py export https://open.spotify.com/playlist/2qOyhfKK44u2USaxUyqDVn?si=abc123
```

Omit the playlist ID to be prompted for it interactively.

**Import** — create a new playlist from a `music.json` file:

```bash
python main.py import music.json "My New Playlist"
```

Omit either argument to be prompted. The JSON file can also be selected with a file picker dialog.

**Add** — append songs to an existing playlist:

```bash
python main.py add music.json 2qOyhfKK44u2USaxUyqDVn
python main.py add music.json https://open.spotify.com/playlist/2qOyhfKK44u2USaxUyqDVn
```

Omit either argument to be prompted. The JSON file picker dialog opens automatically if no path is given.

### First-run OAuth

On the first run, Spotify opens a browser window for OAuth approval. Spotipy stores a local `.cache` token file so later runs do not need to re-authorize unless the token expires or the app's scopes change.

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

The `music.json` format is the same one accepted by the import and add commands.

## Design Notes

- Spotify playlist items are not guaranteed to be normal tracks. The script explicitly skips episodes, null items, and malformed track payloads.
- Last.fm genres are user-generated tags, so they are useful but imperfect.
- Only the primary artist is used for genre lookup.
- The script uses one top tag per artist to keep the output simple and consistent.
- A 1-second delay is applied to uncached Last.fm requests to stay conservative with rate limits.
- Tracks are added to Spotify in batches of 100, which is the API's per-request limit.
- Track search uses `track:<name> artist:<name>` queries; some tracks may not be found if titles differ slightly between sources.

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
- Track search during import/add is best-effort; tracks with unusual titles or live versions may not resolve correctly.

## License

MIT. See `LICENSE`.
