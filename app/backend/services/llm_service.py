import asyncio
import json
import logging
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
    rewrite_round: int = 1,
) -> GeneratedNews:
    fallback = {
        "final_title": f"[AI] {title}",
        "final_text": (raw_text or "")[:1200],
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
        "Siz yangiliklarni qisqa va aniq formatga o'tkazuvchi AI yozuvchisiz. "
        "FAqat O'ZBEK tilida yozing. Inglizcha yoki ruscha so'zlarni minimallashtiring. "
        "Natija faqat JSON bo'lsin va quyidagi kalitlarga ega bo'lsin: "
        "final_title, final_text, ai_score, category, target_persona. "
        "Matn faktlarga asoslangan, lo'nda va o'qilishi oson bo'lsin. "
        "Agar rewrite_round > 1 bo'lsa, uslubni yanada tiniqroq va qiziqroq qiling."
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
            "final_text": str(data.get("final_text") or fallback["final_text"]),
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
                        "Matnni faqat O'zbek tilida saqlang.",
                        "Aniqlik, ravonlik va auditoriyaga moslikni yaxshilang.",
                        "Qisqa va faktlarga asoslangan shaklni saqlang.",
                        "0 dan 10 gacha gemini_score bering.",
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
                "final_text": str(gemini_data.get("final_text") or primary_output["final_text"]),
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