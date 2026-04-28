import asyncio
import hashlib
import json
import logging
import re
import os
from typing import Optional, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

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

logger = logging.getLogger(__name__)
LOG = logger


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
    return persona_contexts[:1]  # DEBUG: limit to 1 persona for speed


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

    # Prevent creating near-duplicate ai_news: check title and text collisions
    is_sqlite = session.get_bind().dialect.name == "sqlite"
    candidate_title = str(params.get("final_title") or "").strip()
    candidate_text = str(params.get("final_text") or "").strip()
    # Use the original raw row image as a candidate for duplicate detection.
    # `media_urls` is computed later; using `raw_row` keeps duplicate check deterministic
    # and avoids referencing an undefined variable.
    candidate_image = str(raw_row.get("image_url") or "").strip()

    if candidate_title or candidate_text or candidate_image:
        if is_sqlite:
            dup_query = """
            SELECT id FROM ai_news
            WHERE (final_title = :final_title)
               OR (substr(final_text,1,200) = substr(:final_text,1,200))
               OR (image_urls IS NOT NULL AND image_urls LIKE '%' || :candidate_image || '%')
            LIMIT 1
            """
            dup_params = {"final_title": candidate_title, "final_text": candidate_text, "candidate_image": candidate_image or ""}
        else:
            dup_query = """
            SELECT id FROM ai_news
            WHERE LOWER(TRIM(final_title)) = LOWER(TRIM(:final_title))
               OR LOWER(SUBSTR(final_text,1,200)) = LOWER(SUBSTR(:final_text,1,200))
               OR (image_urls IS NOT NULL AND image_urls::text ILIKE '%' || :candidate_image || '%')
            LIMIT 1
            """
            dup_params = {"final_title": candidate_title, "final_text": candidate_text, "candidate_image": candidate_image or ""}

        try:
            dup_result = await session.execute(text(dup_query), dup_params)
            dup_id = dup_result.scalar_one_or_none()
            if dup_id is not None:
                # Duplicate detected; return existing id instead of inserting a new row
                return int(dup_id)
        except Exception:
            # If duplicate check fails, continue with insert; don't block ingestion
            pass

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
        print("[DEBUG] saving to ai_news")
        await session.commit()
        print("[DEBUG] commit done")
        print("[AI] saved to ai_news")
        LOG.info("[AI] saved to ai_news id=%s raw_news_id=%s", updated_ai_news_id, raw_row.get("id"))
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
    insert_result = await session.execute(text(insert_query), params)
    ai_news_id = insert_result.scalar_one()
    print("[DEBUG] saving to ai_news")
    await session.commit()
    print("[DEBUG] commit done")
    print("[AI] saved to ai_news")
    LOG.info("[AI] saved to ai_news id=%s raw_news_id=%s", ai_news_id, raw_row.get("id"))
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
        INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
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
            AND NOT EXISTS (
                SELECT 1
                FROM user_feed uf
                WHERE uf.user_id = u.id
                    AND uf.ai_news_id = :ai_news_id
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
            AND NOT EXISTS (
                SELECT 1
                FROM user_feed uf
                WHERE uf.user_id = u.id
                    AND uf.ai_news_id = :ai_news_id
            )
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
            AND NOT EXISTS (
                SELECT 1 FROM user_feed uf WHERE uf.user_id = u.id AND uf.ai_news_id = :ai_news_id
            )
        """
        res2 = await session.execute(text(relaxed_query), params)
        inserted2 = int(res2.rowcount or 0)
        if inserted2:
            return inserted2

    else:
        # SQLite relaxed topic check (fallback to text search of interests)
        relaxed_query_sqlite = """
        INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
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
            AND NOT EXISTS (
                SELECT 1 FROM user_feed uf WHERE uf.user_id = u.id AND uf.ai_news_id = :ai_news_id
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
            AND NOT EXISTS (
                SELECT 1 FROM user_feed uf WHERE uf.user_id = u.id AND uf.ai_news_id = :ai_news_id
            )
        """
        res3 = await session.execute(text(fallback_query), params)
        return int(res3.rowcount or 0)
    else:
        fallback_query_sqlite = """
        INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
        SELECT u.id, :ai_news_id, :ai_score, CURRENT_TIMESTAMP
        FROM users u
        WHERE COALESCE(u.is_active, 1) = 1
            AND (
                (:target_profession != '' AND LOWER(COALESCE(json_extract(COALESCE(u.interests, '{}'), '$.profession'), '')) = :target_profession)
                OR (:target_geo != '' AND LOWER(COALESCE(u.location,'')) LIKE ('%' || :target_geo || '%'))
                OR (:target_country_code != '' AND UPPER(COALESCE(u.country_code,'')) = :target_country_code)
            )
            AND NOT EXISTS (
                SELECT 1 FROM user_feed uf WHERE uf.user_id = u.id AND uf.ai_news_id = :ai_news_id
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
        try:
            await _set_status(
                session=session,
                raw_news_id=raw_news_id,
                status="classified",
                error_message=None,
                attempt_count=attempt,
            )
            await session.commit()

            raw_row = await _fetch_raw_news(session, raw_news_id)
            if not raw_row:
                await _set_status(
                    session=session,
                    raw_news_id=raw_news_id,
                    status="failed",
                    error_message=f"raw_news id={raw_news_id} not found",
                    attempt_count=attempt,
                )
                await session.commit()
                return {"status": "failed", "reason": "raw_news_not_found", "raw_news_id": raw_news_id}

            # FIX START: Remove duplicates and limit personas to prevent rate limiting
            cohort_personas = personas or await _load_cohort_personas(session)
            
            # MANDATORY FIX 1: Remove duplicate personas
            cohort_personas = list(dict.fromkeys(tuple(sorted(p.items())) for p in cohort_personas))
            cohort_personas = [dict(t) for t in cohort_personas]
            
            # MANDATORY FIX 2: Limit personas (temporary safety)
            cohort_personas = cohort_personas[:1]
            
            print("[PIPELINE] personas:", cohort_personas)
            
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
                    # Sequential generation instead of parallel
                    generated = await _generate_with_quality_loop(raw_row, topic, profession, geo)
                    
                    # MANDATORY FIX 6: Check generation result
                    if not generated:
                        print(f"[PIPELINE] generation failed for {topic}, using fallback")
                        # MANDATORY FIX 8: Force DB save with fallback values
                        fallback_title = str(raw_row.get("title") or "test")
                        fallback_text = str(raw_row.get("raw_text") or "test")[:1000]
                        generated = {
                            "final_title": fallback_title,
                            "final_text": fallback_text,
                            "category": str(raw_row.get("category") or "general"),
                            "combined_score": 0.0,
                            "ai_score": 0.0,
                            "is_ai": False,
                        }
                    
                    # MANDATORY FIX 8: Ensure DB save happens
                    ai_news_id = await _upsert_ai_news_for_persona(session, raw_row, persona_context, generated=generated)
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
                    
                    # MANDATORY FIX 9: Stop after first success
                    break
                    
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
                status="generated",
                error_message=None,
                attempt_count=attempt,
            )
            await session.commit()

            return {
                "status": "generated",
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
                    attempt_count=attempt,
                )
                await session.commit()
            except Exception:
                logger.exception("failed to persist failed status raw_news_id=%s", raw_news_id)
            raise


@celery_app.task(
    name="brain.process_raw_news",
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, Exception),
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
        # Run async coroutine in a fresh event loop to avoid coroutine warnings
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_process_raw_news_async(raw_news_id, attempt, personas))
        finally:
            try:
                loop.close()
            except Exception:
                pass
        logger.info("process_raw_news finished raw_news_id=%s result=%s", raw_news_id, result)
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
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_schedule_ingestion_batch_async())
        finally:
            try:
                loop.close()
            except Exception:
                pass
        logger.info("scheduled_ingestion tick finished result=%s", result)
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
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_schedule_feed_ingestion_async())
        finally:
            try:
                loop.close()
            except Exception:
                pass
        logger.info("scheduled_feed_ingestion tick finished result=%s", result)
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
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_cleanup_ai_products_async())
        finally:
            try:
                loop.close()
            except Exception:
                pass
        logger.info("scheduled_cleanup_ai_products tick finished result=%s", result)
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
        loop = asyncio.new_event_loop()
        try:
            async def _run():
                async with SessionLocal() as session:
                    # Import at runtime to reduce import-time coupling
                    from app.backend.services.recommender_service import refresh_user_embedding

                    await refresh_user_embedding(session, int(user_id), history_limit=history_limit)

            result = loop.run_until_complete(_run())
        finally:
            try:
                loop.close()
            except Exception:
                pass
        logger.info("recommender.refresh_user_embedding finished user_id=%s", user_id)
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

    Uses its own event loop (no asyncio.run) to run async DB operations in the worker.
    """
    print("[DEBUG] process_all_task started")
    logger.info("[DEBUG] process_all_task started")

    # Create a new event loop via the event loop policy to avoid interfering
    # with any existing global loop. We'll ensure the loop is closed safely.
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        async def _run_all() -> dict:
            processed = 0
            failed = 0
            skipped = 0

            async with SessionLocal() as session:
                # Load pending raw_news ids
                status_debug = await session.execute(
                    text("SELECT process_status, COUNT(*) FROM raw_news GROUP BY process_status")
                )
                print(f"[PROCESS_ALL] status_counts {status_debug.mappings().all()}")

                sample_debug = await session.execute(
                    text("SELECT id, process_status, title FROM raw_news ORDER BY id DESC LIMIT 10")
                )
                print(f"[PROCESS_ALL] sample_rows {sample_debug.mappings().all()}")

                res = await session.execute(
                    text(
                        """
                        SELECT *
                        FROM raw_news
                        WHERE process_status = 'pending'
                        ORDER BY id ASC
                        """
                    )
                )
                rows = res.mappings().all()

                if not rows:
                    res = await session.execute(
                        text(
                            """
                            SELECT *
                            FROM raw_news
                            WHERE process_status IS NULL OR process_status IN ('pending', 'new', 'parsed')
                            ORDER BY id ASC
                            """
                        )
                    )
                    rows = res.mappings().all()

                print(f"[DEBUG] found {len(rows)} raw_news")
                print(f"[PROCESS_ALL] found {len(rows)} rows")
                pending_ids = [int(r["id"]) for r in rows]

                if not pending_ids:
                    return {"status": "completed", "processed": 0, "failed": 0, "skipped": 0, "total": 0}

                # Batch processing: limit work per run to avoid long-running tasks
                batch_size = int(os.getenv("PIPELINE_BATCH_SIZE", "100"))
                total_pending = len(pending_ids)
                if batch_size and total_pending > batch_size:
                    pending_ids = pending_ids[:batch_size]

                logger.info("Processing batch total=%s total_pending=%s", len(pending_ids), total_pending)

                for raw_id in pending_ids:
                    try:
                        print(f"[DEBUG] processing raw_news_id={raw_id}")
                        logger.info("[DEBUG] processing raw_news_id=%s", raw_id)
                        # Prevent duplicates: skip if ai_news already exists for raw_news
                        dup = await session.execute(
                            text("SELECT 1 FROM ai_news WHERE raw_news_id = :id LIMIT 1"),
                            {"id": raw_id},
                        )
                        if dup.scalar_one_or_none() is not None:
                            await session.execute(
                                text("UPDATE raw_news SET process_status = :st WHERE id = :id"),
                                {"st": "processed", "id": raw_id},
                            )
                            await session.commit()
                            skipped += 1
                            continue

                        # Call main async processor (handles generation, upsert, feed population)
                        # Add a per-item timeout to avoid stuck processing
                        timeout_seconds = int(os.getenv("PIPELINE_PROCESS_TIMEOUT", str(settings.CELERY_TASK_TIME_LIMIT)))
                        try:
                            result = await asyncio.wait_for(
                                _process_raw_news_async(raw_id, attempt=1),
                                timeout=timeout_seconds,
                            )
                        except asyncio.TimeoutError as e:
                            await session.execute(
                                text("UPDATE raw_news SET process_status = :st, error_message = :err WHERE id = :id"),
                                {"st": "failed", "err": f"timeout after {timeout_seconds}s", "id": raw_id},
                            )
                            await session.commit()
                            logger.error("Processing timed out raw_news_id=%s timeout=%s", raw_id, timeout_seconds)
                            failed += 1
                            continue
                        except Exception as e:
                            # Mark failed and continue
                            await session.execute(
                                text("UPDATE raw_news SET process_status = :st, error_message = :err WHERE id = :id"),
                                {"st": "failed", "err": str(e)[:2000], "id": raw_id},
                            )
                            await session.commit()
                            logger.exception("Processing failed raw_news_id=%s error=%s", raw_id, e)
                            failed += 1
                            continue

                        # If processor returned falsy or non-generated status -> fail
                        if not result or result.get("status") != "generated":
                            await session.execute(
                                text("UPDATE raw_news SET process_status = :st, error_message = :err WHERE id = :id"),
                                {"st": "failed", "err": "generation_failed", "id": raw_id},
                            )
                            await session.commit()
                            failed += 1
                            continue
                        print(f"[DEBUG] generate_news result={str(result)[:300]}")

                        # Success — mark processed
                        await session.execute(
                            text("UPDATE raw_news SET process_status = :st, error_message = NULL WHERE id = :id"),
                            {"st": "processed", "id": raw_id},
                        )
                        await session.commit()
                        print("[DEBUG] commit done")
                        processed += 1

                    except Exception as e:
                        # Catch-all safety: ensure item does not remain pending
                        try:
                            await session.execute(
                                text("UPDATE raw_news SET process_status = :st, error_message = :err WHERE id = :id"),
                                {"st": "failed", "err": str(e)[:2000], "id": raw_id},
                            )
                            await session.commit()
                        except Exception:
                            # suppress commit errors here — log and continue
                            logger.exception("Failed to persist failure status raw_news_id=%s error=%s", raw_id, e)
                        logger.exception("Processing failed raw_news_id=%s error=%s", raw_id, e)
                        failed += 1

                return {"status": "completed", "processed": processed, "failed": failed, "skipped": skipped, "total": len(pending_ids)}

        # Run the batch and ensure the loop is closed safely
        try:
            result = loop.run_until_complete(_run_all())
        finally:
            try:
                loop.close()
            except Exception:
                pass

        logger.info(
            "process_all_task finished processed=%s failed=%s skipped=%s total=%s",
            result.get("processed"),
            result.get("failed"),
            result.get("skipped"),
            result.get("total"),
        )
        return result
    finally:
        try:
            asyncio.set_event_loop(None)
        except Exception:
            pass
