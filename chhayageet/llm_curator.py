from __future__ import annotations

from chhayageet.config import ListenerProfile


class LLMCurator:
    """Optional LLM hook for future expansion."""

    def expand_queries(self, profile: ListenerProfile) -> list[str]:
        # Placeholder for plugging in a model later.
        return list(profile.include_queries)

    def explain_selection(self, title: str, query: str) -> str:
        return f"Selected from query '{query}' because it fits the requested Hindi mood mix."
