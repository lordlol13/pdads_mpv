import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
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


def _ensure_uzbek_title(value: str, fallback_title: str) -> str:
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

    return source


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
    paragraphs = _split_into_paragraphs(text)
    facts = _extract_fact_sentences(raw_text, max_items=3)
    interest = _detect_primary_interest(title, raw_text, target_persona)
    sentiment = _detect_news_sentiment(f"{title} {raw_text}")
    language_hint = _detect_language_hint(text, raw_text, title, geo, target_persona)

    min_words = int(settings.PIPELINE_TEXT_MIN_WORDS or 170)
    cleaned_existing = "\n\n".join(paragraphs).strip()
    if len(paragraphs) >= 3 and _word_count(cleaned_existing) >= int(min_words * 0.75):
        persona_tokens = [t for t in re.split(r"[^\w]+", str(target_persona or "").lower()) if len(t) >= 3]
        lowered_existing = cleaned_existing.lower()
        if persona_tokens and not any(token in lowered_existing for token in persona_tokens[:3]):
            if language_hint == "ru":
                persona_line = (
                    f"For your profile ({str(target_persona or 'general').replace('|', ', ')}), "
                    "this update matters because it directly affects short-term expectations."
                )
            elif language_hint == "uz":
                persona_line = (
                    f"Sizning profilingiz ({str(target_persona or 'general').replace('|', ', ')}) uchun bu voqea "
                    "yaqin qarorlar va kutilmalarga bevosita ta'sir qiladi."
                )
            else:
                persona_line = (
                    f"For your profile ({str(target_persona or 'general').replace('|', ', ')}), "
                    "this update matters because it directly affects short-term expectations."
                )
            cleaned_existing = f"{cleaned_existing}\n\n{_clean_text_artifacts(persona_line)}".strip()
        return cleaned_existing

    lead_source = paragraphs[0] if paragraphs else f"{title}."
    lead = _clean_text_artifacts(lead_source)
    if not lead:
        lead = f"{title}."
    emotional_intro = _build_emotional_intro(interest, sentiment, title, language_hint)

    facts_line = " ".join(facts[:2]).strip()
    if not facts_line:
        details_block = " ".join(paragraphs[1:3]).strip() if len(paragraphs) > 1 else ""
        facts_line = details_block or _clean_text_artifacts(raw_text)[:320]

    if language_hint == "ru":
        facts_paragraph = f"Key facts and figures: {facts_line}".strip()
    elif language_hint == "uz":
        facts_paragraph = f"Asosiy fakt va raqamlar: {facts_line}".strip()
    else:
        facts_paragraph = f"Key facts and figures: {facts_line}".strip()

    persona_name = (target_persona or "general").strip().replace("|", ", ")
    interest_label = interest or persona_name
    if language_hint == "ru":
        persona_paragraph = (
            f"Why this matters to you: this development is directly tied to your interest in {interest_label}. "
            f"In {geo or 'your context'}, someone with a {profession or 'general'} profile should focus on "
            "verified facts, team form, and near-term scheduling."
        )
        action_paragraph = (
            "What to watch next: verified updates, lineup/injury changes, and the next fixtures or milestone events."
        )
    elif language_hint == "uz":
        persona_paragraph = (
            f'Siz uchun ahamiyati: voqea "{interest_label}" qiziqishi bilan bevosita bog\'liq. '
            f"{geo or 'hududiy kontekst'}da {profession or 'foydalanuvchi'} uchun hozir asosiy fokus "
            "risklar, jamoa formasi va yaqin taqvimni xolis baholashdir."
        )
        action_paragraph = (
            "Keyingi qadam: tasdiqlangan manbalarni, tarkib/jarohatlarni va keyingi o'yinlar yoki "
            "turnir bosqichlarini kuzatib boring."
        )
    else:
        persona_paragraph = (
            f"Why this matters to you: this development is directly tied to your interest in {interest_label}. "
            f"In {geo or 'your context'}, someone with a {profession or 'general'} profile should focus on "
            "verified facts, team form, and near-term scheduling."
        )
        action_paragraph = (
            "What to watch next: verified updates, lineup/injury changes, and the next fixtures or milestone events."
        )

    user_fact = _extract_user_related_fact(raw_text, interest, language_hint)

    composed = [
        _clean_text_artifacts(f"{emotional_intro} {lead}"),
        _clean_text_artifacts(facts_paragraph),
        _clean_text_artifacts(persona_paragraph),
        _clean_text_artifacts(f"{action_paragraph} {user_fact}"),
    ]

    return "\n\n".join(part for part in composed if part).strip()


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
    final_title = _ensure_uzbek_title(final_title_raw, title)
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
    if _word_count(combined) >= min_words:
        return combined

    language_hint = _detect_language_hint(text)
    if language_hint == "ru":
        filler_paragraphs = [
            "Practical focus: separate confirmed facts from noise and estimate the impact on the next fixture cycle.",
            "Working takeaway: cross-check key numbers across sources and update expectations for the next 24-48 hours.",
        ]
    elif language_hint == "uz":
        filler_paragraphs = [
            "Amaliy fokus: tasdiqlangan faktlarni shovqindan ajrating va yaqin taqvimga ta'sirini baholang.",
            "Ishchi xulosa: raqamlarni bir nechta manba bilan tekshirib, 24-48 soatlik rejani yangilang.",
        ]
    else:
        filler_paragraphs = [
            "Practical focus: separate confirmed facts from noise and estimate the impact on the next fixture cycle.",
            "Working takeaway: cross-check key numbers across sources and update expectations for the next 24-48 hours.",
        ]
    for filler in filler_paragraphs:
        if _word_count(combined) >= min_words:
            break
        combined = (combined + " " + filler).strip() if combined else filler

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
    clean_text = _clean_text_artifacts(text)
    clean_raw_text = _clean_text_artifacts(raw_text)
    min_words = int(settings.PIPELINE_TEXT_MIN_WORDS or 170)
    max_words = int(settings.PIPELINE_TEXT_MAX_WORDS or 0)

    if _word_count(clean_text) >= int(min_words * 0.7):
        paragraphs = _split_into_paragraphs(clean_text)
        if len(paragraphs) < 3:
            paragraphs = _sentences_to_paragraphs(" ".join(paragraphs), target_paragraphs=3)
        fitted = _fit_word_bounds_with_paragraphs("\n\n".join(paragraphs), min_words, max_words)
        return _apply_char_limit(fitted)

    language_hint = _detect_language_hint(clean_text, clean_raw_text, title, target_persona, geo)
    persona_label = str(target_persona or "general").replace("|", ", ")
    source_summary = clean_text or clean_raw_text or title

    if language_hint == "ru":
        sections = [
            f"{title}. This update is directly relevant to your interest profile: {persona_label}.",
            f"Core summary: {source_summary}",
            (
                f"In {geo or 'the current context'}, it is important to evaluate not only the result but also the drivers: "
                "tempo, lineup decisions, hard stats, and the near-term schedule."
            ),
            (
                f"For a {profession or 'general'} profile, the practical move is simple: "
                "prioritize confirmed sources and refresh expectations as new facts arrive."
            ),
        ]
    elif language_hint == "uz":
        sections = [
            f"{title}. Bu xabar sizning qiziqish profilingiz ({persona_label}) bilan bevosita bog'liq.",
            f"Qisqa mazmun: {source_summary}",
            (
                f"{geo or 'joriy kun tartibi'} kontekstida natijadan tashqari sabablarni ham baholash zarur: "
                "o'yin tempi, tarkib qarorlari, statistika va yaqin taqvim."
            ),
            (
                f"{profession or 'foydalanuvchi'} profili uchun amaliy qadam: "
                "tasdiqlangan manbalarga tayangan holda prognozni yangi faktlar bilan yangilab borish."
            ),
        ]
    else:
        sections = [
            f"{title}. This update is directly relevant to your interest profile: {persona_label}.",
            f"Core summary: {source_summary}",
            (
                f"In {geo or 'the current context'}, it is important to evaluate not only the result but also the drivers: "
                "tempo, lineup decisions, hard stats, and the near-term schedule."
            ),
            (
                f"For a {profession or 'general'} profile, the practical move is simple: "
                "prioritize confirmed sources and refresh expectations as new facts arrive."
            ),
        ]

    expanded = "\n\n".join(_clean_text_artifacts(section) for section in sections if section)

    for _ in range(4):
        if _word_count(expanded) >= min_words:
            break
        if language_hint == "ru":
            expanded += (
                "\n\nAdditional emphasis: decisions on this topic should follow source validation, "
                "cross-checking key metrics, and tracking immediate news triggers."
            )
        elif language_hint == "uz":
            expanded += (
                "\n\nQo'shimcha urg'u: mavzu bo'yicha qarorlar bir nechta manbani solishtirish, "
                "asosiy ko'rsatkichlarni tekshirish va yaqin yangilik triggerlarini inobatga olish bilan qabul qilinadi."
            )
        else:
            expanded += (
                "\n\nAdditional emphasis: decisions on this topic should follow source validation, "
                "cross-checking key metrics, and tracking immediate news triggers."
            )

    fitted = _fit_word_bounds_with_paragraphs(expanded, min_words, max_words)
    return _apply_char_limit(fitted)


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
        return "gpt-4.1-mini"

    normalized = raw.lower().replace("_", "-")
    aliases = {
        "gpt4-mini": "gpt-4o-mini",
        "gpt-4-mini": "gpt-4o-mini",
        "gpt4o-mini": "gpt-4o-mini",
        "gpt4.1-mini": "gpt-4.1-mini",
    }
    return aliases.get(normalized, raw)


def _persona_profile_for_prompt(
    *,
    target_persona: str,
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
    if language_hint == "ru":
        language_rule = "Write in natural Russian (Cyrillic)."
    elif language_hint == "uz":
        language_rule = "Matnni tabiiy o'zbek tilida, lotin yozuvida yozing."
    else:
        language_rule = "Write in the natural language of the source text."

    if max_words > 0:
        length_rule = f"Length: {min_words}-{max_words} words."
    else:
        length_rule = f"Length: at least {min_words} words."

    return (
        "You are a senior newsroom editor and feature journalist. "
        "Return ONLY strict JSON with keys: final_title, final_text, ai_score, category, target_persona. "
        f"{length_rule} "
        f"{language_rule} "
        "Write in a vivid, publication-quality style: clear lead, narrative flow, and precise facts. "
        "No markdown, no bullet lists, no template labels like Lid/Headline/Novost/Yangilik. "
        "Personalization rule: explicitly connect the story to the user's favorite team/topic/persona. "
        "If their side loses or context is negative, show concise empathy first, then give objective analysis. "
        "If positive, provide brief congratulations and context. "
        "Always include 2-4 concrete facts that matter to the user (players, stats, timeline, next match/event). "
        "Do not invent facts; if a detail is uncertain, say it is not confirmed."
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
        "quality_goals": {
            "tone": "human_journalistic",
            "must_include": [
                "empathetic personalization when appropriate",
                "team/topic-specific impact",
                "2-4 concrete user-relevant facts",
                "what to watch next",
            ],
        },
    }


def _build_openai_client() -> tuple[AsyncOpenAI | None, str | None]:
    if settings.OPENAI_API_KEY:
        model_name = _normalize_openai_model_name(settings.OPENAI_MODEL)
        if model_name != settings.OPENAI_MODEL:
            logger.info("Normalized OPENAI_MODEL from '%s' to '%s'", settings.OPENAI_MODEL, model_name)
        return (
            AsyncOpenAI(api_key=settings.OPENAI_API_KEY),
            model_name,
        )

    return None, None


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
) -> GeneratedNews:
    """
    Generate personalized news with retry, fallback, and caching.
    
    Flow:
    1. Try OpenAI ChatGPT (with retry & cache)
    2. Try Gemini (with retry & cache)
    3. If fails and fallback enabled, try DeepSeek (with retry & cache)
    4. If all fail, check cache for stale result
    4. Fall back to mock generation
    """
    
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

    # Try OpenAI first
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
    if openai_payload is not None:
        model_score = float(openai_payload.get("ai_score") or fallback["ai_score"])
        return _compose_generated_news(
            final_title_raw=str(openai_payload.get("final_title") or fallback["final_title"]),
            final_text_raw=str(openai_payload.get("final_text") or fallback["final_text"]),
            model_score_raw=model_score,
            category_raw=str(openai_payload.get("category") or fallback["category"]),
            target_persona_raw=str(openai_payload.get("target_persona") or fallback["target_persona"]),
            title=title,
            raw_text=raw_text,
            target_persona=target_persona,
            profession=profession,
            geo=user_geo or region,
        )

    # OpenAI-only mode: if OpenAI is unavailable, try cached OpenAI; otherwise return mock.
    cache_key = (title, target_persona, profession, user_geo)
    cached_openai = await cache_get("llm:openai", *cache_key)
    if cached_openai:
        logger.info("OpenAI unavailable, using cached OpenAI result")
        return _compose_generated_news(
            final_title_raw=str(cached_openai.get("final_title") or fallback["final_title"]),
            final_text_raw=str(cached_openai.get("final_text") or fallback["final_text"]),
            model_score_raw=float(cached_openai.get("ai_score") or fallback["ai_score"]),
            category_raw=str(cached_openai.get("category") or fallback["category"]),
            target_persona_raw=str(cached_openai.get("target_persona") or fallback["target_persona"]),
            title=title,
            raw_text=raw_text,
            target_persona=target_persona,
            profession=profession,
            geo=user_geo or region,
        )

    logger.warning("OpenAI unavailable, returning mock generation")
    return fallback


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
        logger.debug("OpenAI not configured")
        return None

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

    async def _call_openai():
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

        response = await client.chat.completions.create(
            model=model_name,
            temperature=0.45,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
        )

        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        return data if isinstance(data, dict) else None

    try:
        data = await retry_async(
            _call_openai,
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
        return data
    except Exception as e:
        logger.error(f"OpenAI generation failed: {e}")
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
        return cached

    async def _call_deepseek():
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

        # Create fallback for compose
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

