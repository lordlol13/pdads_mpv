from app.backend.services.feed_service import (
    LOCAL_FALLBACK_IMAGE_URL,
    MIN_FEED_ITEMS,
    _finalize_feed_rows,
    normalize_feed_item,
)


def test_finalize_feed_rows_never_empty() -> None:
    rows = _finalize_feed_rows([], limit=20, user_id=42)

    assert len(rows) >= MIN_FEED_ITEMS
    for row in rows:
        assert row["title"]
        assert row["text"]
        assert row["image_url"]
        assert row["source_url"]


def test_normalize_feed_item_fills_required_fields() -> None:
    raw_item = {
        "final_title": "",
        "final_text": "",
        "image_url": "",
        "source_url": "",
    }
    normalized = normalize_feed_item(raw_item, source="raw")

    assert normalized["title"] == "News update"
    assert normalized["text"] == "News update"
    assert normalized["image_url"] == LOCAL_FALLBACK_IMAGE_URL
    assert normalized["source_url"]


def test_finalize_feed_rows_forces_image_fallback() -> None:
    broken = [
        {
            "final_title": "Broken image article",
            "final_text": "Some text",
            "image_url": "data:image/png;base64,abc",
            "source_url": "https://example.com/a",
            "ai_score": 0.8,
        }
    ]

    rows = _finalize_feed_rows(broken, limit=20, user_id=1)
    primary = rows[0]

    assert primary["title"]
    assert primary["text"]
    assert primary["source_url"]
    assert primary["image_url"] == LOCAL_FALLBACK_IMAGE_URL
