import random
from typing import Iterable, Any

# Event weights used to convert raw events into preference scores per category
EVENT_WEIGHTS = {
    "view": 1.0,
    "like": 3.0,
    "skip": -2.0,
    "long_view": 2.0,  # >10 sec extra
}


def compute_user_preferences(events: Iterable[Any]) -> dict:
    """Aggregate user events into a simple per-category preference score.

    `events` may be ORM objects or dict-like rows. Each event should provide
    `event_type`, optional `dwell_time` and optional `category` (fallback 'general').
    """
    scores: dict = {}
    for e in (events or []):
        if isinstance(e, dict):
            event_type = e.get("event_type") or e.get("type") or ""
            dwell = float(e.get("dwell_time") or 0)
            category = str(e.get("category") or "general").strip().lower()
        else:
            event_type = getattr(e, "event_type", None) or getattr(e, "type", "")
            dwell = float(getattr(e, "dwell_time", 0) or 0)
            category = str(getattr(e, "category", None) or "general").strip().lower()

        weight = float(EVENT_WEIGHTS.get(event_type, 0.0))
        if dwell and dwell > 10:
            weight += float(EVENT_WEIGHTS.get("long_view", 0.0))

        scores[category] = scores.get(category, 0.0) + weight

    return scores


def add_exploration(score: float) -> float:
    """Small exploration noise to inject serendipity in ranking."""
    return float(score + random.uniform(0.0, 0.15))
