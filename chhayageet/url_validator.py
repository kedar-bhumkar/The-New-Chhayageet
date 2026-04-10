from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


class YouTubeUrlValidator:
    def __init__(self, timeout_seconds: int = 10, max_workers: int = 10) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_workers = max_workers

    def validate_many(self, urls: list[str]) -> dict[str, bool]:
        results: dict[str, bool] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_by_url = {executor.submit(self.is_live, url): url for url in urls}
            for future in as_completed(future_by_url):
                url = future_by_url[future]
                try:
                    results[url] = future.result()
                except requests.RequestException:
                    results[url] = False
        return results

    def is_live(self, url: str) -> bool:
        if not url:
            return False
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=self.timeout_seconds,
        )
        return response.status_code == 200
