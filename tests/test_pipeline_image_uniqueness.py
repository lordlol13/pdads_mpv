from brain.tasks.pipeline_tasks import _enforce_cross_post_unique_images
from app.backend.services.media_service import canonical_image_key


def test_enforce_cross_post_unique_images_filters_reserved_and_duplicates():
    reserved_keys = {
        canonical_image_key("https://cdn.example.com/images/a.jpg?utm_source=telegram"),
    }

    media_urls = [
        "https://cdn.example.com/images/a.jpg?utm_campaign=test",  # reserved via canonical key
        "https://cdn.example.com/images/b.jpg",
        "https://cdn.example.com/images/b.jpg?utm_source=ads",  # duplicate of b by canonical key
        "https://images.other.com/pic/c.webp",
    ]

    result = _enforce_cross_post_unique_images(
        media_urls,
        reserved_keys,
        limit=2,
        seed_base="seed",
    )

    assert len(result) == 2
    result_keys = [canonical_image_key(url) for url in result]
    assert canonical_image_key("https://cdn.example.com/images/a.jpg") not in result_keys
    assert len(set(result_keys)) == len(result_keys)


def test_enforce_cross_post_unique_images_backfills_with_fallbacks():
    reserved_keys = {
        canonical_image_key("https://cdn.example.com/images/a.jpg"),
    }
    media_urls = [
        "https://cdn.example.com/images/a.jpg",
    ]

    result = _enforce_cross_post_unique_images(
        media_urls,
        reserved_keys,
        limit=3,
        seed_base="raw-1:persona-a",
    )

    assert len(result) == 3
    keys = [canonical_image_key(url) for url in result]
    assert len(set(keys)) == 3
    assert all(url.startswith("https://") for url in result)
