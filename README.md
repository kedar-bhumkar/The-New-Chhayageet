# The New Chhayageet

The New Chhayageet builds weekly Hindi-song playlists on YouTube from a precomputed song catalog stored in Supabase.

The current `main` branch is catalog-driven:
- source songs come from CSVs imported into Supabase
- YouTube Search API is not used for song discovery
- YouTube is used only for account auth and playlist management
- Supabase is the source of truth for catalog data, listener taste, runtime config, and curation history

The older YouTube-search-based implementation was preserved on the Git branch:
- `feature/youtube-search-curator`

## What The App Does

Each run does this:

1. loads a listener profile from Supabase
2. loads runtime guidance from Supabase
3. picks unused songs from the Supabase catalog
4. joins songs with album metadata
5. filters out devotional songs and already-used songs
6. validates YouTube URLs using HTTP oEmbed checks
7. selects a final playlist with decade balance and diversity rules
8. creates or updates a dated YouTube playlist
9. marks selected songs as used globally
10. writes run history back to Supabase

Example playlist title:

```text
Chaayageet - 2026-04-10
```

## Architecture

Main modules:

- [cli.py](C:\DDrive\Programming\Project\misc\The New Chhayageet\chhayageet\cli.py): command entry point
- [csv_importer.py](C:\DDrive\Programming\Project\misc\The New Chhayageet\chhayageet\csv_importer.py): imports album/song CSV files into Supabase
- [catalog_store.py](C:\DDrive\Programming\Project\misc\The New Chhayageet\chhayageet\catalog_store.py): fetches candidates and updates song usage/history
- [catalog_curation_engine.py](C:\DDrive\Programming\Project\misc\The New Chhayageet\chhayageet\catalog_curation_engine.py): selection logic for catalog mode
- [url_validator.py](C:\DDrive\Programming\Project\misc\The New Chhayageet\chhayageet\url_validator.py): validates YouTube URLs without YouTube Search API
- [youtube_client.py](C:\DDrive\Programming\Project\misc\The New Chhayageet\chhayageet\youtube_client.py): OAuth and playlist sync
- [config.py](C:\DDrive\Programming\Project\misc\The New Chhayageet\chhayageet\config.py): profile and guidance models
- [history_store.py](C:\DDrive\Programming\Project\misc\The New Chhayageet\chhayageet\history_store.py): Supabase access layer

## Data Model

The app relies on these Supabase tables.

### `albums`

Stores album-level metadata imported from CSV:

- `album_uuid`
- `album_title`
- `album_year`
- `album_category`
- `album_music_director`
- `album_lyricist`
- `album_label`
- `album_rating`

### `songs`

Stores song-level metadata imported from CSV:

- `song_uuid`
- `album_uuid`
- `track_number`
- `song_title`
- `song_singers`
- `song_rating`
- `youtube_url`
- `music_yt_url_1`
- `music_yt_url_2`
- `music_yt_url_3`
- `youtube_video_id`
- `is_used`
- `used_at`
- `used_playlist_title`
- `used_playlist_id`
- `last_validated_at`
- `is_youtube_live`
- `validation_status`

The important operational rule is:

```text
is_used = true
```

Once a song is selected in any playlist, it is treated as used globally and will not be selected again.

### `listener_profiles`

Stores long-lived taste information for a listener.

Current profile responsibilities:

- `preferred_artists`
- `preferred_music_directors`
- `preferred_eras`
- `preferred_moods`
- `exclude_keywords`
- playlist description text

Think of this as:

```text
who this listener is
```

### `config`

Stores run-time guidance under the `guidance` JSON column.

Current guidance responsibilities:

- `youtube_account`
- `no_of_songs_per_playlist`
- `playlist_name_prefix`
- `preferred_model`
- `mode`
- `candidate_pool_size`
- `year_min`
- `year_max`
- `min_song_rating`
- `min_album_rating`

Think of this as:

```text
how this run should execute
```

### `curated_videos`

Stores historical records of which songs were selected into which playlist.

In catalog mode, rows are written with:

- `source = catalog`
- `song_uuid`
- `album_uuid`
- `youtube_url`

### `curation_runs`

Stores one row per playlist generation run:

- playlist title
- run timestamp
- candidate count
- selected count

## Listener Profile vs Guidance

This split is important.

### Listener Profile

Stable taste:

- favorite singers
- favorite music directors
- broad era preference
- excluded kinds of songs

### Guidance

Operational settings:

- which YouTube account to use
- how many songs to include
- candidate pool size
- year window for this mode
- whether the run is `random` or `user-driven`

## Modes

### `random`

Random mode:

- samples unused songs from the catalog
- filters devotional content
- validates URLs
- picks a final list with general diversity rules

This mode does not try to strongly reflect user taste beyond the global data hygiene rules.

### `user-driven`

User-driven mode is the primary production mode on `main`.

It:

- uses the listener profile’s preferred artists
- uses the listener profile’s preferred music directors
- respects year bounds from guidance
- filters devotional songs
- prefers stronger-rated songs/albums
- balances final picks across the 1950s, 1960s, 1970s, 1980s, and 1990s
- avoids too many songs from the same singer/album/music director

Current decade balancing aims to avoid clustering and produce a spread such as:

```text
1950s=2
1960s=2
1970s=3
1980s=3
1990s=2
```

depending on candidate availability.

### `youtube-search`

This mode remains in the codebase for the old flow, but it is not the preferred path on `main`.

Use the `feature/youtube-search-curator` branch if you want the earlier search-first behavior.

## Devotional Filtering

The devotional filter is currently rule-based, not LLM-based.

It works by checking song text fields such as:

- song title
- album title
- singer text

against a curated keyword list in [catalog_store.py](C:\DDrive\Programming\Project\misc\The New Chhayageet\chhayageet\catalog_store.py).

Examples of blocked terms:

- `bhajan`
- `devotional`
- `aarti`
- `mantra`
- `chalisa`
- `kirtan`
- `krishna`
- `ram`
- `shiva`
- `hanuman`
- `ganesha`
- `prabhu`

This is deterministic and cheap, but not semantically perfect. Some borderline songs may still get through and may require future keyword tuning.

## Role Of The LLM

In the current catalog-driven flow, the LLM is optional and usually disabled.

Current recommendation:

- keep `preferred_model = none` for production catalog mode unless you explicitly want experiments

Why:

- the app already knows the candidate songs from Supabase
- no YouTube search discovery is needed
- selection is mostly deterministic and rule-based
- LLM is not required for URL validation or playlist publishing

Potential future LLM uses:

- rerank borderline candidates by vibe
- generate a short playlist blurb
- classify ambiguous songs that the devotional filter is unsure about

But those are enhancements, not core dependencies.

## YouTube Account Handling

The active YouTube account comes from:

```text
config.guidance.youtube_account
```

If the guidance value is `kedar`, the app looks for:

- `secrets/youtube/kedar-secret.json`
- `secrets/youtube/kedar-token.pickle`

If the value is `mandar`, it looks for:

- `secrets/youtube/mandar-secret.json`
- `secrets/youtube/mandar-token.pickle`

This makes it easy to publish the same app from multiple personal YouTube accounts.

## Setup

### 1. Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Create a top-level `.env`

Recommended variables:

- `SUPABASE_PAT`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Optional fallback Supabase key:

- `SUPABASE_ANON_KEY`

Optional default YouTube auth paths:

- `YOUTUBE_OAUTH_CLIENT_SECRETS_JSON`
- `YOUTUBE_OAUTH_TOKEN_JSON`

Optional LLM keys:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `GOOGLE_API_KEY`
- `OLLAMA_BASE_URL`

### 3. Create YouTube OAuth desktop clients

For each YouTube account, create or download the Google OAuth desktop client JSON and place it under:

```text
secrets/youtube/<account>-secret.json
```

Example:

```text
secrets/youtube/kedar-secret.json
```

The corresponding token file is created automatically after the first successful auth flow:

```text
secrets/youtube/kedar-token.pickle
```

### 4. Apply the Supabase schema

Run the SQL in [schema.sql](C:\DDrive\Programming\Project\misc\The New Chhayageet\supabase\schema.sql).

If you already linked the project locally with the Supabase CLI:

```powershell
npx supabase db query --linked -f supabase\schema.sql
```

### 5. Prepare the listener profile

Edit [profile.json](C:\DDrive\Programming\Project\misc\The New Chhayageet\config\profile.json).

Important fields:

- `preferred_artists`
- `preferred_music_directors`
- `exclude_keywords`
- `playlist_description`

Sync it into Supabase:

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli sync-profile --profile config/profile.json
```

### 6. Import the catalog CSVs

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli import-catalog --albums-dir "data/songs/All/data/raw/albums data" --songs-dir "data/songs/All/data/raw/songs data"
```

This loads:

- albums into `albums`
- songs into `songs`
- extracted YouTube video IDs into `songs.youtube_video_id`

### 7. Configure runtime guidance

Example production config:

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli sync-config --config-key default --youtube-account kedar --songs-per-playlist 12 --playlist-prefix Chaayageet --mode user-driven --candidate-pool-size 50 --year-min 1950 --year-max 1999 --preferred-model none
```

### 8. Authenticate the YouTube account

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli auth-youtube --config-key default --force
```

The browser consent flow will generate the matching token file for that account.

## Commands

### Sync Profile

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli sync-profile --profile config/profile.json
```

### Sync Guidance

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli sync-config --config-key default --youtube-account kedar --songs-per-playlist 12 --playlist-prefix Chaayageet --mode user-driven --candidate-pool-size 50 --year-min 1950 --year-max 1999 --preferred-model none
```

### Import Catalog

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli import-catalog --albums-dir "data/songs/All/data/raw/albums data" --songs-dir "data/songs/All/data/raw/songs data"
```

### Authenticate YouTube

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli auth-youtube --config-key default --force
```

### Dry Run

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli run-weekly --profile-id default --config-key default --verbose --dry-run
```

Dry run:

- validates URLs
- builds the final selected set
- prints candidates and selected songs
- does not create or update a playlist
- does not mark songs as used
- does not write run history

### Real Run

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli run-weekly --profile-id default --config-key default --verbose
```

Real run:

- creates or reuses the dated playlist
- adds missing songs
- removes songs that no longer belong
- marks selected songs as used
- records the run in Supabase

## Candidate Selection Logic

At a high level:

```text
Supabase songs/albums
  -> filter unused
  -> filter devotional
  -> validate YouTube URLs
  -> score by taste and ratings
  -> enforce decade and diversity balance
  -> select final 12
```

Current scoring influences:

- song rating
- album rating
- preferred artist match
- preferred music director match
- mild decade shaping

Current hard constraints:

- global no-repeat through `songs.is_used`
- devotional exclusion
- candidate must have a valid/live YouTube URL
- no duplicate albums in final set
- no excessive singer repetition
- no excessive music-director repetition

## URL Validation

The app does not use YouTube Search API for catalog mode.

Instead, it validates exact YouTube URLs using HTTP oEmbed checks.

This gives a cheap “is this video live enough to use?” signal without spending YouTube Search quota.

## Notes On Re-Runs

For catalog mode:

- dry runs do not consume songs
- real runs mark selected songs as used globally
- same-day reruns reuse the existing selected catalog set for that playlist title instead of consuming more songs

That prevents the playlist from shrinking or drifting when rerun on the same date.

## Repository Notes

- Sensitive files under `.env`, `secrets/`, `credentials/`, `.venv/`, local data directories, and tokens are gitignored.
- The app creates YouTube playlists, not YouTube Music library folders.
- First-time YouTube auth opens a browser window.
- Supabase is the source of truth for profile, guidance, catalog, and history.
