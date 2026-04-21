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
    # generic promotional keywords
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
        "trade-in",
        "trade in",
    ]

    for k in keywords:
        if k in combined:
            return True

    # site navigation / UI markers that often indicate a non-article page
    nav_markers = ["kabinet", "bosh sahifa", "tasma", "menyu", "videolar", "bosh sahifa"]
    if any(nm in combined for nm in nav_markers):
        # if nav markers appear together with comment/registration UI it's likely not an article
        if "izoh qoldirish" in combined or "izoh" in combined or "ro'yxatdan" in combined or "ro‘yxatdan" in combined:
            return True

    # explicit attribution / developer markers often come from landing/promotional pages
    if "ishlab chiquvchi" in combined or "ishlab chiqaruvchi" in combined:
        return True

    # copyright inside the scraped text together with UI words is suspicious
    if "©" in combined or "copyright" in combined:
        if "ishlab" in combined or "izoh" in combined or any(nm in combined for nm in nav_markers):
            return True

    return False


__all__ = ["is_advertisement"]
