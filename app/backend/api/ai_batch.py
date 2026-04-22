import json
import hashlib
import logging
import re
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from openai import OpenAI

from app.backend.core.config import settings
from app.backend.core.redis_client import redis_client

router = APIRouter()

logger = logging.getLogger(__name__)


class NewsItem(BaseModel):
    id: int
    title: str
    content: str


class BatchRequest(BaseModel):
    news: List[NewsItem]
    user_id: Optional[int] = None
    user_profile: Optional[Dict[str, Any]] = None


MAX_BATCH = 10
BASE_TTL = 60 * 60 * 48  # 48 hours
PERSONAL_TTL = 60 * 60 * 12  # 12 hours


def extract_json(text: str) -> List[Dict[str, Any]]:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return []
    return []


def profile_hash(profile: Optional[Dict[str, Any]]) -> str:
    if not profile:
        return "anon"
    raw = json.dumps(profile, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def news_hash(news: NewsItem) -> str:
    raw = f"{news.id}|{news.title}|{(news.content or '')[:500]}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def base_cache_key(news: NewsItem) -> str:
    return f"news:{news.id}:base:{news_hash(news)}"


def user_cache_key(news: NewsItem, user_id: Optional[int], user_profile: Optional[Dict[str, Any]]) -> str:
    ph = profile_hash(user_profile)
    uid = str(user_id) if user_id else "anon"
    return f"news:{news.id}:user:{uid}:{ph}"


def _openai_client() -> OpenAI:
    key = (settings.OPENAI_API_KEY or "").strip()
    return OpenAI(api_key=key) if key else OpenAI()


@router.post("/ai/batch")
async def batch_ai(request: BatchRequest) -> Dict[str, Any]:
    news_list = request.news or []
    user_id = request.user_id
    user_profile = request.user_profile

    if not news_list:
        return {"data": []}

    if len(news_list) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"Too many items (max {MAX_BATCH})")

    cached_results: Dict[int, Any] = {}
    bases: Dict[int, Any] = {}
    to_generate_base: List[NewsItem] = []
    to_personalize: List[NewsItem] = []
    user_needed = bool(user_id or user_profile)

    # 1) Check user-specific cache first, then base cache
    for n in news_list:
        # check user cache
        if user_needed:
            ukey = user_cache_key(n, user_id, user_profile)
            try:
                cached_user = await redis_client.get(ukey)
            except Exception:
                logger.exception("Redis GET (user) failed for %s; treating as miss", ukey)
                cached_user = None

            if cached_user:
                try:
                    cached_results[n.id] = json.loads(cached_user)
                    continue
                except Exception:
                    logger.exception("Failed to decode cached user result for %s", ukey)

        # check base cache
        bkey = base_cache_key(n)
        try:
            cached_base = await redis_client.get(bkey)
        except Exception:
            logger.exception("Redis GET (base) failed for %s; treating as miss", bkey)
            cached_base = None

        if cached_base:
            try:
                base_item = json.loads(cached_base)
                bases[n.id] = base_item
                if user_needed:
                    to_personalize.append(n)
                else:
                    cached_results[n.id] = base_item
            except Exception:
                logger.exception("Failed to decode base cached result for %s", bkey)
                to_generate_base.append(n)
        else:
            to_generate_base.append(n)

    # 2) Generate base summaries for missing ones
    if to_generate_base:
        combined_text = ""
        for i, n in enumerate(to_generate_base):
            combined_text += f"\nNEWS {i+1}:\nID: {n.id}\nTITLE: {n.title}\nCONTENT: {n.content[:1500]}\n"

        base_prompt = f"""
You are a neutral news editor.

For each news below produce a neutral summary (max 3 sentences) and assign a category (politics, economy, sports, tech, other).

Return ONLY JSON list like:
[
  {{ "id": 1, "summary": "...", "category": "..." }}
]

News:
{combined_text}
"""

        client = _openai_client()
        try:
            resp = await run_in_threadpool(
                lambda: client.chat.completions.create(
                    model=(settings.OPENAI_MODEL or "gpt-4o-mini"),
                    messages=[{"role": "user", "content": base_prompt}],
                    temperature=0.2,
                    timeout=15,
                )
            )
            content = resp.choices[0].message.content
            parsed = extract_json(content)
        except Exception:
            logger.exception("OpenAI base generation failed; using fallback truncation for base summaries")
            parsed = []

        # Map parsed results by id
        parsed_map: Dict[int, Dict[str, Any]] = {}
        for item in parsed:
            try:
                parsed_map[int(item.get("id"))] = item
            except Exception:
                continue

        # Save base results (either parsed or fallback)
        for n in to_generate_base:
            item = parsed_map.get(n.id)
            if not item:
                item = {"id": n.id, "summary": (n.content or "")[:200].strip() + "...", "category": "other"}

            bkey = base_cache_key(n)
            try:
                await redis_client.set(bkey, json.dumps(item, ensure_ascii=False), ex=BASE_TTL)
            except Exception:
                logger.exception("Redis SET (base) failed for %s", bkey)

            bases[n.id] = item
            if user_needed:
                to_personalize.append(n)
            else:
                cached_results[n.id] = item

    # 3) Personalize where needed
    if user_needed and to_personalize:
        # remove duplicates
        unique_personalize = []
        seen = set()
        for n in to_personalize:
            if n.id in seen:
                continue
            seen.add(n.id)
            # skip if we already have user-specific cached result
            ukey = user_cache_key(n, user_id, user_profile)
            try:
                if await redis_client.get(ukey):
                    try:
                        cached_results[n.id] = json.loads((await redis_client.get(ukey)))
                        continue
                    except Exception:
                        pass
            except Exception:
                logger.exception("Redis GET (user pre-check) failed for %s", ukey)

            unique_personalize.append(n)

        if unique_personalize:
            # Build personalization prompt using base summaries
            combined = ""
            for i, n in enumerate(unique_personalize):
                base = bases.get(n.id) or {"summary": (n.content or "")[:200]}
                combined += f"\nITEM {i+1}:\nID: {n.id}\nBASE_SUMMARY: {base.get('summary')}\nTITLE: {n.title}\nCONTENT: {n.content[:1200]}\n"

            personalization_note = ""
            if user_id:
                personalization_note = f"Personalize the tone for user id={user_id}."
            elif user_profile:
                personalization_note = f"Personalize according to user profile: {json.dumps(user_profile, ensure_ascii=False)}."

            personal_prompt = f"""
You are a content adapter.

{personalization_note}

For each item below adapt the BASE_SUMMARY to the user (tone, emphasis) while keeping it concise (max 3 sentences). Keep or refine category if needed.

Return ONLY JSON list like:
[
  {{ "id": 1, "summary": "...", "category": "..." }}
]

Items:
{combined}
"""

            client = _openai_client()
            try:
                resp = await run_in_threadpool(
                    lambda: client.chat.completions.create(
                        model=(settings.OPENAI_MODEL or "gpt-4o-mini"),
                        messages=[{"role": "user", "content": personal_prompt}],
                        temperature=0.3,
                        timeout=15,
                    )
                )
                content = resp.choices[0].message.content
                parsed_personal = extract_json(content)
            except Exception:
                logger.exception("OpenAI personalization failed; using base as fallback for personalization")
                parsed_personal = []

            parsed_personal_map: Dict[int, Dict[str, Any]] = {}
            for it in parsed_personal:
                try:
                    parsed_personal_map[int(it.get("id"))] = it
                except Exception:
                    continue

            # Save personalized results
            for n in unique_personalize:
                pitem = parsed_personal_map.get(n.id)
                if not pitem:
                    # fallback: use base
                    base_item = bases.get(n.id) or {"id": n.id, "summary": (n.content or "")[:200].strip() + "...", "category": "other"}
                    pitem = {"id": n.id, "summary": base_item.get("summary"), "category": base_item.get("category", "other")}

                ukey = user_cache_key(n, user_id, user_profile)
                try:
                    await redis_client.set(ukey, json.dumps(pitem, ensure_ascii=False), ex=PERSONAL_TTL)
                except Exception:
                    logger.exception("Redis SET (user) failed for %s", ukey)

                cached_results[n.id] = pitem

    # 4) Final assembly in original order
    ordered = [cached_results.get(n.id) for n in news_list if n.id in cached_results]
    logger.info("[AI] total=%s returned=%s", len(news_list), len(ordered))
    return {"data": ordered}
