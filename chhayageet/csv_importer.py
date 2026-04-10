from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from chhayageet.history_store import HistoryStore
from chhayageet.youtube_url import extract_youtube_video_id


class CatalogCsvImporter:
    def __init__(self, history: HistoryStore, batch_size: int = 500) -> None:
        self.history = history
        self.batch_size = batch_size

    def import_catalog(self, albums_dir: str | Path, songs_dir: str | Path) -> dict[str, int]:
        album_rows = self._dedupe_by_key(list(self._album_rows(Path(albums_dir))), "album_uuid")
        song_rows = self._dedupe_by_key(list(self._song_rows(Path(songs_dir))), "song_uuid")
        self._upsert_batches("albums", album_rows, "album_uuid")
        self._upsert_batches("songs", song_rows, "song_uuid")
        return {
            "albums": len(album_rows),
            "songs": len(song_rows),
        }

    def _album_rows(self, albums_dir: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(albums_dir.glob("*.csv")):
            for row in self._read_csv(path):
                rows.append(
                    {
                        "album_uuid": self._clean(row.get("album_uuid")),
                        "album_title": self._clean(row.get("album_title")),
                        "album_year": self._int(row.get("album_year")),
                        "album_category": self._clean(row.get("album_category")),
                        "album_music_director": self._clean(row.get("album_music_director")),
                        "album_lyricist": self._clean(row.get("album_lyricist")),
                        "album_label": self._clean(row.get("album_label")),
                        "album_rating": self._float(row.get("album_rating")),
                    }
                )
        return rows

    def _song_rows(self, songs_dir: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(songs_dir.glob("*.csv")):
            for row in self._read_csv(path):
                youtube_url = self._clean(row.get("youtube_url"))
                rows.append(
                    {
                        "song_uuid": self._clean(row.get("song_uuid")),
                        "album_uuid": self._clean(row.get("album_uuid")),
                        "track_number": self._int(row.get("track_number")),
                        "song_title": self._clean(row.get("song_title")),
                        "song_singers": self._clean(row.get("song_singers")),
                        "song_rating": self._float(row.get("song_rating")),
                        "youtube_url": youtube_url,
                        "music_yt_url_1": self._clean(row.get("music_yt_url_1")),
                        "music_yt_url_2": self._clean(row.get("music_yt_url_2")),
                        "music_yt_url_3": self._clean(row.get("music_yt_url_3")),
                        "youtube_video_id": extract_youtube_video_id(youtube_url),
                        "is_used": False,
                    }
                )
        return rows

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    def _upsert_batches(self, table: str, rows: list[dict[str, Any]], conflict_column: str) -> None:
        for start in range(0, len(rows), self.batch_size):
            chunk = rows[start : start + self.batch_size]
            if chunk:
                self.history.client.table(table).upsert(chunk, on_conflict=conflict_column).execute()

    def _dedupe_by_key(self, rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            value = row.get(key)
            if value:
                deduped[str(value)] = row
        return list(deduped.values())

    def _clean(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _int(self, value: Any) -> int | None:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _float(self, value: Any) -> float | None:
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None
