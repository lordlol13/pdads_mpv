import re
from app.backend.services.llm_service import _build_editorial_system_prompt


def test_editorial_prompt_contains_structure_and_json_directive():
    prompt = _build_editorial_system_prompt(language_hint="ru", min_words=170, max_words=0)
    assert "Return ONLY a single JSON object" in prompt
    assert "STRUCTURE" in prompt or "Intro:" in prompt
    # ensure default length target was applied (250-500)
    assert re.search(r"Length: \d+-\d+ words\.", prompt)
    assert "250-500" in prompt or int(re.search(r"Length: (\d+)-(\d+) words\.", prompt).group(1)) >= 250
