from __future__ import annotations

from collections import Counter
from datetime import datetime
from html import unescape

from chhayageet.config import ListenerProfile
from chhayageet.history_store import HistoryStore
from chhayageet.llm_curator import LLMCurator
from chhayageet.models import VideoCandidate
from chhayageet.youtube_client import YouTubeClient


class CurationEngine:
    MAX_DURATION_SECONDS = 8 * 60

    def __init__(
        self,
        profile: ListenerProfile,
        youtube: YouTubeClient,
        history: HistoryStore,
        llm_curator: LLMCurator | None = None,
    ) -> None:
        self.profile = profile
        self.youtube = youtube
        self.history = history
        self.llm_curator = llm_curator or LLMCurator()

    def build_queries(self) -> list[str]:
        use_llm = self.profile.use_llm or self.llm_curator.enabled
        queries = self.llm_curator.expand_queries(self.profile) if use_llm else list(self.profile.include_queries)
        deduped: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized = query.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(query.strip())
        return deduped

    def curate(self, *, dry_run: bool = False) -> dict[str, object]:
        playlist_date = datetime.now().date().isoformat()
        playlist_title = f"{self.profile.playlist_prefix} - {playlist_date}"
        playlist_description = self.profile.playlist_description
        playlist_id = ""
        if not dry_run:
            playlist_id = self.youtube.ensure_playlist(playlist_title, playlist_description)

        candidates = self._collect_candidates(playlist_title)
        selected = self._select_candidates(candidates, self.profile.songs_per_week)
        playlist_update = {
            "added": [],
            "removed": [],
            "kept": [],
        }
        if not dry_run:
            playlist_update = self.youtube.sync_playlist_videos(playlist_id, [item.video_id for item in selected])

        curated_at = datetime.now().isoformat(timespec="seconds")
        if not dry_run:
            self.history.record_run(
                playlist_title=playlist_title,
                curated_at=curated_at,
                total_candidates=len(candidates),
                selected=selected,
            )

        return {
            "playlist_title": playlist_title,
            "playlist_id": playlist_id,
            "selected_count": len(selected),
            "selected_titles": [item.title for item in selected],
            "channel_title": self.youtube.channel_title(),
            "dry_run": dry_run,
            "candidates": [self._serialize_candidate(item) for item in candidates],
            "selected": [self._serialize_candidate(item) for item in selected],
            "playlist_update": playlist_update,
        }

    def _serialize_candidate(self, candidate: VideoCandidate) -> dict[str, object]:
        return {
            "video_id": candidate.video_id,
            "title": candidate.title,
            "channel_title": candidate.channel_title,
            "query": candidate.query,
            "duration_seconds": candidate.duration_seconds,
            "score": round(candidate.score, 2),
            "artist": candidate.inferred_artist,
            "era": candidate.inferred_era,
            "rejection_reasons": list(candidate.rejection_reasons),
        }

    def _collect_candidates(self, playlist_title: str) -> list[VideoCandidate]:
        candidates: list[VideoCandidate] = []
        for query in self.build_queries():
            candidates.extend(
                self.youtube.search_videos(
                    query,
                    max_results=max(10, self.profile.songs_per_week * 2),
                    region_code=self.profile.country_code,
                )
            )

        unique_by_video: dict[str, VideoCandidate] = {}
        for item in candidates:
            unique_by_video.setdefault(item.video_id, item)

        enriched = [self._score_candidate(item, playlist_title) for item in unique_by_video.values()]
        self._apply_llm_rerank(enriched)
        return sorted(enriched, key=lambda item: item.score, reverse=True)

    def _apply_llm_rerank(self, candidates: list[VideoCandidate]) -> None:
        if not (self.profile.use_llm or self.llm_curator.enabled):
            return
        adjustments = self.llm_curator.rerank_candidates(
            self.profile,
            candidates,
            self.profile.songs_per_week,
        )
        for candidate in candidates:
            if candidate.score < 0:
                continue
            candidate.score += adjustments.get(candidate.video_id, 0.0)

    def _score_candidate(self, candidate: VideoCandidate, playlist_title: str) -> VideoCandidate:
        title = unescape(candidate.title).lower()
        description = unescape(candidate.description).lower()
        channel = candidate.channel_title.lower()
        full_text = " ".join([title, description, channel, candidate.query.lower()])

        score = 0.0
        candidate.inferred_artist = self._infer_artist(full_text)
        candidate.inferred_era = self._infer_era(full_text)

        if self.history.has_video_outside_playlist(candidate.video_id, playlist_title):
            candidate.rejection_reasons.append("already used")
            candidate.score = -100.0
            return candidate

        if candidate.duration_seconds > self.MAX_DURATION_SECONDS:
            candidate.rejection_reasons.append("longer than 8 minutes")
            candidate.score = -75.0
            return candidate

        if any(keyword.lower() in full_text for keyword in self.profile.exclude_keywords):
            candidate.rejection_reasons.append("excluded keyword")
            candidate.score = -50.0
            return candidate

        if self.profile.language_hint.lower() in full_text:
            score += 2.0

        if candidate.inferred_artist:
            score += 3.0

        if candidate.inferred_artist in self.profile.preferred_artists:
            score += 4.0

        if candidate.inferred_era:
            score += 2.0

        if candidate.inferred_era in self.profile.preferred_eras:
            score += 4.0

        if "official" in full_text or "audio" in full_text or "video song" in full_text:
            score += 1.5

        if "live" in full_text:
            score -= 1.5

        score += self._diversity_penalty(
            candidate.inferred_artist,
            candidate.inferred_era,
            playlist_title,
        )

        candidate.score = score
        return candidate

    def _diversity_penalty(self, artist: str, era: str, playlist_title: str) -> float:
        penalty = 0.0
        recent_artist_counts = self.history.recent_artist_counts(exclude_playlist_title=playlist_title)
        recent_era_counts = self.history.recent_era_counts(exclude_playlist_title=playlist_title)

        if artist:
            penalty -= recent_artist_counts.get(artist, 0) * 0.75
        if era:
            penalty -= recent_era_counts.get(era, 0) * 0.35
        return penalty

    def _select_candidates(self, candidates: list[VideoCandidate], limit: int) -> list[VideoCandidate]:
        selected: list[VideoCandidate] = []
        selected_artists: Counter[str] = Counter()
        selected_eras: Counter[str] = Counter()
        selected_queries: Counter[str] = Counter()

        for candidate in candidates:
            if candidate.score < 0:
                continue
            if candidate.inferred_artist and selected_artists[candidate.inferred_artist] >= 2:
                continue
            if candidate.inferred_era and selected_eras[candidate.inferred_era] >= 4:
                continue
            if selected_queries[candidate.query] >= 3:
                continue

            selected.append(candidate)
            if candidate.inferred_artist:
                selected_artists[candidate.inferred_artist] += 1
            if candidate.inferred_era:
                selected_eras[candidate.inferred_era] += 1
            selected_queries[candidate.query] += 1

            if len(selected) >= limit:
                break

        return selected

    def _infer_artist(self, full_text: str) -> str:
        for artist in self.profile.preferred_artists:
            if artist.lower() in full_text:
                return artist
        return ""

    def _infer_era(self, full_text: str) -> str:
        mappings = {
            "50s": ["195", "50s"],
            "60s": ["196", "60s"],
            "70s": ["197", "70s"],
            "80s": ["198", "80s"],
            "90s": ["199", "90s"],
            "2000s": ["200", "2000"],
            "golden era": ["golden era"],
        }
        for label, hints in mappings.items():
            if any(hint in full_text for hint in hints):
                return label
        return ""
