from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class VideoCandidate:
    video_id: str
    title: str
    channel_title: str
    description: str
    published_at: str
    query: str
    duration_seconds: int = 0
    score: float = 0.0
    inferred_artist: str = ""
    inferred_era: str = ""
    rejection_reasons: list[str] = field(default_factory=list)
