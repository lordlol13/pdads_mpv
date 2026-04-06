import asyncio
import json
import logging
import re
from typing import TypedDict

from openai import AsyncOpenAI

from app.backend.core.config import settings

logger = logging.getLogger(__name__)


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


def _normalize_spaces(text: str) -> str:
    return " ".join((text or "").split())


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
    value = re.sub(
        r"(^|\n)\s*(lid|yanglik|новость|news|asosiy\s+yangilik|foydalanuvchiga\s+ta'siri|kasbiy\s+nuqtai\s+nazar|amaliy\s+qadamlar)\s*:\s*",
        "\\1",
        value,
        flags=re.IGNORECASE,
    )

    lines = [re.sub(r"\s+", " ", line).strip() for line in value.replace("\r", "\n").split("\n")]
    compact = "\n".join(line for line in lines if line)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    return compact.strip()


def _split_into_paragraphs(text: str) -> list[str]:
    cleaned = _clean_text_artifacts(text)
    if not cleaned:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if paragraphs:
        return paragraphs
    return [cleaned]


def _sentences_to_paragraphs(text: str, target_paragraphs: int = 3) -> list[str]:
    cleaned = _clean_text_artifacts(text)
    if not cleaned:
        return []

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
    if len(sentences) <= 1:
        return [cleaned]

    chunk_size = max(1, len(sentences) // max(1, target_paragraphs))
    result: list[str] = []
    for idx in range(0, len(sentences), chunk_size):
        result.append(" ".join(sentences[idx : idx + chunk_size]).strip())

    return [p for p in result if p]


def _fit_word_bounds_with_paragraphs(text: str, min_words: int, max_words: int) -> str:
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        return ""

    kept: list[str] = []
    used = 0
    for paragraph in paragraphs:
        words = [w for w in paragraph.split() if w.strip()]
        if not words:
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
        "Ключевой фокус для читателя: отделить факты от шума, понять, что меняется прямо сейчас, и какие последствия это даст в ближайшие дни.",
        "Практический вывод: полезно проверить источник, сопоставить новость с локальным контекстом и выбрать один конкретный следующий шаг вместо перегрузки деталями.",
    ]
    for filler in filler_paragraphs:
        if _word_count(combined) >= min_words:
            break
        combined = (combined + "\n\n" + filler).strip() if combined else filler

    if _word_count(combined) > max_words:
        words = [w for w in combined.split() if w.strip()][:max_words]
        combined = " ".join(words)

    return combined.strip()


def _fit_word_bounds(text: str, min_words: int, max_words: int) -> str:
    words = [w for w in (text or "").split() if w.strip()]
    if len(words) > max_words:
        words = words[:max_words]
    return " ".join(words)


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
    min_words = settings.PIPELINE_TEXT_MIN_WORDS
    max_words = settings.PIPELINE_TEXT_MAX_WORDS

    if _word_count(clean_text) >= min_words:
        paragraphs = _split_into_paragraphs(clean_text)
        if len(paragraphs) < 3:
            paragraphs = _sentences_to_paragraphs(" ".join(paragraphs), target_paragraphs=3)
        fitted = _fit_word_bounds_with_paragraphs("\n\n".join(paragraphs), min_words, max_words)
        return fitted[: settings.PIPELINE_TEXT_MAX_CHARS]

    sections = [
        f"{title}. Эта новость важна в контексте {geo or 'текущей повестки'} и напрямую связана с интересом пользователя: {target_persona}.",
        f"По сути, речь идет о следующем: {clean_text or clean_raw_text}",
        (
            "Практическая значимость в том, что событие меняет приоритеты и влияет на решения в краткосрочном горизонте: "
            "нужно быстро отделить подтвержденные факты от интерпретаций и оценить влияние на ближайшие задачи."
        ),
        (
            f"С профессиональной точки зрения для роли {profession or 'специалиста'} ключевыми остаются устойчивость процесса, "
            "измеримый результат и понятный план действий на 1-2 недели вперед."
        ),
        (
            "Оптимальная тактика: усилить мониторинг, зафиксировать точки влияния на текущие планы и подготовить "
            "короткий список рисков и возможностей, который можно быстро обновлять по мере появления новых фактов."
        ),
    ]
    expanded = "\n\n".join(_clean_text_artifacts(section) for section in sections if section)

    while _word_count(expanded) < min_words:
        expanded += (
            "\n\nДополнительный акцент: решения стоит принимать на основе проверяемых данных, учитывая региональный контекст "
            "и понятную коммуникацию для целевой аудитории."
        )

    fitted = _fit_word_bounds_with_paragraphs(expanded, min_words, max_words)
    return fitted[: settings.PIPELINE_TEXT_MAX_CHARS]


def _normalize_score(raw_score: float, fallback_score: float) -> float:
    score = float(raw_score or fallback_score)
    # Some providers return scores in 0..1 range; normalize to 0..10.
    if 0.0 <= score <= 1.0:
        score *= 10.0
    return round(score, 2)


def _build_primary_client() -> tuple[AsyncOpenAI | None, str | None, str]:
    if settings.GROQ_API_KEY:
        return (
            AsyncOpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1"),
            settings.GROQ_MODEL,
            "Groq",
        )

    if settings.DEEPSEEK_API_KEY:
        return (
            AsyncOpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com"),
            "deepseek-chat",
            "DeepSeek",
        )

    return None, None, "fallback"


def _gemini_review_enabled() -> bool:
    return bool(settings.GEMINI_REVIEW_ENABLED and settings.GEMINI_API_KEY)


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
    fallback = {
        "final_title": f"[AI] {title}",
        "final_text": _ensure_structured_personal_text(
            (raw_text or "")[:1200],
            title=title,
            target_persona=target_persona,
            profession=profession,
            geo=user_geo or region,
            raw_text=raw_text,
        ),
        "ai_score": 8.5,
        "category": category or "general",
        "target_persona": target_persona or "general",
        "deepseek_score": 8.5,
        "gemini_score": 8.5,
        "combined_score": 8.5,
    }

    client, model_name, provider_name = _build_primary_client()
    if client is None or model_name is None:
        return fallback

    prompt = (
        "Ты аналитический редактор новостей. "
        "Верни строго JSON с ключами: final_title, final_text, ai_score, category, target_persona. "
        "final_text должен быть красивым связным материалом из 3-5 абзацев, без маркеров и заголовков вида 'Lid:', 'Yanglik:', 'Новость:'. "
        "Не используй мусорные артефакты кодировки и обрывки вида '[+123 chars]'. "
        f"Объем текста: {settings.PIPELINE_TEXT_MIN_WORDS}-{settings.PIPELINE_TEXT_MAX_WORDS} слов. "
        "Пиши на языке исходного материала; если язык неоднозначен — пиши на русском. "
        "Сделай текст персонализированным под интерес, профессию и геоконтекст пользователя."
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
        ai_score = _normalize_score(float(data.get("ai_score") or fallback["ai_score"]), float(fallback["ai_score"]))
        primary_output = {
            "final_title": str(data.get("final_title") or fallback["final_title"]),
            "final_text": _ensure_structured_personal_text(
                str(data.get("final_text") or fallback["final_text"]),
                title=title,
                target_persona=target_persona,
                profession=profession,
                geo=user_geo or region,
                raw_text=raw_text,
            ),
            "ai_score": ai_score,
            "category": str(data.get("category") or fallback["category"]),
            "target_persona": str(data.get("target_persona") or fallback["target_persona"]),
            "deepseek_score": ai_score,
            "gemini_score": fallback["gemini_score"],
            "combined_score": ai_score,
        }

        if not _gemini_review_enabled():
            return primary_output

        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.GEMINI_API_KEY)
            gemini_model = genai.GenerativeModel(settings.GEMINI_MODEL)
            gemini_prompt = json.dumps(
                {
                    "task": "review_and_improve_news_rewrite",
                    "input": primary_output,
                    "instructions": [
                        "Сохрани язык исходного текста (или русский при неоднозначности).",
                        "Убери все служебные метки вроде Lid/Yanglik/Новость и любые артефакты кодировки.",
                        "Сделай 3-5 читабельных абзацев с плавной логикой и ясными переходами.",
                        "Оцени качество и верни gemini_score от 0 до 10.",
                        "Return only JSON with final_title, final_text, ai_score, category, target_persona, gemini_score.",
                    ],
                },
                ensure_ascii=False,
            )
            gemini_response = await asyncio.to_thread(gemini_model.generate_content, gemini_prompt)
            gemini_content = getattr(gemini_response, "text", "") or "{}"
            gemini_data = json.loads(_strip_json_code_fence(gemini_content))

            deepseek_score = _normalize_score(float(primary_output["deepseek_score"]), float(primary_output["deepseek_score"]))
            gemini_score = _normalize_score(
                float(gemini_data.get("gemini_score") or gemini_data.get("ai_score") or deepseek_score),
                deepseek_score,
            )
            combined_score = round((deepseek_score + gemini_score) / 2, 2)

            return {
                "final_title": str(gemini_data.get("final_title") or primary_output["final_title"]),
                "final_text": _ensure_structured_personal_text(
                    str(gemini_data.get("final_text") or primary_output["final_text"]),
                    title=title,
                    target_persona=target_persona,
                    profession=profession,
                    geo=user_geo or region,
                    raw_text=raw_text,
                ),
                "ai_score": combined_score,
                "category": str(gemini_data.get("category") or primary_output["category"]),
                "target_persona": str(gemini_data.get("target_persona") or primary_output["target_persona"]),
                "deepseek_score": deepseek_score,
                "gemini_score": gemini_score,
                "combined_score": combined_score,
            }
        except Exception:
            logger.exception("Gemini review failed, returning %s output", provider_name)
            return primary_output
    except Exception:
        logger.exception("%s generation failed, falling back to mock output", provider_name)
        return fallback


def _strip_json_code_fence(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    return cleaned