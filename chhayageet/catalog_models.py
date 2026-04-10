from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CatalogCandidate:
    song_uuid: str
    album_uuid: str
    song_title: str
    song_singers: str
    song_rating: float
    youtube_url: str
    youtube_video_id: str
    album_title: str
    album_year: int | None
    album_music_director: str
    album_rating: float
    score: float = 0.0
    validation_status: str = "unchecked"

    @property
    def playlist_title(self) -> str:
        parts = [self.song_title]
        if self.album_title:
            parts.append(self.album_title)
        if self.song_singers:
            parts.append(self.song_singers)
        return " | ".join(parts)
