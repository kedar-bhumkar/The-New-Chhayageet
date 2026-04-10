from __future__ import annotations

import random
from datetime import datetime, timezone

from chhayageet.catalog_models import CatalogCandidate
from chhayageet.config import GuidanceConfig, ListenerProfile
from chhayageet.history_store import HistoryStore


class CatalogStore:
    TARGET_DECADES = (1950, 1960, 1970, 1980, 1990)
    DEVOTIONAL_KEYWORDS = (
        "bhajan",
        "devotional",
        "aarti",
        "aartis",
        "mantra",
        "chalisa",
        "stotram",
        "stotra",
        "kirtan",
        "kirtans",
        "krishna",
        "radhe",
        "radheshyam",
        "ram ",
        "rama ",
        "shyam",
        "shiv",
        "shiva",
        "mahadev",
        "bholenath",
        "bhole",
        "hanuman",
        "ganesha",
        "ganpati",
        "sai",
        "prabhu",
        "hari hari",
        "bhangiya",
        "booti",
        "maa durga",
        "mata",
        "ambe",
        "jai jai ram",
        "hare rama",
        "hare krishna",
    )

    def __init__(self, history: HistoryStore) -> None:
        self.history = history

    def fetch_candidates(
        self,
        guidance: GuidanceConfig,
        profile: ListenerProfile,
        *,
        fetch_limit: int = 5000,
    ) -> list[CatalogCandidate]:
        if guidance.mode.lower().strip() == "user-driven":
            songs, albums = self._fetch_user_driven_rows(max(fetch_limit, guidance.candidate_pool_size * 80))
        else:
            songs = self._fetch_unused_song_sample(fetch_limit)
            album_ids = sorted({row["album_uuid"] for row in songs if row.get("album_uuid")})
            albums = self._fetch_albums(album_ids)

        candidates = [
            self._candidate_from_rows(song, albums.get(song.get("album_uuid"), {}))
            for song in songs
        ]
        filtered = self._filter_candidates(candidates, guidance, profile)
        if guidance.mode.lower().strip() == "user-driven":
            return self._balanced_candidate_pool(filtered, guidance.candidate_pool_size)
        random.shuffle(filtered)
        return filtered[: guidance.candidate_pool_size]

    def _fetch_unused_song_sample(self, fetch_limit: int) -> list[dict]:
        count_response = (
            self.history.client.table("songs")
            .select("song_uuid", count="exact")
            .eq("is_used", False)
            .not_.is_("youtube_url", "null")
            .neq("youtube_url", "")
            .limit(1)
            .execute()
        )
        total = int(count_response.count or 0)
        if total == 0:
            return []

        page_size = min(1000, fetch_limit)
        pages_needed = max(1, min(20, (fetch_limit + page_size - 1) // page_size))
        rows_by_id: dict[str, dict] = {}
        for _ in range(pages_needed):
            max_offset = max(total - page_size, 0)
            offset = random.randint(0, max_offset) if max_offset else 0
            response = (
                self.history.client.table("songs")
                .select("*")
                .eq("is_used", False)
                .not_.is_("youtube_url", "null")
                .neq("youtube_url", "")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            for row in response.data or []:
                if row.get("song_uuid"):
                    rows_by_id[row["song_uuid"]] = row
            if len(rows_by_id) >= fetch_limit:
                break

        songs = list(rows_by_id.values())
        random.shuffle(songs)
        return songs[:fetch_limit]

    def _fetch_user_driven_rows(self, fetch_limit: int) -> tuple[list[dict], dict[str, dict]]:
        per_decade_target = max(fetch_limit // len(self.TARGET_DECADES), 1)
        songs_by_id: dict[str, dict] = {}
        albums_by_id: dict[str, dict] = {}

        for decade in self.TARGET_DECADES:
            albums = self._fetch_albums_for_decade(decade)
            if not albums:
                continue
            album_items = list(albums.items())
            random.shuffle(album_items)

            decade_rows: dict[str, dict] = {}
            for start in range(0, len(album_items), 150):
                chunk = album_items[start : start + 150]
                chunk_ids = [album_id for album_id, _ in chunk]
                response = (
                    self.history.client.table("songs")
                    .select("*")
                    .eq("is_used", False)
                    .not_.is_("youtube_url", "null")
                    .neq("youtube_url", "")
                    .in_("album_uuid", chunk_ids)
                    .execute()
                )
                for row in response.data or []:
                    song_uuid = row.get("song_uuid")
                    if song_uuid:
                        decade_rows[song_uuid] = row
                if len(decade_rows) >= per_decade_target:
                    break

            decade_song_rows = list(decade_rows.values())
            random.shuffle(decade_song_rows)
            for row in decade_song_rows[:per_decade_target]:
                song_uuid = row.get("song_uuid")
                album_uuid = row.get("album_uuid")
                if not song_uuid or not album_uuid:
                    continue
                songs_by_id[song_uuid] = row
                if album_uuid in albums:
                    albums_by_id[album_uuid] = albums[album_uuid]

        songs = list(songs_by_id.values())
        random.shuffle(songs)
        return songs, albums_by_id

    def _fetch_albums_for_decade(self, decade: int) -> dict[str, dict]:
        response = (
            self.history.client.table("albums")
            .select("*")
            .gte("album_year", decade)
            .lte("album_year", decade + 9)
            .execute()
        )
        return {row["album_uuid"]: row for row in response.data or [] if row.get("album_uuid")}

    def _balanced_candidate_pool(self, candidates: list[CatalogCandidate], limit: int) -> list[CatalogCandidate]:
        by_decade: dict[int, list[CatalogCandidate]] = {decade: [] for decade in self.TARGET_DECADES}
        remainder: list[CatalogCandidate] = []

        for item in candidates:
            decade = self._decade_from_year(item.album_year)
            if decade in by_decade:
                by_decade[decade].append(item)
            else:
                remainder.append(item)

        for bucket in by_decade.values():
            random.shuffle(bucket)
        random.shuffle(remainder)

        selected: list[CatalogCandidate] = []
        base_target = max(1, limit // len(self.TARGET_DECADES))
        for decade in self.TARGET_DECADES:
            bucket = by_decade[decade]
            take = min(base_target, len(bucket))
            selected.extend(bucket[:take])
            by_decade[decade] = bucket[take:]

        remaining_pool: list[CatalogCandidate] = []
        for decade in self.TARGET_DECADES:
            remaining_pool.extend(by_decade[decade])
        remaining_pool.extend(remainder)
        random.shuffle(remaining_pool)

        for item in remaining_pool:
            if len(selected) >= limit:
                break
            selected.append(item)

        random.shuffle(selected)
        return selected[:limit]

    def fetch_selected_for_playlist(self, playlist_title: str) -> list[CatalogCandidate]:
        response = (
            self.history.client.table("curated_videos")
            .select("song_uuid")
            .eq("playlist_title", playlist_title)
            .eq("source", "catalog")
            .execute()
        )
        song_ids = [row["song_uuid"] for row in response.data or [] if row.get("song_uuid")]
        if not song_ids:
            return []

        songs_response = (
            self.history.client.table("songs")
            .select("*")
            .in_("song_uuid", song_ids)
            .execute()
        )
        songs = songs_response.data or []
        albums = self._fetch_albums([row["album_uuid"] for row in songs if row.get("album_uuid")])
        candidates = [
            self._candidate_from_rows(song, albums.get(song.get("album_uuid"), {}))
            for song in songs
        ]
        order = {song_id: index for index, song_id in enumerate(song_ids)}
        return sorted(candidates, key=lambda item: order.get(item.song_uuid, 0))

    def mark_used(
        self,
        selected: list[CatalogCandidate],
        *,
        playlist_title: str,
        playlist_id: str,
    ) -> None:
        used_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "song_uuid": item.song_uuid,
                "is_used": True,
                "used_at": used_at,
                "used_playlist_title": playlist_title,
                "used_playlist_id": playlist_id,
            }
            for item in selected
        ]
        for row in rows:
            self.history.client.table("songs").update(row).eq("song_uuid", row["song_uuid"]).execute()

    def record_catalog_run(
        self,
        *,
        playlist_title: str,
        playlist_id: str,
        total_candidates: int,
        selected: list[CatalogCandidate],
    ) -> None:
        curated_at = datetime.now(timezone.utc).isoformat()
        self.history.client.table("curated_videos").delete().eq("playlist_title", playlist_title).eq(
            "source",
            "catalog",
        ).execute()

        self.history.client.table("curation_runs").insert(
            {
                "playlist_title": playlist_title,
                "curated_at": curated_at,
                "total_candidates": total_candidates,
                "selected_count": len(selected),
            }
        ).execute()

        rows = [
            {
                "video_id": item.youtube_video_id,
                "title": item.song_title,
                "channel_title": "catalog",
                "inferred_artist": item.song_singers,
                "inferred_era": self._era_from_year(item.album_year),
                "query": "catalog",
                "playlist_title": playlist_title,
                "curated_at": curated_at,
                "song_uuid": item.song_uuid,
                "album_uuid": item.album_uuid,
                "youtube_url": item.youtube_url,
                "source": "catalog",
            }
            for item in selected
        ]
        if rows:
            self.history.client.table("curated_videos").upsert(rows, on_conflict="video_id").execute()

    def _fetch_albums(self, album_ids: list[str]) -> dict[str, dict]:
        albums: dict[str, dict] = {}
        for start in range(0, len(album_ids), 500):
            chunk = album_ids[start : start + 500]
            if not chunk:
                continue
            response = (
                self.history.client.table("albums")
                .select("*")
                .in_("album_uuid", chunk)
                .execute()
            )
            for row in response.data or []:
                albums[row["album_uuid"]] = row
        return albums

    def _candidate_from_rows(self, song: dict, album: dict) -> CatalogCandidate:
        return CatalogCandidate(
            song_uuid=song.get("song_uuid") or "",
            album_uuid=song.get("album_uuid") or "",
            song_title=song.get("song_title") or "",
            song_singers=song.get("song_singers") or "",
            song_rating=float(song.get("song_rating") or 0),
            youtube_url=song.get("youtube_url") or "",
            youtube_video_id=song.get("youtube_video_id") or "",
            album_title=album.get("album_title") or "",
            album_year=album.get("album_year"),
            album_music_director=album.get("album_music_director") or "",
            album_rating=float(album.get("album_rating") or 0),
        )

    def _filter_candidates(
        self,
        candidates: list[CatalogCandidate],
        guidance: GuidanceConfig,
        profile: ListenerProfile,
    ) -> list[CatalogCandidate]:
        base_candidates = [item for item in candidates if not self._is_devotional(item)]
        mode = guidance.mode.lower().strip()
        if mode == "random":
            return base_candidates

        singers = guidance.preferred_singers or profile.preferred_artists
        music_directors = guidance.preferred_music_directors or []
        filtered = []
        for item in base_candidates:
            if guidance.year_min is not None and item.album_year is not None and item.album_year < guidance.year_min:
                continue
            if guidance.year_max is not None and item.album_year is not None and item.album_year > guidance.year_max:
                continue
            if guidance.min_song_rating is not None and item.song_rating < guidance.min_song_rating:
                continue
            if guidance.min_album_rating is not None and item.album_rating < guidance.min_album_rating:
                continue
            if singers and not self._contains_any(item.song_singers, singers):
                continue
            if music_directors and not self._contains_any(item.album_music_director, music_directors):
                continue
            filtered.append(item)
        return filtered

    def _contains_any(self, value: str, needles: list[str]) -> bool:
        text = value.lower()
        return any(needle.lower() in text for needle in needles)

    def _is_devotional(self, item: CatalogCandidate) -> bool:
        haystacks = [
            item.song_title.lower(),
            item.album_title.lower(),
            item.song_singers.lower(),
        ]
        return any(keyword in haystack for keyword in self.DEVOTIONAL_KEYWORDS for haystack in haystacks)

    def _decade_from_year(self, year: int | None) -> int | None:
        if not year:
            return None
        decade = year - (year % 10)
        if decade not in self.TARGET_DECADES:
            return None
        return decade

    def _era_from_year(self, year: int | None) -> str:
        if not year:
            return ""
        decade = year - (year % 10)
        return f"{decade}s"
