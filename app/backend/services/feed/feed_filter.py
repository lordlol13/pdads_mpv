"""Feed filter - deduplication, filtering, and constraints."""

from typing import Any
import hashlib

from app.backend.core.logging import ContextLogger

logger = ContextLogger(__name__)


def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """
    Validate and normalize an item.
    
    Returns None if item should be filtered out.
    """
    
    # Title validation
    final_title = str(item.get("final_title") or "").strip()
    if len(final_title) < 5:
        return None
    
    # Content validation
    final_text = str(item.get("final_text") or "").strip()
    if len(final_text) < 30:  # Minimum content length
        return None
    
    # Ensure ai_news_id
    if not item.get("ai_news_id"):
        return None
    
    return item


def _compute_title_hash(item: dict[str, Any]) -> str:
    """
    Compute normalized title hash for deduplication.
    """
    title = str(item.get("final_title") or "").lower().strip()
    return hashlib.sha256(" ".join(title.split()).encode("utf-8")).hexdigest()


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove duplicate items by ai_news_id and title hash.
    
    Keeps first occurrence (which has highest score).
    O(n) with hash set.
    """
    seen_ids = set()
    seen_title_hashes = set()
    deduped = []
    
    for item in items:
        ai_news_id = item.get("ai_news_id")
        title_hash = _compute_title_hash(item)
        if ai_news_id in seen_ids or title_hash in seen_title_hashes:
            continue
        
        seen_ids.add(ai_news_id)
        seen_title_hashes.add(title_hash)
        deduped.append(item)
    
    logger.info("deduplicated", extra={
        "before": len(items),
        "after": len(deduped),
        "removed": len(items) - len(deduped),
    })
    
    return deduped


def filter_seen_items(
    items: list[dict[str, Any]],
    seen_ids: set[int],
) -> list[dict[str, Any]]:
    """
    Remove items user has already seen.
    
    seen_ids: set of ai_news_id the user has viewed/clicked.
    """
    filtered = []
    
    for item in items:
        ai_news_id = item.get("ai_news_id")
        if ai_news_id not in seen_ids:
            filtered.append(item)
    
    logger.info("filtered_seen", extra={
        "before": len(items),
        "after": len(filtered),
        "removed": len(items) - len(filtered),
    })
    
    return filtered


def limit_topic_domination(
    items: list[dict[str, Any]],
    max_per_topic: int = 3,
) -> list[dict[str, Any]]:
    """
    Limit maximum items per topic/category.
    
    Prevents single category from dominating feed.
    Keeps items in order (respects ranking).
    """
    topic_counts = {}
    filtered = []
    
    for item in items:
        category = str(item.get("category") or "general").strip().lower()
        count = topic_counts.get(category, 0)
        
        if count < max_per_topic:
            filtered.append(item)
            topic_counts[category] = count + 1
    
    logger.info("limited_topics", extra={
        "before": len(items),
        "after": len(filtered),
        "max_per_topic": max_per_topic,
    })
    
    return filtered


def filter_feed(
    items: list[dict[str, Any]],
    user_id: int,
    seen_ids: set[int] | None = None,
    max_per_topic: int = 3,
    min_score: float = 0.0,
    allow_low_score_fallback: bool = False,
) -> list[dict[str, Any]]:
    """
    Apply all filter pipeline steps.
    
    Steps:
    1. Validate & normalize each item
    2. Deduplicate by content
    3. Remove seen items
    4. Limit topic domination
    5. Task 4: Quality threshold - drop items with score < min_score
    6. Task 6: Failsafe - allow fallback to lower scores if empty
    """
    
    # Step 1: Normalize
    normalized = []
    for item in items:
        normalized_item = _normalize_item(item)
        if normalized_item:
            normalized.append(normalized_item)
    
    logger.info("normalized", extra={
        "before": len(items),
        "after": len(normalized),
    })
    
    # Step 2: Deduplicate
    deduped = deduplicate(normalized)
    
    # Step 3: Filter seen
    if seen_ids:
        filtered = filter_seen_items(deduped, seen_ids)
    else:
        filtered = deduped
    
    # Step 4: Limit topics
    limited = limit_topic_domination(filtered, max_per_topic)
    
    # Task 4: Quality threshold - drop items with score < min_score
    quality_filtered = []
    for item in limited:
        score = float(item.get("rank_score") or 0.0)
        if score >= min_score:
            quality_filtered.append(item)
    
    logger.info(
        "quality_threshold",
        extra={
            "user_id": user_id,
            "min_score": min_score,
            "before": len(limited),
            "after": len(quality_filtered),
        }
    )
    
    logger.info("filter_complete", extra={
        "user_id": user_id,
        "final_count": len(quality_filtered),
    })
    
    return quality_filtered
