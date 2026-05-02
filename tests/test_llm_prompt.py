import re
from app.backend.services.llm_service import _build_editorial_system_prompt


def test_editorial_prompt_contains_structure_and_json_directive():
    prompt = _build_editorial_system_prompt(language_hint="ru", min_words=170, max_words=0)
    # JSON return directive present (any language)
    assert "JSON" in prompt
    # Output structure section present
    assert "OUTPUT" in prompt or "STRUCTURE" in prompt or "Intro:" in prompt
    # Word length target present as a numeric range somewhere in the prompt
    assert re.search(r"\d+[-–]\d+", prompt) is not None
