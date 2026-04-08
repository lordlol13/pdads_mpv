import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import TypedDict

from openai import AsyncOpenAI

from app.backend.core.config import settings

logger = logging.getLogger(__name__)
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
        r"(^|\n)\s*(lid|yanglik|yangilik|headline|sarlavha|новость|news|asosiy\s+yangilik|foydalanuvchiga\s+ta'siri|kasbiy\s+nuqtai\s+nazar|amaliy\s+qadamlar)\s*:\s*",
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


def _strip_title_heading_prefix(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(
        r"^\s*(?:yangilik|yanglik|news|новость|headline|sarlavha)\s*[:\-–—]+\s*",
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
    source = title or str(fallback_title or "").strip() or "yangilik"
    source = re.sub(r"^\s*\[ai\]\s*", "", source, flags=re.IGNORECASE).strip()
    source = _strip_title_heading_prefix(source)
    source = _clean_text_artifacts(source).split("\n", 1)[0].strip()
    source = _strip_title_heading_prefix(source)

    if not source or _contains_cyrillic(source) or _looks_english_heavy(source):
        return "Dolzarb xabar"

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
        "побед",
        "выиграл",
        "выиграла",
        "чемпион",
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
        "неудач",
        "поражен",
        "проиграл",
        "проиграла",
        "травм",
    )

    pos = sum(1 for marker in positive_markers if marker in lowered)
    neg = sum(1 for marker in negative_markers if marker in lowered)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _build_emotional_intro(interest: str | None, sentiment: str, title: str) -> str:
    if interest and sentiment == "positive":
        return (
            f"Zo'r yangilik: {interest} bo'yicha sizni chin dildan tabriklayman. "
            f"Bu xabar kayfiyatni kotaradi va {title} mavzusida ijobiy fon yaratadi."
        )
    if interest and sentiment == "negative":
        return (
            f"Afsuski, {interest} bo'yicha xabar oson emas, buni siz bilan birga jiddiy qabul qilaman. "
            f"{title} bo'yicha vaziyatni sokin va faktlarga tayangan holda korib chiqamiz."
        )
    if interest:
        return f"{interest} mavzusi siz uchun muhim, shuning uchun {title} yangiligini sodda va aniq korib chiqamiz."
    return f"{title} bo'yicha asosiy yangilikni qisqa va aniq formatda beraman."


def _extract_user_related_fact(raw_text: str, interest: str | None) -> str:
    facts = _extract_fact_sentences(raw_text, max_items=5)
    if not facts:
        return "Sizga tegishli fakt: bu voqea siz kuzatadigan yonalishda yaqin kunlarda qarorlarni tez qabul qilishni talab qiladi."

    if interest:
        interest_lower = interest.lower()
        for fact in facts:
            if interest_lower in fact.lower():
                return f"Sizga tegishli fakt: {fact}"

    return f"Sizga tegishli fakt: {facts[0]}"


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

    lead_source = paragraphs[0] if paragraphs else f"{title}."
    lead = _clean_text_artifacts(lead_source)
    if not lead:
        lead = f"{title}."
    emotional_intro = _build_emotional_intro(interest, sentiment, title)

    facts_line = " ".join(facts[:2]).strip()
    if not facts_line:
        facts_line = paragraphs[1] if len(paragraphs) > 1 else _clean_text_artifacts(raw_text)[:320]
    facts_paragraph = f"Faktlar va raqamlar: {facts_line}".strip()

    persona_name = (target_persona or "general").strip().replace("|", ", ")
    interest_label = interest or persona_name
    persona_paragraph = (
        "Siz uchun ahamiyati: ushbu voqea "
        f"{interest_label} qiziqishlari bilan bevosita bogliq. "
        f"{geo or 'Hududiy kontekst'} sharoitida {profession or 'mutaxassis'} uchun "
        "asosiy fokus - tez qaror, aniq prioritet va faktlarga tayangan baholash."
    )

    user_fact = _extract_user_related_fact(raw_text, interest)
    action_paragraph = (
        "Keyingi amaliy reja: 1) manbani qayta tekshiring, 2) asosiy risk va imkoniyatlarni qisqa royxat qiling, "
        "3) keyingi 24-48 soat uchun bitta aniq harakat rejasini belgilang. "
        f"{user_fact}"
    )

    composed = [
        _clean_text_artifacts(f"{emotional_intro} {lead}"),
        _clean_text_artifacts(facts_paragraph),
        _clean_text_artifacts(persona_paragraph),
        _clean_text_artifacts(action_paragraph),
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

    if not _contains_cyrillic(text):
        score += 1.2

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

    has_congrats = any(token in lowered for token in ("tabrik", "zafar", "golib", "g'alaba"))
    has_condolence = any(token in lowered for token in ("afsus", "qiyin xabar", "hamdard", "sokin korib"))
    has_user_fact = "sizga tegishli fakt" in lowered

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

    filler_paragraphs = [
        "Asosiy urg'u: faktni shovqindan ajratish, hozir nimalar ozgarayotganini tushunish va yaqin kunlardagi ta'sirini baholash kerak.",
        "Amaliy xulosa: manbani tekshirib, yangilikni mahalliy kontekst bilan solishtirish va keyingi bitta aniq qadamni tanlash foydali.",
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
    clean_text = _strip_likely_english_sentences(_clean_text_artifacts(text))
    clean_raw_text = _strip_likely_english_sentences(_clean_text_artifacts(raw_text))
    min_words = settings.PIPELINE_TEXT_MIN_WORDS
    max_words = int(settings.PIPELINE_TEXT_MAX_WORDS or 0)

    if _word_count(clean_text) >= min_words and not _contains_cyrillic(clean_text) and not _looks_english_heavy(clean_text):
        paragraphs = _split_into_paragraphs(clean_text)
        if len(paragraphs) < 3:
            paragraphs = _sentences_to_paragraphs(" ".join(paragraphs), target_paragraphs=3)
        fitted = _fit_word_bounds_with_paragraphs("\n\n".join(paragraphs), min_words, max_words)
        return _apply_char_limit(fitted)

    sections = [
        f"{title}. Bu yangilik {geo or 'joriy kun tartibi'} kontekstida muhim va foydalanuvchi qiziqishi - {target_persona} - bilan bevosita bog'liq.",
        f"Mazmuni qisqacha shunday: {clean_text or clean_raw_text}",
        (
            "Amaliy ahamiyati shundaki, hodisa ustuvorliklarni ozgartiradi va qisqa muddatli qarorlarga ta'sir qiladi: "
            "tasdiqlangan faktlarni talqindan tez ajratib, yaqin vazifalarga ta'sirini baholash kerak."
        ),
        (
            f"Kasbiy nuqtai nazardan {profession or 'mutaxassis'} roli uchun jarayon barqarorligi, "
            "olchab bo'ladigan natija va 1-2 haftalik aniq harakat rejasi eng muhim bo'lib qoladi."
        ),
        (
            "Optimal taktika: monitoringni kuchaytirish, joriy rejalarga ta'sir nuqtalarini qayd etish va "
            "yangi faktlar chiqishi bilan tez yangilanadigan qisqa risk-imkoniyatlar royxatini tayyorlash."
        ),
    ]
    expanded = "\n\n".join(_clean_text_artifacts(section) for section in sections if section)

    while _word_count(expanded) < min_words:
        expanded += (
            "\n\nQoshimcha urg'u: qarorlar tekshiriladigan malumotlar asosida, hududiy kontekstni hisobga olib "
            "va maqsadli auditoriya uchun tushunarli kommunikatsiya bilan qabul qilinishi kerak."
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
        return None

    try:
        import google.generativeai as genai

        configure_fn = getattr(genai, "configure", None)
        model_cls = getattr(genai, "GenerativeModel", None)
        if not callable(configure_fn) or model_cls is None:
            return None

        configure_fn(api_key=settings.GEMINI_API_KEY)
        gemini_model = model_cls(settings.GEMINI_MODEL)
        prompt = json.dumps(
            {
                "task": "generate_personalized_news_rewrite",
                "constraints": {
                    "format": "strict_json",
                    "required_keys": [
                        "final_title",
                        "final_text",
                        "ai_score",
                        "category",
                        "target_persona",
                    ],
                    "paragraphs": "3-5",
                    "words": {
                        "min": settings.PIPELINE_TEXT_MIN_WORDS,
                        "max": settings.PIPELINE_TEXT_MAX_WORDS if settings.PIPELINE_TEXT_MAX_WORDS > 0 else None,
                    },
                    "output_language": "uz",
                    "output_script": "latin",
                    "style": "conversational_empathy",
                    "personalization_rules": [
                        "if user interest entity has positive outcome, congratulate naturally",
                        "if user interest entity has negative outcome, express concise empathy",
                        "end text with user-relevant concrete fact",
                    ],
                    "no_markers": ["Lid:", "Yanglik:", "Новость:"],
                },
                "payload": {
                    "title": title,
                    "raw_text": raw_text,
                    "category": category,
                    "target_persona": target_persona,
                    "region": region,
                    "profession": profession,
                    "user_geo": user_geo,
                    "rewrite_round": rewrite_round,
                },
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

    gemini_payload = await _generate_with_gemini(
        title=title,
        raw_text=raw_text,
        category=category,
        target_persona=target_persona,
        region=region,
        profession=profession,
        user_geo=user_geo,
        rewrite_round=rewrite_round,
    )
    if gemini_payload is not None:
        model_score = float(gemini_payload.get("ai_score") or gemini_payload.get("gemini_score") or fallback["ai_score"])
        return _compose_generated_news(
            final_title_raw=str(gemini_payload.get("final_title") or fallback["final_title"]),
            final_text_raw=str(gemini_payload.get("final_text") or fallback["final_text"]),
            model_score_raw=model_score,
            category_raw=str(gemini_payload.get("category") or fallback["category"]),
            target_persona_raw=str(gemini_payload.get("target_persona") or fallback["target_persona"]),
            title=title,
            raw_text=raw_text,
            target_persona=target_persona,
            profession=profession,
            geo=user_geo or region,
        )

    client, model_name = _build_deepseek_client()
    if client is None or model_name is None:
        return fallback

    prompt = (
        "Siz yangiliklarni qayta yozadigan analitik muharrirsiz. "
        "Faqat JSON qaytaring: final_title, final_text, ai_score, category, target_persona. "
        "final_text 3-5 abzatsli, ravon va markerlarsiz bolsin ('Lid:', 'Yanglik:', 'Novost:' yoq). "
        "Kodlash artefaktlari va '[+123 chars]' kabi chiqindilarni ishlatmang. "
        f"Matn hajmi kamida {settings.PIPELINE_TEXT_MIN_WORDS} soz bo'lsin. "
        + (
            f"Maksimal hajm {settings.PIPELINE_TEXT_MAX_WORDS} sozdan oshmasin. "
            if settings.PIPELINE_TEXT_MAX_WORDS > 0
            else "Yuqori chegara yoq. "
        )
        + "Matnni doim ozbek tilida (lotin yozuvida) yozing. "
        + "Matn foydalanuvchi qiziqishi, kasbi va geokontekstiga moslashtirilgan bolsin. "
        + "Agar foydalanuvchi qiziqadigan jamoa/yunalish bo'yicha natija ijobiy bo'lsa tabriklang, salbiy bo'lsa qisqa hamdardlik bildiring. "
        + "Matn oxirida foydalanuvchiga bevosita tegishli bitta aniq fakt bo'lsin."
    )

    try:
        response = await client.chat.completions.create(
            model=model_name,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "title": title,
                            "raw_text": raw_text,
                            "category": category,
                            "target_persona": target_persona,
                            "region": region,
                            "profession": profession,
                            "user_geo": user_geo,
                            "rewrite_round": rewrite_round,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        model_score = float(data.get("ai_score") or fallback["ai_score"])
        return _compose_generated_news(
            final_title_raw=str(data.get("final_title") or fallback["final_title"]),
            final_text_raw=str(data.get("final_text") or fallback["final_text"]),
            model_score_raw=model_score,
            category_raw=str(data.get("category") or fallback["category"]),
            target_persona_raw=str(data.get("target_persona") or fallback["target_persona"]),
            title=title,
            raw_text=raw_text,
            target_persona=target_persona,
            profession=profession,
            geo=user_geo or region,
        )
    except Exception:
        logger.exception("DeepSeek generation failed, falling back to mock output")
        return fallback


def _strip_json_code_fence(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    return cleaned