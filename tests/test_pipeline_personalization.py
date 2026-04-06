from brain.tasks.pipeline_tasks import _extract_topics


def test_extract_topics_prefers_all_topics_with_custom_values() -> None:
    interests = {
        "topics": ["technology"],
        "custom_topics": ["Uzbek esports", "technology"],
        "all_topics": ["technology", "uzbek esports"],
    }

    result = _extract_topics(interests)

    assert result == ["technology", "uzbek esports"]


def test_extract_topics_uses_custom_topics_when_topics_empty() -> None:
    interests = {
        "topics": [],
        "custom_topics": ["Chinese farming", "AgriTech"],
    }

    result = _extract_topics(interests)

    assert result == ["chinese farming", "agritech"]


def test_extract_topics_parses_json_string_payload() -> None:
    interests = '{"topics": ["technology"], "custom_topics": ["CS", "Dota"], "all_topics": ["technology", "cs", "dota"]}'

    result = _extract_topics(interests)

    assert result == ["technology", "cs", "dota"]
