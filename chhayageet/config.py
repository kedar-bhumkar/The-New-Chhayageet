from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class GuidanceConfig:
    youtube_account: str
    no_of_songs_per_playlist: int
    playlist_name_prefix: str
    preferred_model: str = "none"

    @classmethod
    def from_file(cls, path: str | Path) -> "GuidanceConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        guidance = payload.get("guidance", payload)
        guidance.setdefault("preferred_model", "none")
        return cls(**guidance)

    @classmethod
    def from_dict(cls, payload: dict) -> "GuidanceConfig":
        guidance = payload.get("guidance", payload)
        guidance.setdefault("preferred_model", "none")
        return cls(**guidance)

    def to_row(self, config_key: str = "default") -> dict:
        return {
            "config_key": config_key,
            "guidance": asdict(self),
        }


@dataclass(slots=True)
class ListenerProfile:
    profile_id: str
    listener_name: str
    playlist_prefix: str
    songs_per_week: int
    include_queries: list[str]
    exclude_keywords: list[str]
    preferred_artists: list[str]
    preferred_eras: list[str]
    preferred_moods: list[str]
    language_hint: str
    country_code: str
    playlist_description: str
    use_llm: bool = False

    @classmethod
    def from_file(cls, path: str | Path) -> "ListenerProfile":
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload.setdefault("profile_id", "default")
        return cls(**payload)

    @classmethod
    def from_dict(cls, payload: dict) -> "ListenerProfile":
        allowed_keys = {
            "profile_id",
            "listener_name",
            "playlist_prefix",
            "songs_per_week",
            "include_queries",
            "exclude_keywords",
            "preferred_artists",
            "preferred_eras",
            "preferred_moods",
            "language_hint",
            "country_code",
            "playlist_description",
            "use_llm",
        }
        shaped = {key: value for key, value in dict(payload).items() if key in allowed_keys}
        shaped.setdefault("profile_id", "default")
        return cls(**shaped)

    def to_dict(self) -> dict:
        return asdict(self)

    def apply_guidance(self, guidance: GuidanceConfig) -> "ListenerProfile":
        updated = self.to_dict()
        updated["songs_per_week"] = guidance.no_of_songs_per_playlist
        updated["playlist_prefix"] = guidance.playlist_name_prefix
        return ListenerProfile.from_dict(updated)
