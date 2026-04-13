from app.backend.services.recommender_service import (
    cosine_similarity,
    rank_feed_rows,
    text_to_embedding,
)


def test_text_to_embedding_is_deterministic() -> None:
    first = text_to_embedding("Uzbek tech market grows quickly")
    second = text_to_embedding("Uzbek tech market grows quickly")

    assert first == second
    assert any(value != 0.0 for value in first)


def test_cosine_similarity_prefers_related_text() -> None:
    user_vector = text_to_embedding("football match result and sports analysis")
    related_vector = text_to_embedding("sports analysis after football match")
    unrelated_vector = text_to_embedding("diplomatic policy and central bank inflation")

    assert cosine_similarity(user_vector, related_vector) > cosine_similarity(user_vector, unrelated_vector)


def test_rank_feed_rows_prefers_more_similar_item() -> None:
    user_embedding = text_to_embedding("technology startups and software engineering")
    rows = [
        {
            "user_feed_id": 1,
            "ai_news_id": 11,
            "target_persona": "general",
            "final_title": "New software engineering tools for startups",
            "final_text": "A detailed report about software engineering teams building products.",
            "category": "technology",
            "embedding_vector": text_to_embedding("New software engineering tools for startups"),
            "created_at": "2026-04-10T00:00:00+00:00",
        },
        {
            "user_feed_id": 2,
            "ai_news_id": 12,
            "target_persona": "general",
            "final_title": "Weather alert for coastal regions",
            "final_text": "Forecast and storm warning for the next 24 hours.",
            "category": "weather",
            "embedding_vector": text_to_embedding("Weather alert for coastal regions"),
            "created_at": "2026-04-10T00:00:00+00:00",
        },
    ]

    ranked = rank_feed_rows(rows, user_embedding=user_embedding, limit=2, user_topics=["technology"])

    assert ranked[0]["ai_news_id"] == 11
    assert ranked[0]["rank_score"] >= ranked[1]["rank_score"]