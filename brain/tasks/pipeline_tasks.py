import asyncio
import hashlib
import json
import logging
import re
import os
import time  # FIX - For observability timing
import random
from datetime import datetime
from typing import Optional, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.backend.core.celery_app import celery_app
from app.backend.core.config import settings
from app.backend.services.ingestion_service import create_raw_news
from app.backend.services.llm_service import generate_news
from app.backend.services.parser import clean_text
from app.backend.services.media_service import (
    fetch_media_urls,
    canonical_image_key,
    visual_image_key,
    extract_image_dimensions,
    _normalize_candidate_url,
)
from app.backend.services.news_api_service import fetch_articles_for_topics
from app.backend.services.recommender_service import refresh_ai_news_embedding
from app.backend.db.session import SessionLocal
# FIX START - Observability integration
from app.backend.services.observability_service import (
    get_logger,
    metrics,
    health_monitor,
    Timer,
    set_correlation_id,
)
# FIX END

logger = logging.getLogger(__name__)
LOG = logger
# FIX - Use structured logger
obs_logger = get_logger("pipeline")

# FIX - Global semaphore for LLM concurrency control (max 3 concurrent calls)
_llm_semaphore = asyncio.Semaphore(3)


BAD_PHRASES = [
    "reklama",
    "реклама",
    "подписывайтесь",
    "obuna",
    "batafsil",
    "batafsil o‘qish",
    "telegram",
    "instagram",
    "youtube",
]


def simple_clean(text: str, max_len: int = 400) -> str:
    if not text:
        return ""

    # collapse whitespace
    s = re.sub(r"\s+", " ", str(text))

    # remove URLs
    s = re.sub(r"http\S+", "", s)

    # remove bad phrases (case-insensitive)
    for phrase in BAD_PHRASES:
        try:
            s = re.sub(re.escape(phrase), "", s, flags=re.IGNORECASE)
        except Exception:
            s = s.replace(phrase, "")

    # remove short/meaningless sentence fragments
    parts = [p.strip() for p in s.split(".")]
    parts = [p for p in parts if len(p) > 40]

    s = ". ".join(parts)

    # truncate and append ellipsis
    return s[:max_len].strip() + "..."


def fix_cut_words(text: str) -> str:
    if not text:
        return text

    if not text.endswith((".", "!", "?")):
        # drop the trailing partial word
        if " " in text:
            text = text.rsplit(" ", 1)[0]
    return text


def clean_title(title: str) -> str:
    if not title:
        return ""

    t = str(title).strip()
    # remove site suffixes like "| Site" or "- Site"
    t = re.sub(r"\|.*$", "", t).strip()
    t = re.sub(r"-.*$", "", t).strip()
    return t[:120]


STOPWORDS = {
    "the", "and", "or", "but", "is", "are", "a", "an",
    "va", "ham", "lekin", "bu", "shu",
    "и", "в", "на", "с", "это",
}


SMART_HIGHLIGHT_ENABLED = str(os.getenv("SMART_HIGHLIGHT") or "").lower() in ("1", "true", "yes")


def score_sentence(sentence: str) -> int:
    words = re.findall(r"\w+", sentence.lower())
    return sum(1 for w in words if w not in STOPWORDS)


def smart_summary(text: str, max_sentences: int = 3) -> str:
    if not text:
        return ""

    sentences = re.split(r"[.!?]", text)
    # Build scored list with original positions to preserve order later
    scored: list[tuple[str, int, int]] = []
    for idx, s in enumerate(sentences):
        s_str = s.strip()
        if len(s_str) > 40:
            scored.append((s_str, score_sentence(s_str), idx))

    if not scored:
        return (text or "")[:400].strip() + "..."

    # sort by informativeness (score desc) and pick top candidates
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:max_sentences]

    # preserve original document order for readability
    top_sorted_by_pos = sorted(top, key=lambda x: x[2])
    top_sentences = [s for s, _, _ in top_sorted_by_pos]

    # dedupe near-duplicate sentences (fingerprint by prefix)
    def dedupe_sentences(sentences_list: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for s in sentences_list:
            key = s[:50]
            if key in seen:
                continue
            seen.add(key)
            result.append(s)
        return result

    top_sentences = dedupe_sentences(top_sentences)
    if not top_sentences:
        # fallback to first scored sentence
        return scored[0][0][:400].strip() + "."

    return ". ".join(top_sentences).strip() + "."


def highlight_keywords(text: str, keywords: list[str]) -> str:
    if not text or not keywords:
        return text
    for kw in keywords:
        try:
            # use word boundaries to avoid mid-word matches; wrap with <b> for safe HTML
            pattern = re.compile(rf"\b({re.escape(kw)})\b", flags=re.IGNORECASE)
            text = pattern.sub(lambda m: f"<b>{m.group(1)}</b>", text)
        except Exception:
            pass
    return text


def _extract_image_urls_payload(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]

    return []


async def _load_reserved_image_keys(session: AsyncSession, exclude_ai_news_id: int | None) -> set[str]:
    query = """
    SELECT image_urls
    FROM ai_news
    WHERE image_urls IS NOT NULL
    """
    params: dict[str, Any] = {}
    if exclude_ai_news_id is not None:
        query += " AND id <> :exclude_ai_news_id"
        params["exclude_ai_news_id"] = exclude_ai_news_id

    result = await session.execute(text(query), params)
    reserved: set[str] = set()
    for row in result.fetchall():
        payload = row[0] if isinstance(row, tuple) else row.image_urls
        for url in _extract_image_urls_payload(payload):
            key = canonical_image_key(url)
            if key:
                reserved.add(key)
    return reserved


def _build_unique_fallback_image_url(seed_base: str, index: int) -> str:
    digest = hashlib.sha1(f"{seed_base}:{index}".encode("utf-8")).hexdigest()[:16]
    return f"https://picsum.photos/seed/{digest}/1600/900"


def _enforce_cross_post_unique_images(
    media_urls: list[str],
    reserved_keys: set[str],
    *,
    limit: int,
    seed_base: str,
) -> list[str]:
    unique_urls: list[str] = []
    local_keys: set[str] = set()

    for raw_url in media_urls:
        url = str(raw_url or "").strip()
        if not url:
            continue
        # Prefer canonical key, but fall back to visual key or raw url when canonical is missing
        key = canonical_image_key(url) or visual_image_key(url) or url
        if key in reserved_keys or key in local_keys:
            continue
        unique_urls.append(url)
        local_keys.add(key)
        if len(unique_urls) >= limit:
            return unique_urls

    # Ensure we still return enough media by generating deterministic unique fallbacks.
    fallback_index = 0
    max_attempts = max(24, limit * 8)
    while len(unique_urls) < limit and fallback_index < max_attempts:
        candidate = _build_unique_fallback_image_url(seed_base, fallback_index)
        fallback_index += 1
        key = canonical_image_key(candidate)
        if not key or key in reserved_keys or key in local_keys:
            continue
        unique_urls.append(candidate)
        local_keys.add(key)

    return unique_urls[:limit]


def _collapse_quality_variants(urls: list[str], prefer_indices: tuple[int, int] = (0, 1)) -> list[str]:
    """Collapse multiple URLs that are the same image in different qualities.

    Groups URLs by their visual key (size/quality placeholders). For groups
    with multiple variants, prefer a variant that appears at one of the
    `prefer_indices` positions in the original list (0-based), otherwise
    pick the variant with the largest parsed area (width*height). If no
    dimensions are available, pick the last variant (highest original index).
    """
    if not urls:
        return []

    groups_order: list[str] = []
    groups: dict[str, list[dict[str, Any]]] = {}

    for idx, url in enumerate(urls):
        vkey = visual_image_key(url) or canonical_image_key(url) or str(url)
        if vkey not in groups:
            groups[vkey] = []
            groups_order.append(vkey)

        w, h = extract_image_dimensions(url)
        area = (w or 0) * (h or 0) if (w and h) else None
        groups[vkey].append({"idx": idx, "url": url, "w": w, "h": h, "area": area})

    result: list[str] = []
    for vkey in groups_order:
        entries = groups[vkey]
        # Prefer entries that are at preferred indices
        preferred = [e for e in entries if e["idx"] in prefer_indices]
        chosen = None
        if preferred:
            chosen = max(preferred, key=lambda e: e.get("area") or 0)
        else:
            # choose by max area if available
            entries_with_area = [e for e in entries if e.get("area")]
            if entries_with_area:
                chosen = max(entries_with_area, key=lambda e: e.get("area") or 0)
            else:
                # fallback: choose first (preserve original ranking when no dimensions available)
                chosen = min(entries, key=lambda e: e.get("idx") or 0)

        if chosen:
            result.append(chosen["url"])

    return result


def _normalize_interests_payload(interests: Any) -> dict[str, Any] | None:
    if isinstance(interests, dict):
        return interests
    if isinstance(interests, str) and interests.strip():
        try:
            parsed = json.loads(interests)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _extract_topics(interests: Any) -> list[str]:
    if not interests:
        return []

    payload = _normalize_interests_payload(interests)
    if payload is not None:
        collected: list[str] = []
        for key in ("all_topics", "topics", "custom_topics"):
            values = payload.get(key)
            if isinstance(values, list):
                collected.extend([str(t).strip().lower() for t in values if str(t).strip()])
        if collected:
            deduped: list[str] = []
            seen: set[str] = set()
            for topic in collected:
                if topic in seen:
                    continue
                seen.add(topic)
                deduped.append(topic)
            return deduped
        return [str(k).strip().lower() for k, v in payload.items() if v]

    if isinstance(interests, list):
        return [str(t).strip().lower() for t in interests if str(t).strip()]
    return []


def _extract_profession(interests: Any) -> str | None:
    payload = _normalize_interests_payload(interests)
    if payload is not None:
        profession = str(payload.get("profession") or "").strip().lower()
        return profession or None
    return None


def _build_target_persona_label(
    topic: str,
    profession: str | None,
    geo: str | None,
    country_code: str | None,
) -> str:
    parts = [topic.strip().lower() or "general"]
    if profession:
        parts.append(profession.strip().lower())
    if geo:
        parts.append(geo.strip().lower())
    if country_code:
        parts.append(country_code.strip().lower())
    return "|".join(parts)

async def _set_status(
    session: AsyncSession,
    raw_news_id: int,
    status: str,
    error_message: Optional[str] = None,
    attempt_count: Optional[int] = None,
) -> None:


    query = """
    UPDATE raw_news
    SET process_status = :status,
        error_message = :error_message,
        processing_started_at = CASE WHEN :status = 'processing' THEN COALESCE(processing_started_at, CURRENT_TIMESTAMP) ELSE processing_started_at END,
        attempt_count = COALESCE(:attempt_count, attempt_count)
    WHERE id = :raw_news_id
    """
    await session.execute(
        text(query),
        {
            "status": status,
            "error_message": error_message,
            "attempt_count": attempt_count,
            "raw_news_id": raw_news_id,
        },
    )


async def _try_advisory_lock(session: AsyncSession, lock_key: int) -> bool:
    if session.get_bind().dialect.name != "postgresql":
        return True
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:lock_key)"),
        {"lock_key": lock_key},
    )
    return bool(result.scalar_one())


async def _release_advisory_lock(session: AsyncSession, lock_key: int) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": lock_key},
    )


async def _claim_raw_news_for_processing(
    session: AsyncSession,
    raw_news_id: int,
) -> bool:
    # Only allow claiming items that are not currently 'processing' and
    # that have not exhausted retry attempts. This prevents re-claiming
    # items that are actively being processed by another worker.
    max_attempts = int(os.getenv("PIPELINE_MAX_ATTEMPTS", str(getattr(settings, 'PIPELINE_MAX_ATTEMPTS', 3))))
    query = """
    UPDATE raw_news
    SET process_status = :status,
        error_message = NULL,
        processing_started_at = :now,
        attempt_count = COALESCE(attempt_count, 0) + 1
    WHERE id = :raw_news_id
      AND (
          process_status IS NULL
          OR process_status IN ('pending', 'new', 'failed', 'generated', 'classified')
      )
      AND COALESCE(attempt_count, 0) < :max_attempts
    """
    now_iso = datetime.utcnow().isoformat()
    result = await session.execute(
        text(query),
        {
            "status": "processing",
            "raw_news_id": raw_news_id,
            "max_attempts": max_attempts,
            "now": now_iso,
        },
    )
    return bool(result.rowcount)


async def _recover_stale_processing_rows(session: AsyncSession, ttl_minutes: int) -> int:
    ttl_minutes = max(1, int(ttl_minutes))
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "sqlite":
        query = """
        UPDATE raw_news
        SET process_status = 'pending',
            error_message = NULL,
            processing_started_at = NULL
        WHERE process_status = 'processing'
          AND COALESCE(processing_started_at, created_at) < datetime('now', :ttl_expr)
        """
        params = {"ttl_expr": f"-{ttl_minutes} minutes"}
    else:
        query = """
        UPDATE raw_news
        SET process_status = 'pending',
            error_message = NULL,
            processing_started_at = NULL
        WHERE process_status = 'processing'
          AND COALESCE(processing_started_at, created_at) < NOW() - make_interval(mins => :ttl_minutes)
        """
        params = {"ttl_minutes": ttl_minutes}

    result = await session.execute(text(query), params)
    return int(result.rowcount or 0)


async def _fetch_raw_news(session: AsyncSession, raw_news_id: int) -> Optional[dict[str, Any]]:
    query = """
    SELECT
        id,
        title,
        raw_text,
        source_url,
        image_url,
        category,
        region,
        is_urgent
    FROM raw_news
    WHERE id = :raw_news_id
    """
    result = await session.execute(text(query), {"raw_news_id": raw_news_id})
    row = result.mappings().first()
    if row is None:
        return None
    return dict(row)


async def _load_cohort_personas(session: AsyncSession) -> list[dict[str, str | None]]:
    query = """
    SELECT interests, location, country_code
    FROM users
    WHERE is_active = TRUE
    """
    result = await session.execute(text(query))
    rows = [dict(row) for row in result.mappings().all()]

    persona_contexts: list[dict[str, str | None]] = []
    seen_labels: set[str] = set()
    for row in rows:
        interests = row.get("interests")
        geo = str(row.get("location") or "").strip().lower() or None
        country_code = str(row.get("country_code") or "").strip().upper() or None
        profession = _extract_profession(interests)
        topics = _extract_topics(interests) or ["general"]

        for topic in topics:
            label = _build_target_persona_label(topic, profession, geo, country_code)
            if label in seen_labels:
                continue
            seen_labels.add(label)
            persona_contexts.append(
                {
                    "topic": topic,
                    "profession": profession,
                    "geo": geo,
                    "country_code": country_code,
                    "label": label,
                }
            )

    if not persona_contexts:
        return [{"topic": "general", "profession": None, "geo": None, "country_code": None, "label": "general"}]
    return persona_contexts  # NOTE: Creates ai_news for ALL personas: 321 raw_news × N personas = 321*N ai_news


async def _generate_with_quality_loop(
    raw_row: dict[str, Any],
    topic: str,
    profession: str | None,
    geo: str | None,
) -> dict[str, Any]:
    best_result: dict[str, Any] | None = None
    def _fallback_generated() -> dict[str, Any]:
        # Simple fallback that uses raw text/title when LLM unavailable or fails
        raw_text = str(raw_row.get("raw_text") or "")
        title = str(raw_row.get("title") or "").strip()

        # apply improved non-AI cleaning
        cleaned = simple_clean(raw_text)
        cleaned = fix_cut_words(cleaned)

        # create smart summary from cleaned text
        summary = smart_summary(cleaned)

        # optional lightweight highlight using title-derived keywords
        final_title = clean_title(title) or clean_title((summary or "").split("\n", 1)[0][:120])
        final_text = summary or (cleaned or simple_clean(raw_text[:2000]))
        if SMART_HIGHLIGHT_ENABLED and final_title and final_text:
            # derive keywords from title (simple heuristic)
            kws = [w for w in re.findall(r"\w+", final_title) if len(w) > 3 and w.lower() not in STOPWORDS]
            if kws:
                final_text = highlight_keywords(final_text, kws[:8])

        return {
            "final_title": final_title,
            "final_text": final_text,
            "category": str(raw_row.get("category") or "").strip() or None,
            "combined_score": 0.0,
            "ai_score": 0.0,
            "is_ai": False,
        }

    # If there is no AI key configured, return fallback immediately (AI is optional)
    ai_present = bool((settings.OPENAI_API_KEY or "").strip() or (settings.GEMINI_API_KEY or "").strip())
    if not ai_present:
        LOG.info(f"LLM keys not found, using raw fallback for raw_news_id={raw_row.get('id')}")
        return _fallback_generated()

    for rewrite_round in range(1, settings.PIPELINE_MAX_REWRITE_ROUNDS + 1):
        try:
            # Clean text before sending to AI
            clean_raw_text = clean_text(raw_row.get("raw_text") or "")
            cleaned_title = clean_text(raw_row.get("title") or "")

            # FIX: Limit LLM concurrency to max 3 concurrent calls
            async with _llm_semaphore:
                generated = await generate_news(
                    raw_text=clean_raw_text,
                    title=cleaned_title,
                    category=raw_row.get("category"),
                    target_persona=topic,
                    region=raw_row.get("region"),
                    profession=profession,
                    user_geo=geo,
                    rewrite_round=rewrite_round,
                )
        except Exception as e:
            LOG.exception(f"generate_news failed for raw_news_id={raw_row.get('id')} round={rewrite_round}: {e}")
            # try next round; if all rounds fail we'll fallback below
            generated = None

        if not generated:
            continue

        # Mark AI-generated payload explicitly
        try:
            generated["is_ai"] = True
        except Exception:
            pass

        combined_score = float(generated.get("combined_score", generated.get("ai_score", 0.0)))
        if best_result is None or combined_score > float(best_result.get("combined_score", 0.0)):
            best_result = generated

        if combined_score >= settings.PIPELINE_TARGET_SCORE:
            return generated

    # If we did not get any successful generation, always fallback to raw.
    # This keeps the pipeline progressing even under LLM rate-limits/outages.
    if best_result is None:
        LOG.warning(f"LLM generation failed, falling back to raw for raw_news_id={raw_row.get('id')}")
        return _fallback_generated()

    # If generated but score is too low, fallback to raw.
    if float(best_result.get("combined_score", 0.0)) < settings.PIPELINE_MIN_SCORE:
        LOG.warning(
            f"LLM generation score too low ({float(best_result.get('combined_score', 0.0)):.2f}), "
            f"falling back to raw for raw_news_id={raw_row.get('id')}"
        )
        return _fallback_generated()

    try:
        best_result.setdefault("is_ai", True)
    except Exception:
        pass

    return best_result


def _fix_encoding(text: str | None) -> str:
    """Fix UTF-8/Latin-1 encoding issues (Mojibake)."""
    if not text:
        return ""
    text = str(text)
    try:
        # Common case: UTF-8 text was decoded as Latin-1
        # Try to encode as Latin-1 (which accepts any byte) then decode as UTF-8
        return text.encode('latin1').decode('utf-8', errors='ignore')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


async def _upsert_ai_news_for_persona(
    session: AsyncSession,
    raw_row: dict[str, Any],
    persona_context: dict[str, str | None],
    generated: dict[str, Any] | None = None,
) -> int:
    topic = str(persona_context.get("topic") or "general").strip().lower()
    profession = str(persona_context.get("profession") or "").strip().lower() or None
    geo = str(persona_context.get("geo") or "").strip().lower() or None
    country_code = str(persona_context.get("country_code") or "").strip().upper() or None
    target_persona = str(
        persona_context.get("label") or _build_target_persona_label(topic, profession, geo, country_code)
    ).strip().lower()

    raw_news_id = raw_row["id"]
    logger.info(f"[UPSERT] START raw_news_id={raw_news_id} persona={target_persona}")

    # FIX START - Prevent duplicates: check if ai_news already exists for this raw_news + persona
    dup_check = await session.execute(
        text("SELECT id FROM ai_news WHERE raw_news_id = :raw_id AND target_persona = :persona LIMIT 1"),
        {"raw_id": raw_news_id, "persona": target_persona},
    )
    existing_id = dup_check.scalar_one_or_none()
    if existing_id:
        logger.info(f"[UPSERT] DUPLICATE raw_news_id={raw_news_id} persona={target_persona} existing_ai_news_id={existing_id}")
        return int(existing_id)
    # FIX END

    # Allow caller to provide a pre-generated payload (to enable concurrent LLM calls).
    if generated is None:
        generated = await _generate_with_quality_loop(raw_row, topic, profession, geo)

    # If generation failed, use fallback from raw text instead of raising
    # This ensures SOMETHING gets saved to ai_news
    if not generated:
        LOG.warning(f"[UPSERT] Generation failed for raw_news_id={raw_row.get('id')}, using raw text fallback")
        fallback_title = str(raw_row.get("title") or "Yangilik")
        fallback_text = str(raw_row.get("raw_text") or "")[:1000] or "Ma'lumot yo'q"
        generated = {
            "final_title": fallback_title,
            "final_text": fallback_text,
            "category": str(raw_row.get("category") or "general"),
            "combined_score": 0.0,
            "ai_score": 0.0,
            "is_ai": False,
        }
        print(f"[DEBUG] UPSERT FALLBACK: title={fallback_title[:50]}")

    # FIX: Ensure UTF-8 encoding for database storage
    final_title = _fix_encoding(generated.get("final_title"))
    final_text = _fix_encoding(generated.get("final_text"))

    params = {
        "raw_news_id": raw_row["id"],
        "target_persona": target_persona,
        "final_title": final_title,
        "final_text": final_text,
        "category": generated["category"],
        "ai_score": generated["combined_score"],
        "embedding_id": None,
        "vector_status": "pending",
    }

    # CRITICAL FIX: REMOVED aggressive cross-raw_news duplicate check
    # This check was preventing ai_news creation for different raw_news with similar titles
    # ONLY check for duplicates within same raw_news_id + target_persona (handled above)
    # The original code was returning existing ai_news from DIFFERENT raw_news, causing
    # raw_news to be marked 'generated' without creating new ai_news records.
    logger.info(f"[UPSERT] SKIPPING cross-raw_news duplicate check for raw_news_id={raw_news_id}")

    # Final duplicate check before INSERT/UPDATE
    existing_query = """
    SELECT id
    FROM ai_news
    WHERE raw_news_id = :raw_news_id
      AND target_persona = :target_persona
    ORDER BY id
    LIMIT 1
    """
    existing_result = await session.execute(text(existing_query), params)
    existing_id = existing_result.scalar_one_or_none()
    if existing_id:
        logger.info(f"[UPSERT] EXISTING raw_news_id={raw_news_id} persona={target_persona} ai_news_id={existing_id}")

    reserved_image_keys = await _load_reserved_image_keys(session, exclude_ai_news_id=existing_id)
    # Build media query prioritizing article title and category over persona/topic
    media_query = " ".join(
        part
        for part in [
            str(raw_row.get("title") or "").strip(),
            str(raw_row.get("category") or "").strip().lower() or None,
            topic,
            geo,
            country_code.lower() if country_code else None,
        ]
        if part
    ).strip()
    media_urls = await fetch_media_urls(
        media_query,
        limit=4,
        source_url=str(raw_row.get("source_url") or "").strip() or None,
        source_image_url=str(raw_row.get("image_url") or "").strip() or None,
    )
    # Ensure fetched URLs are normalized (add scheme, resolve protocol-less URLs)
    try:
        normalized_list: list[str] = []
        for raw in media_urls:
            try:
                norm = _normalize_candidate_url(raw)
            except Exception:
                norm = None
            if norm:
                normalized_list.append(norm)
            elif raw:
                normalized_list.append(str(raw).strip())
        media_urls = normalized_list
    except Exception:
        # best-effort: leave original list if normalization fails
        pass
    media_urls = _enforce_cross_post_unique_images(
        media_urls,
        reserved_image_keys,
        limit=4,
        seed_base=f"{raw_row['id']}:{target_persona}",
    )
    # Collapse multiple quality variants of the same image into a single best-quality URL.
    # Prefer items that appear early in the original ranking (0-based indices 0 or 1) when present.
    try:
        media_urls = _collapse_quality_variants(media_urls, prefer_indices=(0, 1))
    except Exception:
        # If quality collapse fails for any reason, fall back to original media_urls
        pass

    video_urls: list[str] = []
    is_sqlite = session.get_bind().dialect.name == "sqlite"
    # Store as JSON string in params. For Postgres we will convert JSON->text[] in SQL.
    params["image_urls"] = json.dumps(media_urls, ensure_ascii=False)
    params["video_urls"] = json.dumps(video_urls, ensure_ascii=False)

    if is_sqlite:
        img_sql = ":image_urls"
        vid_sql = ":video_urls"
    else:
        # PostgreSQL: convert JSON string parameter into text[] using jsonb_array_elements_text
        # Use CAST(:param AS jsonb) to avoid parser issues with '::' after a bind
        img_sql = "ARRAY(SELECT jsonb_array_elements_text(CAST(:image_urls AS jsonb)))"
        vid_sql = "ARRAY(SELECT jsonb_array_elements_text(CAST(:video_urls AS jsonb)))"

    if existing_id is not None:
        logger.info(f"[UPSERT] UPDATE existing_id={existing_id} raw_news_id={raw_news_id}")
        update_query = f"""
        UPDATE ai_news
        SET final_title = :final_title,
            final_text = :final_text,
            image_urls = {img_sql},
            video_urls = {vid_sql},
            category = :category,
            ai_score = :ai_score,
            embedding_id = :embedding_id,
            vector_status = :vector_status
        WHERE id = :id
        RETURNING id
        """
        update_result = await session.execute(text(update_query), {**params, "id": existing_id})
        updated_ai_news_id = update_result.scalar_one()
        logger.info(f"[UPSERT] UPDATED ai_news_id={updated_ai_news_id} raw_news_id={raw_news_id}")
        await session.commit()
        LOG.info("[AI] updated ai_news id=%s raw_news_id=%s", updated_ai_news_id, raw_news_id)
        await refresh_ai_news_embedding(
            session,
            updated_ai_news_id,
            title=str(generated.get("final_title") or ""),
            final_text=str(generated.get("final_text") or ""),
            category=str(generated.get("category") or None),
            target_persona=target_persona,
            raw_text=str(raw_row.get("raw_text") or ""),
            region=str(raw_row.get("region") or None),
        )
        return updated_ai_news_id

    insert_query = f"""
    INSERT INTO ai_news (
        raw_news_id,
        target_persona,
        final_title,
        final_text,
        image_urls,
        video_urls,
        category,
        ai_score,
        embedding_id,
        vector_status
    )
    VALUES (
        :raw_news_id,
        :target_persona,
        :final_title,
        :final_text,
        {img_sql},
        {vid_sql},
        :category,
        :ai_score,
        :embedding_id,
        :vector_status
    )
    RETURNING id
    """

    # FIX START - Handle unique constraint violation (concurrent insert protection)
    logger.info(f"[UPSERT] INSERTING raw_news_id={raw_news_id} persona={target_persona}")
    try:
        insert_result = await session.execute(text(insert_query), params)
        ai_news_id = insert_result.scalar_one()
        logger.info(f"[UPSERT] INSERTED ai_news_id={ai_news_id} raw_news_id={raw_news_id}")
        await session.commit()
        logger.info(f"[UPSERT] COMMITTED ai_news_id={ai_news_id} raw_news_id={raw_news_id}")
        LOG.info("[AI] created ai_news id=%s raw_news_id=%s", ai_news_id, raw_news_id)
    except IntegrityError as ie:
        # FIX: Another process inserted the same record concurrently
        await session.rollback()
        logger.warning(f"[UPSERT] IntegrityError: duplicate ai_news for raw_news_id={raw_news_id}, persona={target_persona}: {ie}")
        # Fetch the existing record
        existing_result = await session.execute(
            text("SELECT id FROM ai_news WHERE raw_news_id = :raw_id AND target_persona = :persona"),
            {"raw_id": raw_news_id, "persona": target_persona},
        )
        ai_news_id = existing_result.scalar_one()
        logger.info(f"[UPSERT] Using existing ai_news id={ai_news_id} after IntegrityError")
        # FIX END
    except Exception as e:
        # CRITICAL FIX: Log any other insert errors and re-raise
        logger.error(f"[UPSERT] INSERT FAILED raw_news_id={raw_news_id}: {type(e).__name__}: {e}")
        await session.rollback()
        raise
    # FIX END
    await refresh_ai_news_embedding(
        session,
        ai_news_id,
        title=str(generated.get("final_title") or ""),
        final_text=str(generated.get("final_text") or ""),
        category=str(generated.get("category") or None),
        target_persona=target_persona,
        raw_text=str(raw_row.get("raw_text") or ""),
        region=str(raw_row.get("region") or None),
    )
    return ai_news_id


async def _populate_user_feed_for_ai_news(
    session: AsyncSession,
    *,
    ai_news_id: int,
    ai_score: float,
    target_topic: str,
    target_profession: str | None,
    target_geo: str | None,
    target_country_code: str | None,
) -> int:
    normalized_profession = (target_profession or "").strip().lower()
    normalized_geo = (target_geo or "").strip().lower()
    normalized_country_code = (target_country_code or "").strip().upper()

    is_sqlite = session.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        query = """
        INSERT OR IGNORE INTO user_feed (user_id, ai_news_id, ai_score, created_at)
        SELECT
                u.id,
                :ai_news_id,
                :ai_score,
                CURRENT_TIMESTAMP
        FROM users u
        WHERE COALESCE(u.is_active, 1) = 1
            AND (
                :target_topic = 'general'
                OR EXISTS (
                    SELECT 1
                    FROM json_each(
                        CASE
                            WHEN json_valid(COALESCE(u.interests, '{}')) THEN COALESCE(u.interests, '{}')
                            ELSE '{}'
                        END,
                        '$.all_topics'
                    ) jt
                    WHERE LOWER(CAST(jt.value AS TEXT)) = :target_topic
                )
            )
            AND (
                :target_profession = ''
                OR LOWER(
                    COALESCE(
                        json_extract(
                            CASE
                                WHEN json_valid(COALESCE(u.interests, '{}')) THEN COALESCE(u.interests, '{}')
                                ELSE '{}'
                            END,
                            '$.profession'
                        ),
                        ''
                    )
                ) = :target_profession
            )
            AND (
                :target_geo = ''
                OR LOWER(COALESCE(u.location, '')) LIKE ('%' || :target_geo || '%')
            )
            AND (
                :target_country_code = ''
                OR UPPER(COALESCE(u.country_code, '')) = :target_country_code
            )
        """
    else:
        query = """
        INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
        SELECT
                u.id,
                :ai_news_id,
                :ai_score,
                NOW()
        FROM users u
        WHERE u.is_active = TRUE
            AND (
                :target_topic = 'general'
                OR (u.interests -> 'all_topics') ? :target_topic
            )
            AND (
                :target_profession = ''
                OR LOWER(COALESCE(u.interests ->> 'profession', '')) = :target_profession
            )
            AND (
                :target_geo = ''
                OR LOWER(COALESCE(u.location, '')) LIKE ('%' || :target_geo || '%')
            )
            AND (
                :target_country_code = ''
                OR UPPER(COALESCE(u.country_code, '')) = :target_country_code
            )
        ON CONFLICT (user_id, ai_news_id) DO NOTHING
        """
    params = {
        "ai_news_id": ai_news_id,
        "ai_score": ai_score,
        "target_topic": target_topic,
        "target_profession": normalized_profession or "",
        "target_geo": normalized_geo or "",
        "target_country_code": normalized_country_code or "",
    }

    # First, attempt the original (strict) insert
    result = await session.execute(text(query), params)
    inserted = int(result.rowcount or 0)
    if inserted:
        return inserted

    # If nothing matched, try a relaxed topic match that checks multiple topic keys
    if not is_sqlite:
        relaxed_query = """
        INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
        SELECT u.id, :ai_news_id, :ai_score, NOW()
        FROM users u
        WHERE u.is_active = TRUE
            AND (
                :target_topic = 'general'
                OR (
                    (u.interests -> 'all_topics') ? :target_topic
                    OR (u.interests -> 'topics') ? :target_topic
                    OR (u.interests -> 'custom_topics') ? :target_topic
                    OR LOWER(COALESCE(u.interests::text, '')) LIKE ('%' || :target_topic || '%')
                )
            )
            AND (
                :target_profession = ''
                OR LOWER(COALESCE(u.interests ->> 'profession', '')) = :target_profession
            )
            AND (
                :target_geo = ''
                OR LOWER(COALESCE(u.location, '')) LIKE ('%' || :target_geo || '%')
            )
            AND (
                :target_country_code = ''
                OR UPPER(COALESCE(u.country_code, '')) = :target_country_code
            )
        ON CONFLICT (user_id, ai_news_id) DO NOTHING
        """
        res2 = await session.execute(text(relaxed_query), params)
        inserted2 = int(res2.rowcount or 0)
        if inserted2:
            return inserted2

    else:
        # SQLite relaxed topic check (fallback to text search of interests)
        relaxed_query_sqlite = """
        INSERT OR IGNORE INTO user_feed (user_id, ai_news_id, ai_score, created_at)
        SELECT u.id, :ai_news_id, :ai_score, CURRENT_TIMESTAMP
        FROM users u
        WHERE COALESCE(u.is_active, 1) = 1
            AND (
                :target_topic = 'general'
                OR LOWER(COALESCE(u.interests, '')) LIKE ('%' || :target_topic || '%')
            )
            AND (
                :target_profession = ''
                OR LOWER(COALESCE(json_extract(COALESCE(u.interests, '{}'), '$.profession'), '')) = :target_profession
            )
            AND (
                :target_geo = ''
                OR LOWER(COALESCE(u.location, '')) LIKE ('%' || :target_geo || '%')
            )
            AND (
                :target_country_code = ''
                OR UPPER(COALESCE(u.country_code, '')) = :target_country_code
            )
        """
        res2 = await session.execute(text(relaxed_query_sqlite), params)
        inserted2 = int(res2.rowcount or 0)
        if inserted2:
            return inserted2

    # Final fallback: if still nothing, match any of profession / geo / country (OR), to avoid dropping audience completely
    if not is_sqlite:
        fallback_query = """
        INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
        SELECT u.id, :ai_news_id, :ai_score, NOW()
        FROM users u
        WHERE u.is_active = TRUE
            AND (
                (:target_profession != '' AND LOWER(COALESCE(u.interests ->> 'profession','')) = :target_profession)
                OR (:target_geo != '' AND LOWER(COALESCE(u.location,'')) LIKE ('%' || :target_geo || '%'))
                OR (:target_country_code != '' AND UPPER(COALESCE(u.country_code,'')) = :target_country_code)
            )
        ON CONFLICT (user_id, ai_news_id) DO NOTHING
        """
        res3 = await session.execute(text(fallback_query), params)
        return int(res3.rowcount or 0)
    else:
        fallback_query_sqlite = """
        INSERT OR IGNORE INTO user_feed (user_id, ai_news_id, ai_score, created_at)
        SELECT u.id, :ai_news_id, :ai_score, CURRENT_TIMESTAMP
        FROM users u
        WHERE COALESCE(u.is_active, 1) = 1
            AND (
                (:target_profession != '' AND LOWER(COALESCE(json_extract(COALESCE(u.interests, '{}'), '$.profession'), '')) = :target_profession)
                OR (:target_geo != '' AND LOWER(COALESCE(u.location,'')) LIKE ('%' || :target_geo || '%'))
                OR (:target_country_code != '' AND UPPER(COALESCE(u.country_code,'')) = :target_country_code)
            )
        """
        res3 = await session.execute(text(fallback_query_sqlite), params)
        return int(res3.rowcount or 0)


async def _schedule_ingestion_batch_async() -> dict[str, Any]:
    async with SessionLocal() as session:
        persona_contexts = await _load_cohort_personas(session)
        topics = list(dict.fromkeys([str(p.get("topic") or "general") for p in persona_contexts]))
        country_codes = [str(p.get("country_code") or "").strip().upper() for p in persona_contexts if p.get("country_code")]
        articles = await fetch_articles_for_topics(
            topics,
            settings.NEWS_FETCH_BATCH_SIZE,
            country_codes=country_codes,
        )

        if not articles and "general" not in topics:
            articles = await fetch_articles_for_topics(
                [*topics, "general"],
                settings.NEWS_FETCH_BATCH_SIZE,
                country_codes=country_codes,
            )

        queued = 0
        for article in articles:
            raw_news = await create_raw_news(session, article)
            if raw_news.get("process_status") in {"pending", "failed", None}:
                process_raw_news.delay(raw_news["id"], persona_contexts)
                queued += 1

        return {
            "fetched": len(articles),
            "queued": queued,
            "personas": [str(p.get("label") or p.get("topic") or "general") for p in persona_contexts],
        }


async def _cleanup_ai_products_async() -> dict[str, Any]:
    async with SessionLocal() as session:
        # Delete generated AI products older than configured retention
        ai_query = """
        DELETE FROM ai_news
        WHERE created_at < NOW() - make_interval(days => :retention_days)
        """
        result_ai = await session.execute(
            text(ai_query),
            {"retention_days": settings.AI_PRODUCT_RETENTION_DAYS},
        )

        # Delete raw_news older than configured raw retention (this will cascade to ai_news if FK set)
        raw_query = """
        DELETE FROM raw_news
        WHERE created_at < NOW() - make_interval(days => :raw_retention_days)
        """
        result_raw = await session.execute(
            text(raw_query),
            {"raw_retention_days": settings.RAW_NEWS_RETENTION_DAYS},
        )

        await session.commit()
        deleted_ai = int(result_ai.rowcount or 0)
        deleted_raw = int(result_raw.rowcount or 0)
        return {
            "deleted_ai_news": deleted_ai,
            "deleted_raw_news": deleted_raw,
            "ai_retention_days": settings.AI_PRODUCT_RETENTION_DAYS,
            "raw_retention_days": settings.RAW_NEWS_RETENTION_DAYS,
        }


async def _process_raw_news_async(
    raw_news_id: int,
    attempt: int,
    personas: list[dict[str, str | None]] | None = None,
) -> dict:
    async with SessionLocal() as session:
        lock_acquired = False
        try:
            lock_acquired = await _try_advisory_lock(session, raw_news_id)
            if not lock_acquired:
                logger.info("[PIPELINE] raw_news_id=%s locked by another worker", raw_news_id)
                return {"status": "skipped", "reason": "locked", "raw_news_id": raw_news_id}

            status_result = await session.execute(
                text("SELECT process_status FROM raw_news WHERE id = :raw_news_id"),
                {"raw_news_id": raw_news_id},
            )
            current_status = status_result.scalar_one_or_none()
            if current_status is None:
                return {"status": "failed", "reason": "raw_news_not_found", "raw_news_id": raw_news_id}

            if current_status in {"generated", "completed"}:
                existing_ai = await session.execute(
                    text("SELECT 1 FROM ai_news WHERE raw_news_id = :raw_id LIMIT 1"),
                    {"raw_id": raw_news_id},
                )
                if existing_ai.scalar_one_or_none() is not None:
                    logger.info("[PIPELINE] raw_news_id=%s already generated, skipping", raw_news_id)
                    return {"status": "skipped", "reason": "already_generated", "raw_news_id": raw_news_id}

            claimed = await _claim_raw_news_for_processing(session, raw_news_id)
            if not claimed:
                await session.rollback()
                logger.info("[PIPELINE] raw_news_id=%s already claimed or completed", raw_news_id)
                return {"status": "skipped", "reason": "already_claimed", "raw_news_id": raw_news_id}

            await session.commit()

            raw_row = await _fetch_raw_news(session, raw_news_id)
            if not raw_row:
                await _set_status(
                    session=session,
                    raw_news_id=raw_news_id,
                    status="failed",
                    error_message=f"raw_news id={raw_news_id} not found",
                )
                await session.commit()
                return {"status": "failed", "reason": "raw_news_not_found", "raw_news_id": raw_news_id}

            # FIX START: Remove duplicates and limit personas to prevent rate limiting
            cohort_personas = personas or await _load_cohort_personas(session)

            # Safety: Handle None
            cohort_personas = cohort_personas or []

            def _normalize_persona(p):
                if isinstance(p, dict):
                    return {
                        str(k): _normalize_persona(v)
                        for k, v in sorted(p.items(), key=lambda x: str(x[0]))
                    }
                if isinstance(p, list):
                    return [_normalize_persona(v) for v in p]
                if isinstance(p, (str, int, float, bool)) or p is None:
                    return p

                logger.warning(
                    "[PIPELINE] Unsupported persona type: %s -> converting to string",
                    type(p),
                )
                return str(p)

            original_count = len(cohort_personas)

            # Dedup + stable order + single serialization (performance optimized)
            persona_map = {}
            for p in cohort_personas:
                normalized = _normalize_persona(p)
                key = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
                if key in persona_map:
                    logger.warning("[PIPELINE] persona collision detected")
                persona_map[key] = p  # last wins (safe for identical personas)

            # Deterministic ordering to ensure stable persona selection across runs
            cohort_personas = [persona_map[k] for k in sorted(persona_map.keys())]

            logger.info(
                "[PIPELINE] personas deduplicated: %s -> %s",
                original_count,
                len(cohort_personas),
            )

            # Fallback with warning log
            if not cohort_personas:
                logger.warning("[PIPELINE] No personas found, using default")
                cohort_personas = [{"type": "general"}]

            # PRODUCTION FIX: Adaptive persona selection based on system load
            res = await session.execute(text("SELECT id FROM ai_news LIMIT 200"))
            ai_news_total = len(res.scalars().all())

            if ai_news_total < 50:
                personas_to_use = cohort_personas
            elif ai_news_total < 200:
                personas_to_use = cohort_personas[:2]
            else:
                personas_to_use = cohort_personas[:1]

            logger.info("[PIPELINE] ai_news_total=%s", ai_news_total)
            logger.info("[PIPELINE] personas_used=%s/%s", len(personas_to_use), len(cohort_personas))

            cohort_personas = personas_to_use
            # FIX END
            
            # MANDATORY FIX 3: Replace parallel execution with sequential loop
            ai_news_ids: list[int] = []
            saved_count = 0
            
            for persona_context in cohort_personas:
                topic = str(persona_context.get("topic") or "general").strip().lower()
                profession = str(persona_context.get("profession") or "").strip().lower() or None
                geo = str(persona_context.get("geo") or "").strip().lower() or None
                
                print(f"[PIPELINE] generating for: {persona_context}")
                
                # MANDATORY FIX 4: Add delay between LLM calls
                if saved_count > 0:
                    await asyncio.sleep(0.5)
                
                try:
                    # Idempotent upsert: if ai_news exists, this will reuse it without regenerating.
                    ai_news_id = await _upsert_ai_news_for_persona(session, raw_row, persona_context, generated=None)
                    ai_news_ids.append(ai_news_id)
                    saved_count += 1
                    
                    score_result = await session.execute(
                        text("SELECT ai_score FROM ai_news WHERE id = :id"),
                        {"id": ai_news_id},
                    )
                    ai_score = float(score_result.scalar_one_or_none() or 0.0)
                    await _populate_user_feed_for_ai_news(
                        session,
                        ai_news_id=ai_news_id,
                        ai_score=ai_score,
                        target_topic=topic,
                        target_profession=profession,
                        target_geo=geo,
                        target_country_code=str(persona_context.get("country_code") or "").strip().upper() or None,
                    )
                    
                    print(f"[PIPELINE] saved ai_news_id={ai_news_id} for {topic}")
                    # Continue to next persona (don't break) - create ai_news for ALL personas

                except Exception as e:
                    print(f"[PIPELINE] ERROR generating for {topic}: {e}")
                    logger.error(f"[PROCESS] persona {topic} generation error: {e}")
                    continue
            
            # MANDATORY FIX 10: Fail-fast if nothing saved
            if saved_count == 0:
                raise RuntimeError(f"Failed to save any ai_news for raw_news_id={raw_news_id}")
            # FIX END

            await _set_status(
                session=session,
                raw_news_id=raw_news_id,
                status="completed",
                error_message=None,
            )
            await session.commit()

            return {
                "status": "completed",
                "raw_news_id": raw_news_id,
                "ai_news_ids": ai_news_ids,
                "personas": [str(item.get("label") or item.get("topic") or "general") for item in cohort_personas],
            }

        except Exception as e:
            await session.rollback()
            try:
                await _set_status(
                    session=session,
                    raw_news_id=raw_news_id,
                    status="failed",
                    error_message=str(e)[:2000],
                )
                await session.commit()
            except Exception:
                logger.exception("failed to persist failed status raw_news_id=%s", raw_news_id)
            raise
        finally:
            if lock_acquired:
                try:
                    await _release_advisory_lock(session, raw_news_id)
                except Exception:
                    logger.exception("failed to release advisory lock raw_news_id=%s", raw_news_id)


@celery_app.task(
    name="brain.process_raw_news",
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, SQLAlchemyError),
    retry_backoff=True,
    retry_backoff_max=settings.API_RETRY_MAX_DELAY_SECONDS,
    retry_backoff_base=2,
    retry_jitter=True,
    max_retries=settings.API_RETRY_MAX_ATTEMPTS,
)
def process_raw_news(self, raw_news_id: int, personas: list[dict[str, str | None]] | None = None) -> dict:
    attempt = self.request.retries + 1
    logger.info("process_raw_news started raw_news_id=%s attempt=%s", raw_news_id, attempt)

    try:
        # FIX: Use asyncio.run() instead of manual loop management
        result = asyncio.run(_process_raw_news_async(raw_news_id, attempt, personas))
        logger.info("[WORKER] process_raw_news finished raw_news_id=%s result=%s", raw_news_id, result)
        return result
    except SQLAlchemyError as e:
        logger.exception("db error raw_news_id=%s attempt=%s error=%s", raw_news_id, attempt, e)
        raise
    except Exception as e:
        logger.exception("unexpected error raw_news_id=%s attempt=%s error=%s", raw_news_id, attempt, e)
        raise


@celery_app.task(
    name="brain.scheduled_ingestion",
    autoretry_for=(ConnectionError, TimeoutError, Exception),
    retry_backoff=True,
    retry_backoff_max=settings.API_RETRY_MAX_DELAY_SECONDS,
    retry_jitter=True,
    max_retries=2,  # Scheduled tasks - limited retries
)
def scheduled_ingestion() -> dict:
    logger.info("scheduled_ingestion tick started")
    try:
        # FIX: Use asyncio.run() instead of manual loop management
        result = asyncio.run(_schedule_ingestion_batch_async())
        logger.info("[WORKER] scheduled_ingestion finished result=%s", result)
        return result
    except Exception as e:
        logger.error("scheduled_ingestion failed: %s", e)
        raise



async def _schedule_feed_ingestion_async() -> dict[str, Any]:
    """Async wrapper to run feed_fetcher.ingest_many within an AsyncSession.

    Importing `app.backend.services.feed_fetcher` is done at runtime to avoid
    hard import-time dependency failures when optional parsing libs are not
    installed in some environments.
    """
    async with SessionLocal() as session:
        try:
            try:
                # Import at runtime to keep startup resilient
                from app.backend.services.feed_fetcher import ingest_many
            except Exception as e:
                logger.exception("feed_fetcher import failed", exc_info=True)
                return {"error": "feed_fetcher_import_failed", "detail": str(e)}

            result = await ingest_many(session)
            return {"ingested": result}
        except Exception as e:
            logger.exception("_schedule_feed_ingestion_async failed", exc_info=True)
            raise


@celery_app.task(
    name="brain.scheduled_feed_ingestion",
    autoretry_for=(ConnectionError, TimeoutError, Exception),
    retry_backoff=True,
    retry_backoff_max=settings.API_RETRY_MAX_DELAY_SECONDS,
    retry_jitter=True,
    max_retries=2,
)
def scheduled_feed_ingestion() -> dict:
    logger.info("scheduled_feed_ingestion tick started")
    try:
        # FIX: Use asyncio.run() instead of manual loop management
        result = asyncio.run(_schedule_feed_ingestion_async())
        logger.info("[WORKER] scheduled_feed_ingestion finished result=%s", result)
        return result
    except Exception as e:
        logger.error("scheduled_feed_ingestion failed: %s", e)
        raise


@celery_app.task(
    name="brain.scheduled_cleanup_ai_products",
    autoretry_for=(ConnectionError, TimeoutError, Exception),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=1,  # Cleanup is low priority
)
def scheduled_cleanup_ai_products() -> dict:
    logger.info("scheduled_cleanup_ai_products tick started")
    try:
        # FIX: Use asyncio.run() instead of manual loop management
        result = asyncio.run(_cleanup_ai_products_async())
        logger.info("[WORKER] scheduled_cleanup_ai_products finished result=%s", result)
        return result
    except Exception as e:
        logger.error("scheduled_cleanup_ai_products failed: %s", e)
        raise


@celery_app.task(
    name="recommender.refresh_user_embedding",
    bind=False,
    autoretry_for=(ConnectionError, TimeoutError, Exception),
    retry_backoff=True,
    max_retries=3,
)
def refresh_user_embedding_task(user_id: int, history_limit: int | None = None) -> dict:
    logger.info("recommender.refresh_user_embedding task started user_id=%s", user_id)
    try:
        # FIX: Use asyncio.run() instead of manual loop management
        async def _run():
            async with SessionLocal() as session:
                # Import at runtime to reduce import-time coupling
                from app.backend.services.recommender_service import refresh_user_embedding
                await refresh_user_embedding(session, int(user_id), history_limit=history_limit)

        asyncio.run(_run())
        logger.info("[WORKER] recommender.refresh_user_embedding finished user_id=%s", user_id)
        return {"status": "ok", "user_id": user_id}
    except Exception as e:
        logger.exception("recommender.refresh_user_embedding failed user_id=%s: %s", user_id, e)
        raise


# ---------------------------------------------------------------------------
# Full pipeline runner: process all pending raw_news
# ---------------------------------------------------------------------------


@celery_app.task(
    name="brain.tasks.pipeline_tasks.process_all_task",
    bind=False,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def process_all_task() -> dict:
    """Process all raw_news with status 'pending'.

    - Fetch pending raw_news
    - Skip if ai_news already exists (prevent duplicates)
    - Call internal async processor `_process_raw_news_async` for full pipeline
    - On success mark raw_news.process_status='processed'
    - On failure mark raw_news.process_status='failed' and record `error_message`

    Uses asyncio.run() to run async DB operations in the worker.
    """
    logger.info("[PIPELINE] process_all_task started")

    # FIX: Use asyncio.run() instead of manual loop management
    async def _run_all() -> dict:
        # FIX START - Observability: track execution time
        start_time = time.time()
        # FIX END
        processed = 0
        failed = 0
        skipped = 0

        async with SessionLocal() as session:
            recovered = await _recover_stale_processing_rows(
                session,
                int(os.getenv("PIPELINE_PROCESSING_TTL_MINUTES", "10")),
            )
            if recovered:
                await session.commit()
                logger.warning("[PIPELINE] recovered stale processing rows=%s", recovered)

            # Load pending raw_news ids
            status_debug = await session.execute(
                text("SELECT process_status, COUNT(*) FROM raw_news GROUP BY process_status")
            )
            logger.info("[PIPELINE] status_counts %s", status_debug.mappings().all())

            # FIX START - Check ai_news count and force processing if low
            ai_news_count_result = await session.execute(text("SELECT COUNT(*) FROM ai_news"))
            ai_news_count = ai_news_count_result.scalar_one() or 0

            # FIX - Force processing if ai_news < 50 (bypass status filters BUT keep LIMIT)
            if ai_news_count < 50:
                logger.warning("[PIPELINE] ai_news count low (%s < 50), forcing processing", ai_news_count)
                res = await session.execute(
                    text(
                        """
                        SELECT *
                        FROM raw_news
                                WHERE process_status IS NULL
                                    OR process_status IN ('pending', 'new', 'failed', 'generated', 'classified')
                        ORDER BY created_at DESC
                        LIMIT 50
                        """
                    )
                )
            else:
                # FIX - Increased batch size: 20 → 50
                # EXCLUDES 'parsed', 'classified', 'completed' to prevent duplicate processing
                # INCLUDES 'failed' with retry limit (see retry logic below)
                res = await session.execute(
                    text(
                        """
                        SELECT *
                        FROM raw_news
                                WHERE process_status IS NULL
                                    OR process_status IN ('pending', 'new', 'generated', 'classified')
                                    OR (process_status = 'failed' AND COALESCE(attempt_count, 0) < 3)
                        ORDER BY created_at DESC
                        LIMIT 50
                        """
                    )
                )
            # FIX END
            rows = res.mappings().all()

            # FIX START - Enhanced logging with counts
            fetched_count = len(rows)
            logger.info("[PIPELINE] fetched=%s ai_news_count=%s", fetched_count, ai_news_count)
            # FIX END
            pending_ids = [int(r["id"]) for r in rows]

            if not pending_ids:
                return {"status": "completed", "processed": 0, "failed": 0, "skipped": 0, "total": 0}

            # Batch processing: limit work per run to avoid long-running tasks
            batch_size = int(os.getenv("PIPELINE_BATCH_SIZE", "100"))
            total_pending = len(pending_ids)
            if batch_size and total_pending > batch_size:
                pending_ids = pending_ids[:batch_size]

            logger.info("[PIPELINE] Processing batch total=%s", len(pending_ids))

            # FIX START - Process in parallel with asyncio.gather for speed
            async def process_single(raw_id: int) -> dict:
                """Process a single raw_news item with retry-safe logic."""
                try:
                    logger.info("[PIPELINE] processing raw_news_id=%s", raw_id)

                    timeout_seconds = int(os.getenv("PIPELINE_PROCESS_TIMEOUT", str(settings.CELERY_TASK_TIME_LIMIT)))
                    # Per-row exponential backoff + jitter to avoid thundering herd on retries
                    try:
                        async with SessionLocal() as backoff_session:
                            ac_res = await backoff_session.execute(
                                text("SELECT COALESCE(attempt_count, 0) FROM raw_news WHERE id = :id"),
                                {"id": raw_id},
                            )
                            attempt_count = int(ac_res.scalar_one_or_none() or 0)
                    except Exception:
                        attempt_count = 0
                    backoff_base = min(2 ** max(0, attempt_count), 30)
                    delay_seconds = float(backoff_base) + random.uniform(0, 1)
                    await asyncio.sleep(delay_seconds)
                    try:
                        result = await asyncio.wait_for(
                            _process_raw_news_async(raw_id, attempt=1),
                            timeout=timeout_seconds,
                        )
                    except asyncio.TimeoutError:
                        logger.error("[PIPELINE] timeout raw_news_id=%s", raw_id)
                        return {"status": "failed", "raw_id": raw_id, "created": 0, "reason": "timeout"}

                    if not result:
                        return {"status": "failed", "raw_id": raw_id, "created": 0, "reason": "empty_result"}

                    if result.get("status") == "skipped":
                        return {"status": "skipped", "raw_id": raw_id, "created": 0}

                    if result.get("status") not in {"generated", "completed"}:
                        return {"status": "failed", "raw_id": raw_id, "created": 0, "reason": "generation_failed"}

                    created_count = len(result.get("ai_news_ids") or [])
                    if created_count == 0:
                        return {"status": "failed", "raw_id": raw_id, "created": 0, "reason": "no_ai_news_created"}

                    async with SessionLocal() as update_session:
                        await update_session.execute(
                            text("UPDATE raw_news SET process_status = :st, error_message = NULL WHERE id = :id"),
                            {"st": "completed", "id": raw_id},
                        )
                        await update_session.commit()

                    logger.info("[PIPELINE] COMPLETED raw_news_id=%s ai_news_count=%s", raw_id, created_count)
                    return {"status": "processed", "raw_id": raw_id, "created": created_count}

                except Exception:
                    logger.exception("[PIPELINE] failed raw_news_id=%s", raw_id)
                    return {"status": "failed", "raw_id": raw_id, "created": 0}

            # FIX - Parallel processing with limited concurrency
            semaphore = asyncio.Semaphore(5)  # Max 5 concurrent

            async def process_with_semaphore(raw_id: int) -> dict:
                async with semaphore:
                    return await process_single(raw_id)

            results = await asyncio.gather(*[process_with_semaphore(rid) for rid in pending_ids])

            # FIX - Aggregate results
            processed = sum(1 for r in results if r["status"] == "processed")
            failed = sum(1 for r in results if r["status"] == "failed")
            total_created = sum(r.get("created", 0) for r in results)
            skipped = len(pending_ids) - processed - failed

            # FIX START - Record metrics and health
            end_time = time.time()
            latency_ms = (end_time - start_time) * 1000 if 'start_time' in locals() else 0

            health_monitor.record_pipeline_run(
                fetched=fetched_count,
                created=total_created,
                processed=processed,
                failed=failed,
                skipped=skipped,
                latency_ms=latency_ms,
            )

            # Update metrics
            await metrics.increment("pipeline.runs", 1)
            await metrics.increment("pipeline.processed", processed)
            await metrics.increment("pipeline.failed", failed)
            await metrics.increment("pipeline.created", total_created)
            await metrics.gauge("pipeline.ai_news_total", ai_news_count + total_created)

            # Structured logging
            obs_logger.info(
                "Pipeline batch completed",
                fetched=fetched_count,
                created=total_created,
                processed=processed,
                failed=failed,
                skipped=skipped,
                total=len(pending_ids),
                latency_ms=round(latency_ms, 2),
                ai_news_total=ai_news_count + total_created,
            )
            # FIX END

            return {"status": "completed", "processed": processed, "failed": failed, "skipped": skipped, "total": len(pending_ids), "created": total_created}

    result = asyncio.run(_run_all())
    logger.info(
        "[PIPELINE] process_all_task finished processed=%s failed=%s skipped=%s total=%s",
        result.get("processed"),
        result.get("failed"),
        result.get("skipped"),
        result.get("total"),
    )
    return result
