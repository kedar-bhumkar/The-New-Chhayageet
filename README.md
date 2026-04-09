# The New Chhayageet

The New Chhayageet curates Hindi songs from YouTube into a weekly playlist using Python, the YouTube Data API, and Supabase.

## Overview

The app:

- loads listener preferences from Supabase
- loads runtime guidance from Supabase
- searches YouTube for candidate songs
- filters out repeats and videos longer than 8 minutes
- scores and selects a final set
- syncs a dated YouTube playlist such as `Chaayageet - 2026-04-09`

Supabase is the source of truth for:

- listener profiles
- runtime guidance
- curation history
- prior playlist selections

## Runtime Guidance

The `config` table stores a `guidance` JSON object with keys:

- `youtube_account`
- `no_of_songs_per_playlist`
- `playlist_name_prefix`

Example:

```json
{
  "youtube_account": "yt",
  "no_of_songs_per_playlist": 12,
  "playlist_name_prefix": "Chaayageet"
}
```

If `youtube_account` is `yt`, the app resolves YouTube auth files as:

- `secrets/youtube/yt-secret.json`
- `secrets/youtube/yt-token.pickle`

The same pattern works for `Amar`, `Akbar`, `Anthony` and other account names.

## Setup

1. Create a virtual environment and install dependencies.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. Create a top-level `.env` file.

Recommended variables:

- `SUPABASE_PAT`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`

Optional YouTube fallback variables:

- `YOUTUBE_OAUTH_CLIENT_SECRETS_JSON`
- `YOUTUBE_OAUTH_TOKEN_JSON`

3. Create a Google Cloud OAuth desktop client and place account files under `secrets/youtube/`.

Examples:

- `secrets/youtube/yt-secret.json`


4. Apply the Supabase schema in [schema.sql](C:\DDrive\Programming\Project\misc\The New Chhayageet\supabase\schema.sql).

5. Copy and customize [profile.json](C:\DDrive\Programming\Project\misc\The New Chhayageet\config\profile.json).

6. Sync the listener profile into Supabase.

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli sync-profile --profile config/profile.json
```

7. Sync runtime guidance into Supabase.

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli sync-config --config-key default --youtube-account yt --songs-per-playlist 12 --playlist-prefix Chaayageet
```

8. Authenticate the target YouTube account.

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli auth-youtube --config-key default --force
```

9. Run the weekly curation.

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli run-weekly --profile-id default --config-key default --verbose
```

## Commands

Sync profile:

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli sync-profile --profile config/profile.json
```

Sync guidance:

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli sync-config --config-key default --youtube-account yt --songs-per-playlist 12 --playlist-prefix Chaayageet
```

Force YouTube re-auth:

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli auth-youtube --config-key default --force
```

Run curation:

```powershell
.\.venv\Scripts\python.exe -m chhayageet.cli run-weekly --profile-id default --config-key default --verbose
```

## Selection Rules

Current rules include:

- reject videos already curated in prior runs
- reject excluded keywords such as `remix`, `lofi`, and `shorts`
- reject videos longer than 8 minutes
- boost preferred artists and eras
- limit repeated artists, eras, and query buckets in the final set
- sync the playlist so removed candidates are also removed from YouTube

## Repository Notes

- Sensitive files should stay under `secrets/` or `.env` and are ignored by git.
- The YouTube API manages playlists, not YouTube Music library folders.
- First-time YouTube auth opens a browser window.
- The app supports multiple YouTube accounts through the `youtube_account` guidance key.
