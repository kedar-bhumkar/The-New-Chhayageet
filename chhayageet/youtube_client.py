from __future__ import annotations

import json
import pickle
import re
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from chhayageet.env import env_path, load_environment
from chhayageet.models import VideoCandidate

SCOPES = ["https://www.googleapis.com/auth/youtube"]
ISO_8601_DURATION = re.compile(
    r"^P(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)$"
)


class YouTubeClient:
    def __init__(
        self,
        credentials_path: str | Path | None = None,
        token_path: str | Path | None = None,
        *,
        youtube_account: str | None = None,
        force_reauth: bool = False,
    ) -> None:
        load_environment()
        self.credentials_path, self.token_path = self._resolve_auth_paths(
            credentials_path,
            token_path,
            youtube_account,
        )
        self.force_reauth = force_reauth
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.service = build("youtube", "v3", credentials=self._load_credentials())

    def _resolve_auth_paths(
        self,
        credentials_path: str | Path | None,
        token_path: str | Path | None,
        youtube_account: str | None,
    ) -> tuple[Path, Path]:
        credentials = None
        token = None
        if youtube_account:
            credentials = env_path(
                f"YOUTUBE_{youtube_account.upper()}_CLIENT_SECRETS_JSON",
                f"secrets/youtube/{youtube_account}-secret.json",
            )
            token = env_path(
                f"YOUTUBE_{youtube_account.upper()}_TOKEN_JSON",
                f"secrets/youtube/{youtube_account}-token.pickle",
            )
        if credentials_path:
            credentials = Path(credentials_path)
        if token_path:
            token = Path(token_path)
        if credentials is None:
            credentials = env_path("YOUTUBE_OAUTH_CLIENT_SECRETS_JSON")
        if token is None:
            token = env_path("YOUTUBE_OAUTH_TOKEN_JSON")
        if credentials is None or token is None:
            raise ValueError(
                "YouTube OAuth paths are required. Set YOUTUBE_OAUTH_CLIENT_SECRETS_JSON and YOUTUBE_OAUTH_TOKEN_JSON."
            )
        if not credentials.is_absolute():
            credentials = Path.cwd() / credentials
        if not token.is_absolute():
            token = Path.cwd() / token

        credentials_name = credentials.name.lower()
        token_name = token.name.lower()
        if credentials.suffix == ".pickle" and token.suffix == ".json":
            if "token" in credentials_name and "secret" in token_name:
                credentials, token = token, credentials
        return credentials, token

    def _load_credentials(self) -> Credentials:
        creds = None
        if self.token_path.exists() and not self.force_reauth:
            creds = self._read_token_file(self.token_path)
            if creds and not creds.has_scopes(SCOPES):
                creds = None

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), SCOPES)
            creds = flow.run_local_server(
                port=0,
                authorization_prompt_message="Authorize The New Chhayageet for YouTube playlist management.",
                prompt="consent",
                access_type="offline",
            )
            self._write_token_file(self.token_path, creds)

        return creds

    def _read_token_file(self, path: Path) -> Credentials | None:
        if path.suffix == ".pickle":
            with path.open("rb") as handle:
                payload = pickle.load(handle)
            if isinstance(payload, Credentials):
                return payload
            return None

        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if "refresh_token" not in payload and "token" not in payload:
            return None
        return Credentials.from_authorized_user_info(payload, SCOPES)

    def _write_token_file(self, path: Path, creds: Credentials) -> None:
        if path.suffix == ".pickle":
            with path.open("wb") as handle:
                pickle.dump(creds, handle)
            return
        path.write_text(creds.to_json(), encoding="utf-8")

    def search_videos(
        self,
        query: str,
        *,
        max_results: int,
        region_code: str,
    ) -> list[VideoCandidate]:
        response = (
            self.service.search()
            .list(
                part="snippet",
                q=query,
                type="video",
                videoCategoryId="10",
                maxResults=max_results,
                regionCode=region_code,
                relevanceLanguage="hi",
                safeSearch="none",
            )
            .execute()
        )

        durations = self._video_durations(
            [item["id"]["videoId"] for item in response.get("items", []) if item.get("id", {}).get("videoId")]
        )

        candidates: list[VideoCandidate] = []
        for item in response.get("items", []):
            snippet = item["snippet"]
            video_id = item["id"]["videoId"]
            candidates.append(
                VideoCandidate(
                    video_id=video_id,
                    title=snippet["title"],
                    channel_title=snippet["channelTitle"],
                    description=snippet.get("description", ""),
                    published_at=snippet["publishedAt"],
                    query=query,
                    duration_seconds=durations.get(video_id, 0),
                )
            )
        return candidates

    def _video_durations(self, video_ids: list[str]) -> dict[str, int]:
        if not video_ids:
            return {}

        durations: dict[str, int] = {}
        for start in range(0, len(video_ids), 50):
            chunk = video_ids[start : start + 50]
            response = (
                self.service.videos()
                .list(
                    part="contentDetails",
                    id=",".join(chunk),
                    maxResults=len(chunk),
                )
                .execute()
            )
            for item in response.get("items", []):
                duration_text = item.get("contentDetails", {}).get("duration", "PT0S")
                durations[item["id"]] = self._parse_duration_seconds(duration_text)
        return durations

    def _parse_duration_seconds(self, value: str) -> int:
        match = ISO_8601_DURATION.match(value)
        if not match:
            return 0
        hours = int(match.group("hours") or 0)
        minutes = int(match.group("minutes") or 0)
        seconds = int(match.group("seconds") or 0)
        return hours * 3600 + minutes * 60 + seconds

    def find_playlist_by_title(self, title: str) -> str | None:
        request = self.service.playlists().list(part="snippet", mine=True, maxResults=50)
        while request is not None:
            response = request.execute()
            for item in response.get("items", []):
                if item["snippet"]["title"] == title:
                    return item["id"]
            request = self.service.playlists().list_next(request, response)
        return None

    def create_playlist(self, title: str, description: str) -> str:
        response = (
            self.service.playlists()
            .insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": title,
                        "description": description,
                    },
                    "status": {"privacyStatus": "private"},
                },
            )
            .execute()
        )
        return response["id"]

    def ensure_playlist(self, title: str, description: str) -> str:
        existing = self.find_playlist_by_title(title)
        if existing:
            return existing
        return self.create_playlist(title, description)

    def playlist_item_video_ids(self, playlist_id: str) -> set[str]:
        video_ids: set[str] = set()
        request = self.service.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
        )
        while request is not None:
            response = request.execute()
            for item in response.get("items", []):
                details = item.get("contentDetails", {})
                video_id = details.get("videoId")
                if video_id:
                    video_ids.add(video_id)
            request = self.service.playlistItems().list_next(request, response)
        return video_ids

    def playlist_items(self, playlist_id: str) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        request = self.service.playlistItems().list(
            part="id,contentDetails,snippet",
            playlistId=playlist_id,
            maxResults=50,
        )
        while request is not None:
            response = request.execute()
            for item in response.get("items", []):
                video_id = item.get("contentDetails", {}).get("videoId")
                if not video_id:
                    continue
                items.append(
                    {
                        "playlist_item_id": item["id"],
                        "video_id": video_id,
                        "title": item.get("snippet", {}).get("title", ""),
                    }
                )
            request = self.service.playlistItems().list_next(request, response)
        return items

    def add_videos_to_playlist(self, playlist_id: str, video_ids: list[str]) -> dict[str, list[str]]:
        existing_ids = self.playlist_item_video_ids(playlist_id)
        added: list[str] = []
        skipped_existing: list[str] = []
        for video_id in video_ids:
            if video_id in existing_ids:
                skipped_existing.append(video_id)
                continue
            (
                self.service.playlistItems()
                .insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": video_id,
                            },
                        }
                    },
                )
                .execute()
            )
            added.append(video_id)
        return {
            "added": added,
            "skipped_existing": skipped_existing,
        }

    def sync_playlist_videos(self, playlist_id: str, desired_video_ids: list[str]) -> dict[str, list[str]]:
        desired_set = set(desired_video_ids)
        existing_items = self.playlist_items(playlist_id)
        existing_ids = {item["video_id"] for item in existing_items}

        removed: list[str] = []
        kept: list[str] = []
        for item in existing_items:
            if item["video_id"] in desired_set:
                kept.append(item["video_id"])
                continue
            self.service.playlistItems().delete(id=item["playlist_item_id"]).execute()
            removed.append(item["video_id"])

        added: list[str] = []
        for video_id in desired_video_ids:
            if video_id in existing_ids:
                continue
            (
                self.service.playlistItems()
                .insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": video_id,
                            },
                        }
                    },
                )
                .execute()
            )
            added.append(video_id)

        return {
            "added": added,
            "removed": removed,
            "kept": kept,
        }

    def channel_title(self) -> str:
        try:
            response: dict[str, Any] = (
                self.service.channels().list(part="snippet", mine=True).execute()
            )
        except HttpError as exc:
            if exc.resp.status == 403 and b"insufficientPermissions" in exc.content:
                raise RuntimeError(
                    "The saved YouTube token does not have the required scope. Run 'python -m chhayageet.cli auth-youtube --force' to refresh it."
                ) from exc
            raise
        items = response.get("items", [])
        if not items:
            return "Unknown channel"
        return items[0]["snippet"]["title"]

    def authenticate(self) -> str:
        return self.channel_title()
