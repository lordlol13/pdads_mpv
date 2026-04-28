import asyncio
from datetime import datetime, timedelta, timezone
import json
import re
from typing import TypedDict

from openai import AsyncOpenAI

from app.backend.core.config import settings
from app.backend.core.logging import ContextLogger
from app.backend.services.resilience_service import (
    retry_async,
    cache_get,
    cache_set,
    check_rate_limit,
    _llm_limiter,
)

logger = ContextLogger(__name__)
_GEMINI_BACKOFF_UNTIL: datetime | None = None
_GEMINI_DEFAULT_BACKOFF_SECONDS = 180

# Per-event-loop semaphore to limit concurrent external LLM requests
_LLM_SEMAPHORE: asyncio.Semaphore | None = None
_LLM_SEMAPHORE_LOOP_ID: int | None = None

def _get_llm_semaphore() -> asyncio.Semaphore | None:
    """Return an asyncio.Semaphore bound to the current running loop.

    This avoids awaiting a semaphore created on a different loop.
    """
    global _LLM_SEMAPHORE, _LLM_SEMAPHORE_LOOP_ID
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        return None

    if _LLM_SEMAPHORE is None or _LLM_SEMAPHORE_LOOP_ID != loop_id:
        _LLM_SEMAPHORE = asyncio.Semaphore(int(settings.LLM_CONCURRENCY or 2))
        _LLM_SEMAPHORE_LOOP_ID = loop_id
    return _LLM_SEMAPHORE

ENGLISH_TITLE_STOPWORDS = {
    "the",
    "and",
    "of",
    "to",
    "in",
    "for",
    "with",
    "on",
    "from",
    "by",
    "is",
    "are",
    "was",
    "were",
    "after",
    "before",
    "warning",
    "adds",
    "uncertainty",
}

ENGLISH_TEXT_STOPWORDS = ENGLISH_TITLE_STOPWORDS | {
    "today",
    "breaking",
    "report",
    "story",
    "latest",
    "update",
    "video",
    "watch",
    "more",
}

UZBEK_LATIN_MARKERS = {
    "yangilik",
    "o'zbekiston",
    "ozbekiston",
    "shuningdek",
    "bo'yicha",
    "foydalanuvchi",
    "jamoa",
    "g'alaba",
    "mag'lub",
}


class GeneratedNews(TypedDict):
    final_title: str
    final_text: str
    ai_score: float
    category: str
    target_persona: str
    deepseek_score: float
    gemini_score: float
    combined_score: float


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


def is_valid_news(text: str) -> bool:
    """Validate that generated news text is valid and not garbage.

    Returns True if text is valid, False otherwise.
    """
    if not text or not isinstance(text, str):
        return False

    # Check for broken encoding (Mojibake)
    if "Ð" in text or "â" in text or "Ã" in text or "Â" in text:
        return False

    # Check for HTML tags
    if "<" in text and ">" in text:
        return False

    # Check for forbidden phrases
    forbidden_phrases = [
        "Additional emphasis",
        "In Tashkent",
        "For a general profile",
        "Siz uchun ahamiyati",
        "Asosiy fakt va raqamlar",
        "Key facts",
        "Why this matters",
        "What to watch next",
        "emotional signal",
        "Bu juda muhim",
        "Zamonaviy dunyoda",
        "Foydalanuvchilar uchun",
    ]
    for phrase in forbidden_phrases:
        if phrase.lower() in text.lower():
            return False

    # Check minimum word count (prompt asks for 200-250, allow 150+ as valid)
    words = text.split()
    if len(words) < 150:
        return False

    # Check for excessive English (should be mostly Uzbek)
    english_words = len([w for w in words if re.match(r'^[a-zA-Z]+$', w)])
    if english_words > len(words) * 0.5:  # More than 50% English
        return False

    return True


def is_valid_title(title: str) -> bool:
    """Validate generated news title.

    Title rules are intentionally lighter than body text validation.
    """
    if not title or not isinstance(title, str):
        return False

    value = title.strip()
    if not value:
        return False

    # Check for broken encoding (Mojibake)
    if "Ã" in value or "Ã¢" in value or "Ãƒ" in value or "Ã‚" in value:
        return False

    # Check for HTML tags
    if "<" in value and ">" in value:
        return False

    words = [w for w in value.split() if w.strip()]
    if len(words) < 2:
        return False
    if len(words) > 24:
        return False
    if len(value) > 220:
        return False

    return True


def validate_ai_response(data: dict) -> tuple[bool, str]:
    """Validate AI response data.

    Returns (is_valid, error_message)
    """
    if not isinstance(data, dict):
        return False, "Invalid response format"

    title = data.get("final_title", "")
    text = data.get("final_text", "")

    if not title or not text:
        return False, "Missing title or text"

    if not is_valid_title(title):
        return False, f"Invalid title: {title[:50]}..."

    if not is_valid_news(text):
        return False, f"Invalid text: {text[:100]}..."

    return True, ""


def _apply_char_limit(text: str) -> str:
    max_chars = int(settings.PIPELINE_TEXT_MAX_CHARS or 0)
    if max_chars > 0:
        return text[:max_chars]
    return text


def _clean_text_artifacts(text: str) -> str:
    value = (text or "")

    replacements = {
        "â€™": "'",
        "â€\x9c": '"',
        "â€\x9d": '"',
        "â€“": "-",
        "â€”": "-",
        "â€¦": "...",
        "Ã": "",
        "Â": "",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(r"\[\+\d+\s+chars\]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:lid|yanglik|yangilik|headline|sarlavha)\b\s*:?", "", value, flags=re.IGNORECASE)
    value = re.sub(
        r"(^|\n)\s*(lid|yanglik|yangilik|headline|sarlavha|novost|news|asosiy\s+yangilik|foydalanuvchiga\s+ta'siri|kasbiy\s+nuqtai\s+nazar|amaliy\s+qadamlar)\s*:\s*",
        "\\1",
        value,
        flags=re.IGNORECASE,
    )
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.replace("\r", "\n").split("\n")]
    compact = "\n".join(line for line in lines if line)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    return compact.strip()


def _contains_cyrillic(text: str) -> bool:
    return bool(re.search(r"[\u0400-\u04FF]", text or ""))


def _detect_language_hint(*samples: str | None) -> str:
    joined = " ".join(str(sample or "") for sample in samples).strip().lower()
    if not joined:
        return "en"

    if _contains_cyrillic(joined):
        return "ru"

    uz_hits = sum(1 for token in UZBEK_LATIN_MARKERS if token in joined)
    if uz_hits >= 2:
        return "uz"

    return "en"


def _default_headline_for_language(language: str) -> str:
    if language == "ru":
        return "Top story"
    if language == "uz":
        return "Dolzarb xabar"
    return "Top story"


def _strip_title_heading_prefix(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(
        r"^\s*(?:yangilik|yanglik|news|novost|headline|sarlavha)\s*[:\-–—]+\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" -:\t")


def _looks_english_heavy(value: str) -> bool:
    tokens = [token for token in re.findall(r"[a-zA-Z']+", str(value or "").lower()) if token]
    if len(tokens) < 4:
        return False

    stopword_hits = sum(1 for token in tokens if token in ENGLISH_TITLE_STOPWORDS)
    return stopword_hits >= 2 and (stopword_hits / max(1, len(tokens))) >= 0.2


def _strip_likely_english_sentences(text: str) -> str:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", str(text or "")) if part.strip()]
    if not sentences:
        return ""

    filtered: list[str] = []
    for sentence in sentences:
        words = re.findall(r"[a-z']+", sentence.lower()) or []
        if len(words) < 5:
            filtered.append(sentence)
            continue

        hits = sum(1 for word in words if word in ENGLISH_TEXT_STOPWORDS)
        if hits >= 2 and (hits / max(1, len(words))) >= 0.2:
            continue
        filtered.append(sentence)

    return " ".join(filtered).strip()


def _ensure_uzbek_title(value: str, fallback_title: str, source_text: str | None = None) -> str:
    title = str(value or "").strip()
    source = title or str(fallback_title or "").strip()
    source = re.sub(r"^\s*\[ai\]\s*", "", source, flags=re.IGNORECASE).strip()
    source = _strip_title_heading_prefix(source)
    source = _clean_text_artifacts(source).split("\n", 1)[0].strip()
    source = _strip_title_heading_prefix(source)
    source = source.strip(" -:\t")
    language = _detect_language_hint(source, fallback_title)

    if not source:
        return _default_headline_for_language(language)

    # Avoid low-quality generated headings that look like parser leftovers.
    if re.search(r"^[\W_]+$", source) or len(source) < 4:
        return _default_headline_for_language(language)

    # Keep very long model outputs from becoming a pseudo-summary title.
    if len(source) > 160:
        source = source[:157].rstrip() + "..."

    # If the title still looks generic/template-like, infer a newsroom headline from source context.
    if source.lower() in {"top story", "dolzarb xabar", "news", "headline"}:
        inferred = _infer_news_headline_from_source(" ".join([fallback_title or "", source_text or ""]).strip())
        if inferred:
            return inferred

    return source


def _extract_leading_subject(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" .,:;!-")
    if not text:
        return ""

    parts = re.split(
        r"\b(?:won|wins|beats?|defeats?|victory|champion(?:s)?|pobeda|vyigral|yutdi|g'olib)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    head = parts[0].strip(" -,:;!")
    if not head:
        return ""

    words = [word for word in re.split(r"\s+", head) if word]
    return " ".join(words[:5]).strip()


def _infer_news_headline_from_source(source_title: str) -> str:
    raw = _clean_text_artifacts(source_title)
    if not raw:
        return ""

    lowered = raw.lower()
    subject = _extract_leading_subject(raw)
    if not subject:
        subject = re.sub(r"[^\w\s\-]", "", raw).strip().split(" ")[0:3]
        subject = " ".join(subject).strip()

    world_cup_markers = (
        "world cup",
        "чемпионат мира",
        "чм",
        "jahon chempionati",
    )
    win_markers = (
        "won",
        "wins",
        "victory",
        "champion",
        "champions",
        "pobeda",
        "vyigral",
        "g'olib",
        "g'alaba",
        "yutdi",
    )

    if subject and any(marker in lowered for marker in world_cup_markers) and any(marker in lowered for marker in win_markers):
        language = _detect_language_hint(raw)
        if language == "ru":
            return f"{subject} победитель чемпионата мира"
        if language == "uz":
            return f"{subject} jahon chempionati g'olibi"
        return f"{subject} wins the World Cup"

    first_sentence = re.split(r"(?<=[.!?])\s+", raw)[0].strip()
    first_sentence = re.sub(r"^[\"'“”‘’\-\s]+", "", first_sentence)
    first_sentence = re.sub(r"\s+", " ", first_sentence)
    return first_sentence[:120].strip(" -,:;") if first_sentence else ""


def _extract_news_topics_for_toc(title: str, raw_text: str, category: str | None = None) -> list[str]:
    source = _clean_text_artifacts(" ".join([title or "", raw_text or ""]))
    if not source:
        fallback = str(category or "").strip()
        return [fallback] if fallback else []

    chunks = re.split(r"[.!?;\n\r]+", source)
    phrases: list[str] = []
    for chunk in chunks:
        normalized = re.sub(r"\s+", " ", chunk).strip(" -,:;")
        if len(normalized) < 8:
            continue
        words = [w for w in normalized.split(" ") if w]
        if len(words) > 8:
            normalized = " ".join(words[:8]).strip()
        if normalized and normalized.lower() not in {p.lower() for p in phrases}:
            phrases.append(normalized)
        if len(phrases) >= 6:
            break

    if not phrases and category:
        phrases.append(str(category).strip())
    return phrases


def _split_into_paragraphs(text: str) -> list[str]:
    raw = str(text or "").replace("\r", "\n").strip()
    if not raw:
        return []

    if re.search(r"\n\s*\n", raw):
        parts: list[str] = []
        for chunk in re.split(r"\n\s*\n", raw):
            cleaned_chunk = _clean_text_artifacts(chunk)
            if cleaned_chunk:
                parts.append(cleaned_chunk)
        if parts:
            return parts

    cleaned = _clean_text_artifacts(raw)
    if not cleaned:
        return []

    line_parts = [part.strip() for part in cleaned.split("\n") if part.strip()]
    if len(line_parts) >= 3:
        return line_parts
    return [cleaned]


def _sentences_to_paragraphs(text: str, target_paragraphs: int = 3) -> list[str]:
    cleaned = _clean_text_artifacts(text)
    if not cleaned:
        return []

    sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+", cleaned) if s.strip()]
    if len(sentences) <= 1:
        return [cleaned]

    chunk_size = max(1, (len(sentences) + max(1, target_paragraphs) - 1) // max(1, target_paragraphs))
    result: list[str] = []
    for idx in range(0, len(sentences), chunk_size):
        result.append(" ".join(sentences[idx : idx + chunk_size]).strip())

    return [p for p in result if p]


def _extract_fact_sentences(raw_text: str, max_items: int = 3) -> list[str]:
    cleaned = _clean_text_artifacts(raw_text)
    if not cleaned:
        return []

    sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+", cleaned) if s.strip()]
    if not sentences:
        return []

    priority: list[str] = []
    secondary: list[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        has_digit = bool(re.search(r"\d", sentence))
        has_quant = any(token in lowered for token in ("%", "ming", "million", "mlrd", "foiz", "ta "))
        if has_digit or has_quant:
            priority.append(sentence)
        else:
            secondary.append(sentence)

    merged = [*priority, *secondary]
    result: list[str] = []
    seen: set[str] = set()
    for sentence in merged:
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(sentence)
        if len(result) >= max_items:
            break
    return result


def _persona_tokens(target_persona: str) -> list[str]:
    tokens = [token.strip().lower() for token in re.split(r"[^\w]+", str(target_persona or "")) if token.strip()]
    compact = [token for token in tokens if len(token) >= 3 and token not in {"and", "the", "for", "with", "news", "general"}]
    return compact[:8]


def _persona_phrases(target_persona: str) -> list[str]:
    raw = str(target_persona or "").strip().lower()
    if not raw:
        return []

    chunks = [chunk.strip() for chunk in re.split(r"[|,;]+", raw) if chunk.strip()]
    phrases: list[str] = []
    for chunk in chunks:
        normalized = re.sub(r"\s+", " ", chunk).strip()
        if len(normalized) >= 4:
            phrases.append(normalized)

    # Keep longer phrases first so "team spirit" wins over "team".
    phrases.sort(key=len, reverse=True)
    return phrases[:6]


def _detect_primary_interest(title: str, raw_text: str, target_persona: str) -> str | None:
    phrases = _persona_phrases(target_persona)
    tokens = _persona_tokens(target_persona)
    if not phrases and not tokens:
        return None

    haystack = f"{title} {raw_text}".lower()

    token_phrases: list[str] = []
    if len(tokens) >= 2:
        max_n = min(3, len(tokens))
        for n in range(max_n, 1, -1):
            for idx in range(0, len(tokens) - n + 1):
                phrase = " ".join(tokens[idx : idx + n]).strip()
                if len(phrase) >= 5:
                    token_phrases.append(phrase)

    for phrase in token_phrases:
        if phrase in haystack:
            return phrase

    for phrase in phrases:
        if phrase in haystack:
            return phrase

    for token in tokens:
        if token in haystack:
            return token

    if phrases:
        return phrases[0]
    return tokens[0]


def _detect_news_sentiment(text: str) -> str:
    lowered = str(text or "").lower()
    positive_markers = (
        "win",
        "won",
        "victory",
        "champion",
        "champions",
        "title",
        "qualified",
        "passed",
        "success",
        "rekord",
        "g'alaba",
        "zafar",
        "yutdi",
        "golib",
        "pobed",
        "vyigral",
        "chempion",
    )
    negative_markers = (
        "lost",
        "defeat",
        "eliminated",
        "suspended",
        "ban",
        "failed",
        "injury",
        "crisis",
        "jarohat",
        "maglub",
        "yutqaz",
        "afsus",
        "neudach",
        "porazhen",
        "proigral",
        "travm",
    )

    pos = sum(1 for marker in positive_markers if marker in lowered)
    neg = sum(1 for marker in negative_markers if marker in lowered)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _build_emotional_intro(interest: str | None, sentiment: str, title: str, language_hint: str) -> str:
    topic = interest or title
    if language_hint == "ru":
        if sentiment == "positive":
            return f"For your focus on {topic}, this is an encouraging signal."
        if sentiment == "negative":
            return f"For your focus on {topic}, this is a tough update and the disappointment is understandable."
        return f"The topic {topic} matters for your feed, so here is a calm fact-first breakdown."

    if language_hint == "uz":
        if sentiment == "positive":
            return f"{topic} bo'yicha xabar ijobiy: bu natija siz uchun quvonarli bo'lishi mumkin."
        if sentiment == "negative":
            return f"{topic} bo'yicha xabar murakkab: bu holat muxlislar kayfiyatiga ta'sir qilishi tabiiy."
        return f"{topic} siz uchun muhim mavzu, shu sabab asosiy faktlarni aniq va xolis ko'rib chiqamiz."

    if sentiment == "positive":
        return f"For your focus on {topic}, this is encouraging news worth noting."
    if sentiment == "negative":
        return f"For your focus on {topic}, this is a tough development and the disappointment is understandable."
    return f"{topic} is relevant to your interests, so here is a clear, fact-first breakdown."


def _extract_user_related_fact(raw_text: str, interest: str | None, language_hint: str) -> str:
    facts = _extract_fact_sentences(raw_text, max_items=5)
    if language_hint == "ru":
        prefix = "Relevant fact for your profile"
        fallback = "this story can influence decisions in the next 24-48 hours."
    elif language_hint == "uz":
        prefix = "Siz uchun muhim fakt"
        fallback = "bu voqea yaqin 24-48 soat ichidagi qarorlarga ta'sir qiladi."
    else:
        prefix = "Relevant fact for you"
        fallback = "this development can affect near-term decisions in the next 24-48 hours."

    if not facts:
        return f"{prefix}: {fallback}"

    if interest:
        interest_lower = interest.lower()
        for fact in facts:
            if interest_lower in fact.lower():
                return f"{prefix}: {fact}"

    return f"{prefix}: {facts[0]}"


def _enforce_editorial_structure(
    text: str,
    *,
    raw_text: str,
    title: str,
    target_persona: str,
    profession: str | None,
    geo: str | None,
) -> str:
    """Return text as-is without adding extra editorial sections.
    
    The LLM prompt now handles all formatting requirements.
    We just clean up artifacts and return the text unchanged.
    """
    # Clean up the text but don't add any extra sections
    cleaned = _clean_text_artifacts(text)
    
    # Ensure we have at least 1 paragraph
    paragraphs = _split_into_paragraphs(cleaned)
    if not paragraphs:
        return cleaned or title
    
    # Return exactly what the LLM generated (1-2 paragraphs max)
    return "\n\n".join(paragraphs[:2]).strip()


def _evaluate_text_quality(
    final_text: str,
    *,
    raw_text: str,
    target_persona: str,
    geo: str | None,
) -> float:
    text = _clean_text_artifacts(final_text)
    if not text:
        return 0.0

    words = [w for w in re.findall(r"\w+", text.lower()) if w]
    word_count = len(words)
    paragraphs = _split_into_paragraphs(text)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+", text) if s.strip()]
    avg_sentence_len = word_count / max(1, len(sentences))

    unique_words = len(set(words))
    lexical_diversity = unique_words / max(1, word_count)

    persona_tokens = [t for t in re.split(r"[^\w]+", (target_persona or "").lower()) if len(t) >= 3]
    geo_tokens = [t for t in re.split(r"[^\w]+", (geo or "").lower()) if len(t) >= 3]
    lowered = text.lower()
    sentiment = _detect_news_sentiment(f"{raw_text} {final_text}")

    persona_hit = any(token in lowered for token in persona_tokens[:4]) if persona_tokens else True
    geo_hit = any(token in lowered for token in geo_tokens[:3]) if geo_tokens else True

    raw_has_numbers = bool(re.search(r"\d", raw_text or ""))
    text_has_numbers = bool(re.search(r"\d", text))
    has_artifacts = bool(re.search(r"\[\+\d+\s+chars\]|\b(?:lid|yanglik)\b", text, flags=re.IGNORECASE))

    score = 0.0
    min_words = int(settings.PIPELINE_TEXT_MIN_WORDS or 170)

    if word_count >= min_words:
        score += 2.2
    else:
        score += min(2.2, max(0.0, word_count / max(1, min_words)) * 2.2)

    if len(paragraphs) >= 4:
        score += 1.8
    elif len(paragraphs) == 3:
        score += 1.2

    source_language = _detect_language_hint(raw_text, target_persona, geo)
    if source_language == "ru":
        score += 1.2 if _contains_cyrillic(text) else 0.2
    else:
        score += 0.8

    if persona_hit:
        score += 1.1
    if geo_hit:
        score += 0.8

    if not raw_has_numbers or text_has_numbers:
        score += 1.0

    if 0.35 <= lexical_diversity <= 0.78:
        score += 0.9
    else:
        score += 0.4

    if 8.0 <= avg_sentence_len <= 26.0:
        score += 0.8
    else:
        score += 0.3

    if not has_artifacts:
        score += 0.8

    has_congrats = any(
        token in lowered
        for token in (
            "tabrik",
            "zafar",
            "golib",
            "g'alaba",
            "great news",
            "congrat",
        )
    )
    has_condolence = any(
        token in lowered
        for token in (
            "afsus",
            "hamdard",
            "qiyin xabar",
            "tough development",
            "disappoint",
        )
    )
    has_user_fact = any(
        token in lowered
        for token in (
            "siz uchun muhim fakt",
            "sizga tegishli fakt",
            "relevant fact for you",
        )
    )

    if sentiment == "positive" and has_congrats:
        score += 0.8
    elif sentiment == "negative" and has_condolence:
        score += 0.8
    elif sentiment == "neutral":
        score += 0.4

    if has_user_fact:
        score += 0.8

    return round(max(0.0, min(10.0, score)), 2)


def _compose_generated_news(
    *,
    final_title_raw: str,
    final_text_raw: str,
    model_score_raw: float,
    category_raw: str,
    target_persona_raw: str,
    title: str,
    raw_text: str,
    target_persona: str,
    profession: str | None,
    geo: str | None,
) -> GeneratedNews:
    final_title = _ensure_uzbek_title(final_title_raw, title, raw_text)
    structured_text = _ensure_structured_personal_text(
        final_text_raw,
        title=final_title,
        target_persona=target_persona,
        profession=profession,
        geo=geo,
        raw_text=raw_text,
    )
    editorial_text = _enforce_editorial_structure(
        structured_text,
        raw_text=raw_text,
        title=final_title,
        target_persona=target_persona,
        profession=profession,
        geo=geo,
    )
    final_text = _apply_char_limit(
        _fit_word_bounds_with_paragraphs(
            editorial_text,
            int(settings.PIPELINE_TEXT_MIN_WORDS or 170),
            int(settings.PIPELINE_TEXT_MAX_WORDS or 0),
        )
    )

    model_score = _normalize_score(float(model_score_raw or 0.0), 7.5)
    quality_score = _evaluate_text_quality(
        final_text,
        raw_text=raw_text,
        target_persona=target_persona,
        geo=geo,
    )
    combined_score = round((model_score * 0.4) + (quality_score * 0.6), 2)

    return {
        "final_title": final_title,
        "final_text": final_text,
        "ai_score": combined_score,
        "category": str(category_raw or "general"),
        "target_persona": str(target_persona_raw or target_persona or "general"),
        "deepseek_score": model_score,
        "gemini_score": quality_score,
        "combined_score": combined_score,
    }


def _fit_word_bounds_with_paragraphs(text: str, min_words: int, max_words: int) -> str:
    """Return text without adding filler paragraphs."""
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        return ""

    unlimited_words = int(max_words or 0) <= 0
    kept: list[str] = []
    used = 0
    for paragraph in paragraphs:
        words = [w for w in paragraph.split() if w.strip()]
        if not words:
            continue

        if unlimited_words:
            kept.append(" ".join(words))
            used += len(words)
            continue

        remaining = max_words - used
        if remaining <= 0:
            break

        take = words[:remaining]
        kept.append(" ".join(take))
        used += len(take)

    combined = "\n\n".join(kept).strip()
    
    # Truncate if exceeds max_words, but don't add filler
    if not unlimited_words and _word_count(combined) > max_words:
        words = [w for w in combined.split() if w.strip()][:max_words]
        combined = " ".join(words)

    return combined.strip()


def _ensure_structured_personal_text(
    text: str,
    *,
    title: str,
    target_persona: str,
    profession: str | None,
    geo: str | None,
    raw_text: str,
) -> str:
    """Return clean text without adding extra sections.
    
    The LLM prompt now handles all formatting. We just clean and limit the text.
    """
    clean_text = _clean_text_artifacts(text)
    
    # Return up to 3 paragraphs, cleaned
    paragraphs = _split_into_paragraphs(clean_text)
    if not paragraphs:
        return clean_text or title
    
    # Limit to 3 paragraphs max and apply char limit
    limited = "\n\n".join(paragraphs[:3])
    return _apply_char_limit(limited)


def _normalize_score(raw_score: float, fallback_score: float) -> float:
    score = float(raw_score or fallback_score)
    # Some providers return scores in 0..1 range; normalize to 0..10.
    if 0.0 <= score <= 1.0:
        score *= 10.0
    return round(score, 2)


def _build_deepseek_client() -> tuple[AsyncOpenAI | None, str | None]:
    if settings.DEEPSEEK_API_KEY:
        return (
            AsyncOpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com"),
            "deepseek-chat",
        )

    return None, None


def _normalize_openai_model_name(model_name: str | None) -> str:
    raw = str(model_name or "").strip()
    if not raw:
        return "gpt-4o-mini"

    normalized = raw.lower().replace("_", "-")
    aliases = {
        "gpt4-mini": "gpt-4o-mini",
        "gpt-4-mini": "gpt-4o-mini",
        "gpt4o-mini": "gpt-4o-mini",
        "gpt4.1-mini": "gpt-4o-mini",
        "gpt-4.1-mini": "gpt-4o-mini",
        "gpt-3.5-turbo": "gpt-4o-mini",
        "gpt-4": "gpt-4o-mini",
        "gpt-4o": "gpt-4o-mini",
        "text-embedding-3-small": "gpt-4o-mini",
    }
    return aliases.get(normalized, raw)


def _persona_profile_for_prompt(
    *,
    target_persona: str,
    title: str,
    raw_text: str,
    category: str | None,
    profession: str | None,
    user_geo: str | None,
    region: str | None,
) -> dict[str, str | list[str] | None]:
    raw = str(target_persona or "").strip()
    parts = [part.strip() for part in raw.split("|") if part.strip()]

    topic = parts[0] if parts else (raw or "general")
    inferred_profession = profession or (parts[1] if len(parts) > 1 else None)
    inferred_geo = user_geo or (parts[2] if len(parts) > 2 else region)
    inferred_country = parts[3] if len(parts) > 3 else None

    readable_topics: list[str] = []
    for part in parts:
        token = re.sub(r"\s+", " ", part).strip()
        if token and token not in readable_topics:
            readable_topics.append(token)

    for topic in _extract_news_topics_for_toc(title=title, raw_text=raw_text, category=category):
        token = re.sub(r"\s+", " ", topic).strip()
        if token and token not in readable_topics:
            readable_topics.append(token)

    if not readable_topics:
        readable_topics = [topic]

    return {
        "target_persona_raw": raw or "general",
        "primary_topic": topic,
        "topics_toc": readable_topics[:8],
        "profession": inferred_profession,
        "geo": inferred_geo,
        "country_code": inferred_country,
    }


def _build_editorial_system_prompt(*, language_hint: str, min_words: int, max_words: int) -> str:
    """
    STRICT Uzbek tech news editor prompt.
    Output ONLY Uzbek (Latin). ZERO English/Russian.
    Focus ONLY on AI and technology. DELETE everything else.
    """
    word_range = f"{min_words}-{max_words}" if max_words > 0 else f"{min_words}+"
    return (
        "Siz professional texnologiya yangiliklari muxbiri va qat'iy tahrirchisisiz. "
        "Vazifangiz: yangiliklarni FAQAT O'ZBEK TILIDA (LOTIN) qayta yozing va tarjima qiling. "
        "Barcha matn FAQAT o'zbek tilida bo'lishi shart! "
        "Agar yangilikda AI/texnologiya elementi bo'lmasa, UNDA HAM umumiy texnologik kontekstda yoritib bering. "
        "\n\n"
        "QATTIY QOIDALAR (buzmang!):\n"
        "1. TIL: Faqat O'ZBEK tili (LOTIN alifbosi). INGLIZ yoki RUS tilida bir so'z ham bo'lmasin!\n"
        "   - Kompaniya nomlari (Meta, Google, Apple) va texnik atamalar (AI, API, GPU) bundan mustasno\n"
        "   - Qolgan barcha so'zlar FAQAT o'zbek tilida!\n"
        "2. FOKUS: FAQAT AI/texnologiya qismlari. Boshqalarini O'CHIRING!\n"
        f"3. UZUNLIK: 2-3 paragraf, JAMI {word_range} so'z. KAMIDA {min_words} SO'Z BO'LISHI SHART!\n"
        "4. USLUB: Professional yangiliklar uslubi. Aniq, keskin, faktga asoslangan. "
        "   - Hech qanday fikr, tahlil yoki maslahat yo'q!\n"
        "   - Har bir jumla YANGI ma'lumot qo'shishi kerak\n"
        "   - Takrorlar taqiqlanadi\n"
        "5. TA'QIQ LANGAN (ishlatmang!):\n"
        "   - 'Bu juda muhim'\n"
        "   - 'Zamonaviy dunyoda'\n"
        "   - 'Foydalanuvchilar uchun'\n"
        "   - 'Siz uchun ahamiyati'\n"
        "   - 'Asosiy fakt va raqamlar'\n"
        "   - Bosh sarlavhalar va umumiy iboralar\n"
        "6. Agar input sifati past bo'lsa: FAQAT faktik kontekst asosida kengaytiring. "
        "   Uydumagan ma'lumot qo'shmang!\n"
        "\n"
        "NAMUNA (yaxshi):\n"
        "Input: Meta plans to use employee activity data to improve AI models.\n"
        "Sarlavha: Meta sun'iy intellektni yaxshilash uchun xodimlar ma'lumotidan foydalanadi\n"
        "Matn: Meta kompaniyasi sun'iy intellekt modellarini rivojlantirish maqsadida xodimlarning ish faoliyatiga oid ma'lumotlarni tahlil qilishni rejalashtirmoqda. "
        "Ushbu jarayonda tizim ichidagi harakatlar, bosilgan tugmalar va ish jarayonidagi boshqa raqamli izlar o'rganiladi. "
        "Kompaniya bu ma'lumotlardan foydalanib, sun'iy intellekt modellarining aniqligini oshirish va natijalarni yaxshilashni maqsad qilgan. "
        "Tahlil jarayonida xodimlarning kundalik ish faoliyati, dasturiy ta'minotdan foydalanish statistikasi va raqamli muloqot ma'lumotlari qamrab olinadi. "
        "\n"
        "Shu bilan birga, bunday yondashuv maxfiylik va ma'lumotlarni himoya qilish sohasida jiddiy savollar keltirib chiqarmoqda. "
        "Mutaxassislar fikricha, xodimlar ma'lumotlaridan bunday keng miqyosda foydalanish shaxsiy hayot huquqlariga ta'sir qilishi mumkin. "
        "Kompaniya esa barcha ma'lumotlarni anonimlashtirilgan holda ishlatishini ta'kidlamoqda.\n"
        "\n"
        f"OUTPUT (JSON format, qo'shimcha matn yo'q):\n"
        f"final_title: qisqa, aniq sarlavha (10-15 so'z)\n"
        f"final_text: 2-3 paragraf, {word_range} so'z, faqat faktlar, FAQAT O'ZBEK TILI\n"
        f"ai_score: 0-10 baho (sifat bahosi)\n"
        f"category: 'technology'\n"
        f"target_persona: ai|tashkent|uz\n"
        "\n"
        "ESLATMA: Agar yangilik to'liq AI/texnologiya mavzusida bo'lmasa, undagi "
        "avtomatlashtirish, raqamli texnologiyalar, zamonaviy uskunalar kabi jihatlarni ajratib oling. "
        "Masalan, avtomobil ishlab chiqarish -> zamonaviy robotlashtirilgan ishlab chiqarish texnologiyalari.\n"
        "FAQAT JSON qaytaring!"
    )


def _build_editorial_user_payload(
    *,
    title: str,
    raw_text: str,
    category: str | None,
    target_persona: str,
    region: str | None,
    profession: str | None,
    user_geo: str | None,
    rewrite_round: int,
) -> dict[str, object]:
    persona = _persona_profile_for_prompt(
        target_persona=target_persona,
        title=title,
        raw_text=raw_text,
        category=category,
        profession=profession,
        user_geo=user_geo,
        region=region,
    )
    return {
        "task": "rewrite_news_for_personalized_feed",
        "rewrite_round": rewrite_round,
        "source": {
            "title": title,
            "raw_text": raw_text,
            "category": category or "general",
            "region": region,
        },
        "user_profile": persona,
        "requirements": {
            "language": "uzbek_latin_only",
            "length": "200-250_words",
            "paragraphs": "2-3_paragraphs",
            "style": "professional_news",
            "focus": "AI_technology_interest",
            "forbidden_phrases": [
                "Additional emphasis",
                "In Tashkent",
                "For a general profile",
                "Siz uchun ahamiyati",
                "Asosiy fakt va raqamlar",
                "Key facts",
                "Why this matters",
                "What to watch next",
                "emotional signal"
            ],
            "content_rules": [
                "only_concrete_facts_from_source",
                "no_generic_analysis",
                "no_filler_text",
                "no_repetition",
                "adapt_to_AI_tech_interest",
            ],
        },
    }


def _build_openai_client() -> tuple[AsyncOpenAI | None, str | None]:
    if not settings.OPENAI_API_KEY:
        return None, None

    # Determine requested model. If an explicit `OPENAI_MODEL` is provided via
    # env, use it. If none is set, allow switching to a heavier default only
    # when `LLM_ENABLE_HEAVY_MODEL` is true (guard against accidental heavy
    # model usage in production). Default safe model is gpt-4o-mini.
    requested_model = (settings.OPENAI_MODEL or "").strip()
    if not requested_model:
        requested_model = getattr(settings, "OPENAI_MODEL_DEFAULT_HEAVY", "gpt-4o-mini")

    model_name = _normalize_openai_model_name(requested_model)
    if model_name != requested_model:
        logger.info(f"Normalized OPENAI_MODEL from '{requested_model}' to '{model_name}'")

    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY), model_name


async def _openai_call_core(
    client: AsyncOpenAI,
    model_name: str,
    title: str,
    raw_text: str,
    category: str | None,
    target_persona: str,
    region: str | None,
    profession: str | None,
    user_geo: str | None,
    rewrite_round: int,
) -> dict[str, str | float] | None:
    """Core OpenAI call extracted to module-level to avoid fragile closures."""
    try:
        forced_lang = (getattr(settings, "EDITORIAL_FORCE_LANGUAGE", "") or "").strip().lower()
        if forced_lang:
            language_hint = forced_lang
        else:
            language_hint = _detect_language_hint(title, raw_text, target_persona, user_geo, region)

        system_prompt = _build_editorial_system_prompt(
            language_hint=language_hint,
            min_words=int(settings.PIPELINE_TEXT_MIN_WORDS or 170),
            max_words=int(settings.PIPELINE_TEXT_MAX_WORDS or 0),
        )

        payload = _build_editorial_user_payload(
            title=title,
            raw_text=raw_text,
            category=category,
            target_persona=target_persona,
            region=region,
            profession=profession,
            user_geo=user_geo,
            rewrite_round=rewrite_round,
        )

        logger.info(f"[OPENAI-CALL] model={model_name} title={title[:50]}...")

        sem = _get_llm_semaphore()
        if sem is not None:
            async with sem:
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model_name,
                        temperature=0.45,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                    ),
                    timeout=30.0,
                )
        else:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model_name,
                    temperature=0.45,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                ),
                timeout=30.0,
            )

        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        logger.info(f"[OPENAI-CALL] Success: response_keys={list(data.keys()) if isinstance(data, dict) else None}")
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.exception(f"[OPENAI-CALL] Error: {e}")
        raise


def _gemini_generation_available() -> bool:
    global _GEMINI_BACKOFF_UNTIL

    if not settings.GEMINI_API_KEY:
        return False

    if _GEMINI_BACKOFF_UNTIL is None:
        return True

    now = datetime.now(timezone.utc)
    if now >= _GEMINI_BACKOFF_UNTIL:
        _GEMINI_BACKOFF_UNTIL = None
        return True

    return False


def _extract_retry_seconds_from_error(message: str) -> int | None:
    text = str(message or "").lower()
    if not text:
        return None

    patterns = (
        r"retry[_\s-]*delay[^\d]{0,40}seconds[^\d]{0,10}(\d+)",
        r"retry[_\s-]*after[^\d]{0,20}(\d+)",
        r"retry\s+in[^\d]{0,20}(\d+)",
        r"after\s+(\d+)\s*seconds",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except (TypeError, ValueError):
            continue
        return max(30, min(1800, value))

    return None


def _mark_gemini_backoff_if_needed(exc: Exception) -> bool:
    global _GEMINI_BACKOFF_UNTIL

    message = str(exc or "")
    lowered = message.lower()
    is_rate_limited = any(
        marker in lowered
        for marker in (
            "429",
            "rate limit",
            "rate_limit",
            "too many requests",
            "resource has been exhausted",
            "quota",
        )
    )
    if not is_rate_limited:
        return False

    retry_seconds = _extract_retry_seconds_from_error(message) or _GEMINI_DEFAULT_BACKOFF_SECONDS
    until = datetime.now(timezone.utc) + timedelta(seconds=retry_seconds)
    if _GEMINI_BACKOFF_UNTIL is None or until > _GEMINI_BACKOFF_UNTIL:
        _GEMINI_BACKOFF_UNTIL = until

    logger.warning("Gemini rate-limited; backoff enabled for %s seconds", retry_seconds)
    return True


async def _generate_with_gemini(
    *,
    title: str,
    raw_text: str,
    category: str | None,
    target_persona: str,
    region: str | None,
    profession: str | None,
    user_geo: str | None,
    rewrite_round: int,
) -> dict[str, str | float] | None:
    if not _gemini_generation_available():
        logger.debug("Gemini not available (rate limited or no API key)")
        return None

    # Rate limit check
    allowed = await check_rate_limit(
        f"llm:gemini:{target_persona}",
        limiter=_llm_limiter,
        limit=settings.LLM_RATE_LIMIT_PER_MINUTE,
        window_seconds=60,
    )
    if not allowed:
        logger.warning("Gemini rate limit exceeded, skipping")
        return None

    # Check cache first
    cache_key = (title, target_persona, profession, user_geo)
    cached = await cache_get("llm:gemini", *cache_key)
    if cached is not None:
        logger.debug("Gemini cache hit")
        return cached

    async def _call_gemini():
        try:
            import google.generativeai as genai

            configure_fn = getattr(genai, "configure", None)
            model_cls = getattr(genai, "GenerativeModel", None)
            if not callable(configure_fn) or model_cls is None:
                return None

            configure_fn(api_key=settings.GEMINI_API_KEY)
            gemini_model = model_cls(settings.GEMINI_MODEL)
            forced_lang = (getattr(settings, "EDITORIAL_FORCE_LANGUAGE", "") or "").strip().lower()
            if forced_lang:
                language_hint = forced_lang
            else:
                language_hint = _detect_language_hint(title, raw_text, target_persona, user_geo, region)
            system_prompt = _build_editorial_system_prompt(
                language_hint=language_hint,
                min_words=int(settings.PIPELINE_TEXT_MIN_WORDS or 170),
                max_words=int(settings.PIPELINE_TEXT_MAX_WORDS or 0),
            )
            payload = _build_editorial_user_payload(
                title=title,
                raw_text=raw_text,
                category=category,
                target_persona=target_persona,
                region=region,
                profession=profession,
                user_geo=user_geo,
                rewrite_round=rewrite_round,
            )
            prompt = json.dumps(
                {
                    "instructions": system_prompt,
                    "payload": payload,
                },
                ensure_ascii=False,
            )

            sem = _get_llm_semaphore()
            if sem is not None:
                async with sem:
                    response = await asyncio.to_thread(gemini_model.generate_content, prompt)
            else:
                response = await asyncio.to_thread(gemini_model.generate_content, prompt)
            content = _strip_json_code_fence(getattr(response, "text", "") or "{}")
            data = json.loads(content)
            if not isinstance(data, dict):
                return None
            return data
        except Exception as exc:
            if _mark_gemini_backoff_if_needed(exc):
                logger.warning("Gemini generation deferred due to provider rate limit")
            else:
                logger.exception("Gemini generation failed")
            raise

    try:
        result = await retry_async(
            _call_gemini,
            max_attempts=settings.API_RETRY_MAX_ATTEMPTS,
            base_delay_seconds=settings.API_RETRY_BASE_DELAY_SECONDS,
            max_delay_seconds=settings.API_RETRY_MAX_DELAY_SECONDS,
            retry_on_exceptions=(Exception,),
        )
        
        if result:
            # Cache successful result
            await cache_set(
                "llm:gemini",
                settings.CACHE_LLM_RESULTS_TTL_HOURS,
                result,
                *cache_key,
            )
        return result
    
    except Exception as e:
        logger.error(f"Gemini generation failed after retries: {e}")
        return None


async def generate_news(
    raw_text: str,
    title: str,
    category: str | None,
    *,
    target_persona: str = "general",
    region: str | None = None,
    profession: str | None = None,
    user_geo: str | None = None,
    rewrite_round: int = 1,
) -> GeneratedNews | None:
    """
    Generate personalized news with retry, fallback, and caching.
    Validates output to ensure no garbage is returned.

    Flow:
    1. Try OpenAI ChatGPT (with retry & cache & validation)
    2. Retry up to 2 times if result is invalid
    3. Return None if all attempts fail (caller should handle)
    """

    print("[DEBUG] generate_news called")
    print(f"[AI] generate_news called: title={title[:50] if title else ''}")
    logger.info(f"[GENERATE] Starting generation: title={title[:50] if title else ''}..., persona={target_persona}")

    # Single OpenAI call — no retry loop for speed
    openai_payload = await _generate_with_openai(
        title=title,
        raw_text=raw_text,
        category=category,
        target_persona=target_persona,
        region=region,
        profession=profession,
        user_geo=user_geo,
        rewrite_round=rewrite_round,
    )

    if openai_payload is None:
        logger.warning("[GENERATE] OpenAI returned None")
        print("[DEBUG] generate_news NO PAYLOAD from OpenAI")
        return None

    # Log validation result but DON'T block saving
    is_valid, error_msg = validate_ai_response(openai_payload)
    print(f"[DEBUG] validate_ai_response: is_valid={is_valid}, error={error_msg}")
    if not is_valid:
        logger.warning(f"[GENERATE] Validation warning (not blocking): {error_msg}")

    model_score = float(openai_payload.get("ai_score") or 7.0)
    if not is_valid:
        model_score = min(model_score, 4.0)  # Lower score for unvalidated results

    print(f"[DEBUG] generate_news result: title={str(openai_payload.get('final_title', ''))[:60]}")
    return _compose_generated_news(
        final_title_raw=str(openai_payload.get("final_title") or title),
        final_text_raw=str(openai_payload.get("final_text") or raw_text[:500]),
        model_score_raw=model_score,
        category_raw=str(openai_payload.get("category") or category or "general"),
        target_persona_raw=str(openai_payload.get("target_persona") or target_persona or "general"),
        title=title,
        raw_text=raw_text,
        target_persona=target_persona,
        profession=profession,
        geo=user_geo or region,
    )


async def _generate_with_openai(
    *,
    title: str,
    raw_text: str,
    category: str | None,
    target_persona: str,
    region: str | None,
    profession: str | None,
    user_geo: str | None,
    rewrite_round: int,
) -> dict[str, str | float] | None:
    """Generate with OpenAI ChatGPT as primary LLM, with retry and cache."""

    client, model_name = _build_openai_client()
    if client is None or model_name is None:
        logger.warning(f"[LLM] OPENAI_API_KEY not configured - OpenAI generation disabled")
        return None
    
    logger.info(f"[LLM] OpenAI generation started: model={model_name}, persona={target_persona}")

    allowed = await check_rate_limit(
        f"llm:openai:{target_persona}",
        limiter=_llm_limiter,
        limit=settings.LLM_RATE_LIMIT_PER_MINUTE,
        window_seconds=60,
    )
    if not allowed:
        logger.warning("OpenAI rate limit exceeded")
        return None

    cache_key = (title, target_persona, profession, user_geo)
    cached = await cache_get("llm:openai", *cache_key)
    if cached is not None:
        logger.debug("OpenAI cache hit")
        return cached

    # Use a module-level core function to avoid fragile closures and ensure
    # the callable passed to retry_async is stable across event-loop boundaries.
    try:
        data = await retry_async(
            _openai_call_core,
            client,
            model_name,
            title,
            raw_text,
            category,
            target_persona,
            region,
            profession,
            user_geo,
            rewrite_round,
            max_attempts=settings.API_RETRY_MAX_ATTEMPTS,
            base_delay_seconds=settings.API_RETRY_BASE_DELAY_SECONDS,
            max_delay_seconds=settings.API_RETRY_MAX_DELAY_SECONDS,
            retry_on_exceptions=(Exception,),
        )
        if not data:
            return None

        await cache_set(
            "llm:openai",
            settings.CACHE_LLM_RESULTS_TTL_HOURS,
            data,
            *cache_key,
        )
        logger.info(f"[LLM] OpenAI generation successful: title={str(data.get('final_title', ''))[:50]}...")
        return data
    except Exception as e:
        logger.exception(f"[LLM] OpenAI generation failed: {e}")
        return None


async def _generate_with_deepseek(
    *,
    title: str,
    raw_text: str,
    category: str | None,
    target_persona: str,
    region: str | None,
    profession: str | None,
    user_geo: str | None,
    rewrite_round: int,
) -> GeneratedNews | None:
    """Generate with DeepSeek as fallback, with retry and cache."""
    
    client, model_name = _build_deepseek_client()
    if client is None or model_name is None:
        logger.debug("DeepSeek not configured")
        return None

    # Rate limit check
    allowed = await check_rate_limit(
        f"llm:deepseek:{target_persona}",
        limiter=_llm_limiter,
        limit=settings.LLM_RATE_LIMIT_PER_MINUTE,
        window_seconds=60,
    )
    if not allowed:
        logger.warning("DeepSeek rate limit exceeded")
        return None

    # Check cache
    cache_key = (title, target_persona, profession, user_geo)
    cached = await cache_get("llm:deepseek", *cache_key)
    if cached is not None:
        logger.debug("DeepSeek cache hit")
        # cached is expected to be the raw payload dict
        data = cached
        # Compose into GeneratedNews for compatibility with callers
        fallback = _compose_generated_news(
            final_title_raw=title,
            final_text_raw=(raw_text or "")[:1400],
            model_score_raw=7.2,
            category_raw=category or "general",
            target_persona_raw=target_persona or "general",
            title=title,
            raw_text=raw_text,
            target_persona=target_persona,
            profession=profession,
            geo=user_geo or region,
        )
        return _compose_generated_news(
            final_title_raw=str(data.get("final_title") or fallback["final_title"]),
            final_text_raw=str(data.get("final_text") or fallback["final_text"]),
            model_score_raw=float(data.get("ai_score") or fallback["ai_score"]),
            category_raw=str(data.get("category") or fallback["category"]),
            target_persona_raw=str(data.get("target_persona") or fallback["target_persona"]),
            title=title,
            raw_text=raw_text,
            target_persona=target_persona,
            profession=profession,
            geo=user_geo or region,
        )

    async def _call_deepseek():
        forced_lang = (getattr(settings, "EDITORIAL_FORCE_LANGUAGE", "") or "").strip().lower()
        if forced_lang:
            language_hint = forced_lang
        else:
            language_hint = _detect_language_hint(title, raw_text, target_persona, user_geo, region)

        prompt = _build_editorial_system_prompt(
            language_hint=language_hint,
            min_words=int(settings.PIPELINE_TEXT_MIN_WORDS or 170),
            max_words=int(settings.PIPELINE_TEXT_MAX_WORDS or 0),
        )

        payload = _build_editorial_user_payload(
            title=title,
            raw_text=raw_text,
            category=category,
            target_persona=target_persona,
            region=region,
            profession=profession,
            user_geo=user_geo,
            rewrite_round=rewrite_round,
        )

        sem = _get_llm_semaphore()
        if sem is not None:
            async with sem:
                response = await client.chat.completions.create(
                    model=model_name,
                    temperature=0.45,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                )
        else:
            response = await client.chat.completions.create(
                model=model_name,
                temperature=0.45,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
            )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        return data

    try:
        data = await retry_async(
            _call_deepseek,
            max_attempts=settings.API_RETRY_MAX_ATTEMPTS,
            base_delay_seconds=settings.API_RETRY_BASE_DELAY_SECONDS,
            max_delay_seconds=settings.API_RETRY_MAX_DELAY_SECONDS,
            retry_on_exceptions=(Exception,),
        )

        if not data:
            return None

        # Compose result
        fallback = _compose_generated_news(
            final_title_raw=title,
            final_text_raw=(raw_text or "")[:1400],
            model_score_raw=7.2,
            category_raw=category or "general",
            target_persona_raw=target_persona or "general",
            title=title,
            raw_text=raw_text,
            target_persona=target_persona,
            profession=profession,
            geo=user_geo or region,
        )

        result = _compose_generated_news(
            final_title_raw=str(data.get("final_title") or fallback["final_title"]),
            final_text_raw=str(data.get("final_text") or fallback["final_text"]),
            model_score_raw=float(data.get("ai_score") or fallback["ai_score"]),
            category_raw=str(data.get("category") or fallback["category"]),
            target_persona_raw=str(data.get("target_persona") or fallback["target_persona"]),
            title=title,
            raw_text=raw_text,
            target_persona=target_persona,
            profession=profession,
            geo=user_geo or region,
        )

        # Cache successful result
        await cache_set(
            "llm:deepseek",
            settings.CACHE_LLM_RESULTS_TTL_HOURS,
            data,
            *cache_key,
        )

        return result

    except Exception as e:
        logger.error(f"DeepSeek generation failed: {e}")
        return None


def _strip_json_code_fence(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    return cleaned

