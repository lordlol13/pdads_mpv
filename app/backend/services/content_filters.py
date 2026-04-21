"""Content filters for news pipeline: ad detection, quality checks."""
from __future__ import annotations

from typing import Optional


def is_advertisement(text: Optional[str], title: Optional[str]) -> bool:
    """Return True if combined title+text looks like promotional content.

    Uses simple keyword heuristics (Uzbek + Russian + English common terms).
    """
    if not text and not title:
        return False
    combined = ((text or "") + " " + (title or "")).lower()

    keywords = [
        "reklama",
        "aksiya",
        "chegirma",
        "hamkorlik",
        "maxsus taklif",
        "promo",
        "sponsor",
        "sponsorlik",
        "реклама",
        "акция",
        "скидка",
        "партн",
        "партнёр",
        "партнер",
        "партнерство",
        "advertisement",
        "promotion",
    ]

    for k in keywords:
        if k in combined:
            return True
    return False


__all__ = ["is_advertisement"]
