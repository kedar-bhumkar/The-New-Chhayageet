from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from os import environ

from supabase import Client, create_client

from chhayageet.config import GuidanceConfig, ListenerProfile
from chhayageet.env import load_environment
from chhayageet.models import VideoCandidate


class HistoryStore:
    def __init__(self, supabase_url: str | None = None, supabase_key: str | None = None) -> None:
        load_environment()
        url = supabase_url or environ.get("SUPABASE_URL")
        key = (
            supabase_key
            or environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or environ.get("SUPABASE_KEY")
            or environ.get("SUPABASE_ANON_KEY")
        )
        if not url or not key:
            raise ValueError(
                "SUPABASE_URL and one of SUPABASE_SERVICE_ROLE_KEY, SUPABASE_KEY, or SUPABASE_ANON_KEY must be set."
            )
        self.client: Client = create_client(url, key)

    def has_video(self, video_id: str) -> bool:
        response = (
            self.client.table("curated_videos")
            .select("video_id")
            .eq("video_id", video_id)
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def get_profile(self, profile_id: str) -> ListenerProfile:
        response = (
            self.client.table("listener_profiles")
            .select("*")
            .eq("profile_id", profile_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            raise ValueError(f"Profile '{profile_id}' was not found in Supabase.")
        return ListenerProfile.from_dict(response.data[0])

    def get_guidance(self, config_key: str = "default") -> GuidanceConfig:
        response = (
            self.client.table("config")
            .select("*")
            .eq("config_key", config_key)
            .limit(1)
            .execute()
        )
        if not response.data:
            raise ValueError(f"Config '{config_key}' was not found in Supabase.")
        return GuidanceConfig.from_dict(response.data[0])

    def upsert_profile(self, profile: ListenerProfile) -> None:
        row = profile.to_dict()
        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.client.table("listener_profiles").upsert(row, on_conflict="profile_id").execute()

    def upsert_guidance(self, guidance: GuidanceConfig, config_key: str = "default") -> None:
        row = guidance.to_row(config_key=config_key)
        self.client.table("config").upsert(row, on_conflict="config_key").execute()

    def recent_artist_counts(self, limit: int = 100) -> dict[str, int]:
        response = (
            self.client.table("curated_videos")
            .select("inferred_artist, curated_at")
            .not_.is_("inferred_artist", "null")
            .neq("inferred_artist", "")
            .order("curated_at", desc=True)
            .limit(limit)
            .execute()
        )
        counts = Counter(row["inferred_artist"] for row in response.data if row.get("inferred_artist"))
        return dict(counts)

    def recent_era_counts(self, limit: int = 100) -> dict[str, int]:
        response = (
            self.client.table("curated_videos")
            .select("inferred_era, curated_at")
            .not_.is_("inferred_era", "null")
            .neq("inferred_era", "")
            .order("curated_at", desc=True)
            .limit(limit)
            .execute()
        )
        counts = Counter(row["inferred_era"] for row in response.data if row.get("inferred_era"))
        return dict(counts)

    def record_run(
        self,
        playlist_title: str,
        curated_at: str,
        total_candidates: int,
        selected: list[VideoCandidate],
    ) -> None:
        self.client.table("curation_runs").insert(
            {
                "playlist_title": playlist_title,
                "curated_at": curated_at,
                "total_candidates": total_candidates,
                "selected_count": len(selected),
            }
        ).execute()

        rows = [
            {
                "video_id": item.video_id,
                "title": item.title,
                "channel_title": item.channel_title,
                "inferred_artist": item.inferred_artist or None,
                "inferred_era": item.inferred_era or None,
                "query": item.query,
                "playlist_title": playlist_title,
                "curated_at": curated_at,
            }
            for item in selected
        ]
        if rows:
            self.client.table("curated_videos").upsert(rows, on_conflict="video_id").execute()

    def close(self) -> None:
        return None
