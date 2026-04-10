from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def extract_youtube_video_id(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")

    if host == "youtu.be":
        return parsed.path.strip("/")

    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [""])[0]
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/", 2)[2]
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/", 2)[2]

    return ""
