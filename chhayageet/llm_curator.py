from __future__ import annotations

import json
import re
from os import environ
from typing import Any

import requests

from chhayageet.config import ListenerProfile
from chhayageet.env import load_environment
from chhayageet.models import VideoCandidate


class LLMCurator:
    def __init__(self, preferred_model: str = "none", timeout_seconds: int = 45) -> None:
        load_environment()
        self.preferred_model = preferred_model.strip() if preferred_model else "none"
        self.timeout_seconds = timeout_seconds
        self.provider, self.model = self._parse_model(self.preferred_model)

    @property
    def enabled(self) -> bool:
        return self.provider not in {"", "none"} and self.model != ""

    def expand_queries(self, profile: ListenerProfile) -> list[str]:
        if not self.enabled:
            return list(profile.include_queries)

        prompt = {
            "task": "Generate YouTube search queries for a weekly Hindi music playlist.",
            "rules": [
                "Return JSON only.",
                "Use queries that are likely to find individual songs, not long jukeboxes or compilations.",
                "Prefer Hindi film songs and ghazals that match the listener profile.",
                "Avoid remix, lofi, slowed, reverb, shorts, and playlist-style query terms.",
                "Return 8 to 12 concise queries.",
            ],
            "listener_profile": profile.to_dict(),
            "response_schema": {"queries": ["string"]},
        }
        payload = self._complete_json(prompt)
        queries = payload.get("queries", []) if isinstance(payload, dict) else []
        cleaned = [query.strip() for query in queries if isinstance(query, str) and query.strip()]
        return cleaned or list(profile.include_queries)

    def rerank_candidates(
        self,
        profile: ListenerProfile,
        candidates: list[VideoCandidate],
        limit: int,
    ) -> dict[str, float]:
        if not self.enabled:
            return {}

        eligible = [candidate for candidate in candidates if candidate.score >= 0]
        if not eligible:
            return {}

        prompt_candidates = [
            {
                "video_id": item.video_id,
                "title": item.title,
                "channel_title": item.channel_title,
                "query": item.query,
                "duration_seconds": item.duration_seconds,
                "current_score": round(item.score, 2),
                "inferred_artist": item.inferred_artist,
                "inferred_era": item.inferred_era,
            }
            for item in eligible[: min(len(eligible), max(limit * 4, 30))]
        ]
        prompt = {
            "task": "Score verified YouTube candidates for a Hindi playlist.",
            "rules": [
                "Return JSON only.",
                "Only score video_id values present in candidates.",
                "Prefer individual song videos under 8 minutes.",
                "Penalize jukeboxes, full albums, compilations, live streams, covers, tribute uploads, remixes, lofi, slowed, reverb, and non-Hindi mismatches.",
                "Score each candidate from -5 to 5 where 5 is an excellent fit.",
            ],
            "listener_profile": profile.to_dict(),
            "candidates": prompt_candidates,
            "response_schema": {"scores": [{"video_id": "string", "score_adjustment": 0}]},
        }
        payload = self._complete_json(prompt)
        scores = payload.get("scores", []) if isinstance(payload, dict) else []
        adjustments: dict[str, float] = {}
        allowed_ids = {item["video_id"] for item in prompt_candidates}
        for item in scores:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("video_id", "")).strip()
            if video_id not in allowed_ids:
                continue
            try:
                score = float(item.get("score_adjustment", 0))
            except (TypeError, ValueError):
                continue
            adjustments[video_id] = max(-5.0, min(5.0, score))
        return adjustments

    def explain_selection(self, title: str, query: str) -> str:
        return f"Selected from query '{query}' because it fits the requested Hindi mood mix."

    def _parse_model(self, value: str) -> tuple[str, str]:
        if not value or value.lower() == "none":
            return "none", ""
        if ":" not in value:
            return "openai", value
        provider, model = value.split(":", 1)
        normalized_provider = provider.strip().lower()
        if normalized_provider == "anthropic":
            normalized_provider = "claude"
        if normalized_provider == "google":
            normalized_provider = "gemini"
        return normalized_provider, model.strip()

    def _complete_json(self, prompt: dict[str, Any]) -> dict[str, Any]:
        system = "You are a careful Hindi music curator. Return strict JSON only."
        user_prompt = json.dumps(prompt, ensure_ascii=False)
        try:
            if self.provider == "openai":
                text = self._call_openai(system, user_prompt)
            elif self.provider == "claude":
                text = self._call_claude(system, user_prompt)
            elif self.provider == "gemini":
                text = self._call_gemini(system, user_prompt)
            elif self.provider == "ollama":
                text = self._call_ollama(system, user_prompt)
            else:
                return {}
        except requests.RequestException:
            return {}

        return self._parse_json_text(text)

    def _call_openai(self, system: str, prompt: str) -> str:
        api_key = environ.get("OPENAI_API_KEY")
        if not api_key:
            return "{}"
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "instructions": system,
                "input": prompt,
                "max_output_tokens": 1800,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("output_text"):
            return str(payload["output_text"])
        texts: list[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    texts.append(str(content["text"]))
        return "\n".join(texts)

    def _call_claude(self, system: str, prompt: str) -> str:
        api_key = environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return "{}"
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 1800,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return "\n".join(
            str(item.get("text", ""))
            for item in payload.get("content", [])
            if item.get("type") == "text"
        )

    def _call_gemini(self, system: str, prompt: str) -> str:
        api_key = environ.get("GEMINI_API_KEY") or environ.get("GOOGLE_API_KEY")
        if not api_key:
            return "{}"
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            params={"key": api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": 1800,
                },
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "\n".join(str(part.get("text", "")) for part in parts)

    def _call_ollama(self, system: str, prompt: str) -> str:
        base_url = environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": f"{system}\n\n{prompt}",
                "stream": False,
                "format": "json",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return str(response.json().get("response", ""))

    def _parse_json_text(self, text: str) -> dict[str, Any]:
        if not text:
            return {}
        try:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
