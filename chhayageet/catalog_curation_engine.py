from __future__ import annotations

import random
from collections import Counter
from datetime import datetime

from chhayageet.catalog_models import CatalogCandidate
from chhayageet.catalog_store import CatalogStore
from chhayageet.config import GuidanceConfig, ListenerProfile
from chhayageet.url_validator import YouTubeUrlValidator
from chhayageet.youtube_client import YouTubeClient


class CatalogCurationEngine:
    TARGET_DECADES = (1950, 1960, 1970, 1980, 1990)

    def __init__(
        self,
        profile: ListenerProfile,
        guidance: GuidanceConfig,
        catalog: CatalogStore,
        youtube: YouTubeClient,
        validator: YouTubeUrlValidator | None = None,
    ) -> None:
        self.profile = profile
        self.guidance = guidance
        self.catalog = catalog
        self.youtube = youtube
        self.validator = validator or YouTubeUrlValidator()

    def curate(self, *, dry_run: bool = False) -> dict[str, object]:
        playlist_date = datetime.now().date().isoformat()
        playlist_title = f"{self.guidance.playlist_name_prefix} - {playlist_date}"
        playlist_id = ""
        if not dry_run:
            playlist_id = self.youtube.ensure_playlist(playlist_title, self.profile.playlist_description)

        existing_selection = self.catalog.fetch_selected_for_playlist(playlist_title) if not dry_run else []
        if existing_selection:
            candidates = existing_selection
            live_candidates = existing_selection
            selected = existing_selection
        else:
            candidates = self.catalog.fetch_candidates(self.guidance, self.profile)
            live_candidates = self._live_candidates(candidates)
            selected = self._select(live_candidates, self.guidance.no_of_songs_per_playlist)

        playlist_update = {"added": [], "removed": [], "kept": []}
        if not dry_run:
            playlist_update = self.youtube.sync_playlist_videos(
                playlist_id,
                [item.youtube_video_id for item in selected],
            )
            self.catalog.mark_used(selected, playlist_title=playlist_title, playlist_id=playlist_id)
            self.catalog.record_catalog_run(
                playlist_title=playlist_title,
                playlist_id=playlist_id,
                total_candidates=len(candidates),
                selected=selected,
            )

        return {
            "mode": self.guidance.mode,
            "playlist_title": playlist_title,
            "playlist_id": playlist_id,
            "channel_title": self.youtube.channel_title(),
            "dry_run": dry_run,
            "candidate_count": len(candidates),
            "live_candidate_count": len(live_candidates),
            "selected_count": len(selected),
            "reused_existing_selection": bool(existing_selection),
            "candidates": [self._serialize(item) for item in candidates],
            "live_candidates": [self._serialize(item) for item in live_candidates],
            "selected": [self._serialize(item) for item in selected],
            "selected_titles": [item.playlist_title for item in selected],
            "playlist_update": playlist_update,
        }

    def _live_candidates(self, candidates: list[CatalogCandidate]) -> list[CatalogCandidate]:
        validation = self.validator.validate_many([item.youtube_url for item in candidates])
        live = []
        for item in candidates:
            is_live = validation.get(item.youtube_url, False)
            item.validation_status = "live" if is_live else "not_live"
            if is_live and item.youtube_video_id:
                live.append(item)
        return live

    def _select(self, candidates: list[CatalogCandidate], limit: int) -> list[CatalogCandidate]:
        scored = [self._score(item) for item in candidates]
        random.shuffle(scored)
        scored.sort(key=lambda item: item.score, reverse=True)

        selected: list[CatalogCandidate] = []
        singer_counts: Counter[str] = Counter()
        album_counts: Counter[str] = Counter()
        director_counts: Counter[str] = Counter()
        decade_counts: Counter[int] = Counter()

        if self.guidance.mode.lower().strip() == "user-driven":
            decade_targets = self._decade_targets(limit, scored)
            for decade in self.TARGET_DECADES:
                while decade_counts[decade] < decade_targets.get(decade, 0):
                    next_item = self._take_next_for_decade(
                        scored,
                        selected,
                        singer_counts,
                        album_counts,
                        director_counts,
                        decade,
                    )
                    if next_item is None:
                        break
                    selected.append(next_item)
                    self._record_selection(next_item, singer_counts, album_counts, director_counts, decade_counts)
                    if len(selected) >= limit:
                        return selected

        for item in scored:
            if item in selected:
                continue
            if not self._can_select(item, singer_counts, album_counts, director_counts):
                continue
            selected.append(item)
            self._record_selection(item, singer_counts, album_counts, director_counts, decade_counts)
            if len(selected) >= limit:
                break
        return selected

    def _take_next_for_decade(
        self,
        candidates: list[CatalogCandidate],
        selected: list[CatalogCandidate],
        singer_counts: Counter[str],
        album_counts: Counter[str],
        director_counts: Counter[str],
        decade: int,
    ) -> CatalogCandidate | None:
        for item in candidates:
            if item in selected:
                continue
            if self._decade_from_year(item.album_year) != decade:
                continue
            if not self._can_select(item, singer_counts, album_counts, director_counts):
                continue
            return item
        return None

    def _can_select(
        self,
        item: CatalogCandidate,
        singer_counts: Counter[str],
        album_counts: Counter[str],
        director_counts: Counter[str],
    ) -> bool:
        singer_key = item.song_singers.lower()
        director_key = item.album_music_director.lower()
        if singer_key and singer_counts[singer_key] >= 2:
            return False
        if item.album_uuid and album_counts[item.album_uuid] >= 1:
            return False
        if director_key and director_counts[director_key] >= 3:
            return False
        return True

    def _record_selection(
        self,
        item: CatalogCandidate,
        singer_counts: Counter[str],
        album_counts: Counter[str],
        director_counts: Counter[str],
        decade_counts: Counter[int],
    ) -> None:
        singer_key = item.song_singers.lower()
        director_key = item.album_music_director.lower()
        if singer_key:
            singer_counts[singer_key] += 1
        if item.album_uuid:
            album_counts[item.album_uuid] += 1
        if director_key:
            director_counts[director_key] += 1
        decade = self._decade_from_year(item.album_year)
        if decade is not None:
            decade_counts[decade] += 1

    def _decade_targets(self, limit: int, candidates: list[CatalogCandidate]) -> dict[int, int]:
        available = Counter(
            decade for decade in (self._decade_from_year(item.album_year) for item in candidates) if decade in self.TARGET_DECADES
        )
        targets = {decade: 0 for decade in self.TARGET_DECADES}
        remaining = limit

        for decade in self.TARGET_DECADES:
            if remaining <= 0:
                break
            if available[decade] > 0:
                targets[decade] = 1
                remaining -= 1

        priority_order = [1970, 1980, 1960, 1990, 1950]
        while remaining > 0:
            progressed = False
            for decade in priority_order:
                if remaining <= 0:
                    break
                if available[decade] <= targets[decade]:
                    continue
                targets[decade] += 1
                remaining -= 1
                progressed = True
            if not progressed:
                break
        return targets

    def _decade_from_year(self, year: int | None) -> int | None:
        if not year:
            return None
        decade = year - (year % 10)
        if decade not in self.TARGET_DECADES:
            return None
        return decade

    def _score(self, item: CatalogCandidate) -> CatalogCandidate:
        score = 0.0
        score += item.song_rating
        score += item.album_rating * 0.25
        preferred_artists = self.profile.preferred_artists
        preferred_music_directors = self.profile.preferred_music_directors
        if preferred_artists and self._contains_any(item.song_singers, preferred_artists):
            score += 3.0
        if preferred_music_directors and self._contains_any(
            item.album_music_director,
            preferred_music_directors,
        ):
            score += 2.0
        decade = self._decade_from_year(item.album_year)
        if decade == 1970:
            score += 1.0
        elif decade == 1960:
            score += 0.75
        elif decade == 1980:
            score += 0.75
        elif decade == 1990:
            score += 0.5
        elif decade == 1950:
            score += 0.5
        item.score = score
        return item

    def _contains_any(self, value: str, needles: list[str]) -> bool:
        text = value.lower()
        return any(needle.lower() in text for needle in needles)

    def _serialize(self, item: CatalogCandidate) -> dict[str, object]:
        return {
            "song_uuid": item.song_uuid,
            "album_uuid": item.album_uuid,
            "song_title": item.song_title,
            "song_singers": item.song_singers,
            "song_rating": item.song_rating,
            "youtube_url": item.youtube_url,
            "youtube_video_id": item.youtube_video_id,
            "album_title": item.album_title,
            "album_year": item.album_year,
            "album_music_director": item.album_music_director,
            "album_rating": item.album_rating,
            "score": round(item.score, 2),
            "validation_status": item.validation_status,
        }
