import asyncio
import json
import logging
from typing import TypedDict

import google.generativeai as genai
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

    if not settings.DEEPSEEK_API_KEY:
        return fallback

    client = AsyncOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )

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
            model="deepseek-chat",
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
        deepseek_output = {
            "final_title": str(data.get("final_title") or fallback["final_title"]),
            "final_text": str(data.get("final_text") or fallback["final_text"]),
            "ai_score": float(data.get("ai_score") or fallback["ai_score"]),
            "category": str(data.get("category") or fallback["category"]),
            "target_persona": str(data.get("target_persona") or fallback["target_persona"]),
            "deepseek_score": float(data.get("ai_score") or fallback["deepseek_score"]),
            "gemini_score": fallback["gemini_score"],
            "combined_score": float(data.get("ai_score") or fallback["combined_score"]),
        }

        if not settings.GEMINI_API_KEY:
            return deepseek_output

        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            gemini_model = genai.GenerativeModel("gemini-1.5-flash")
            gemini_prompt = json.dumps(
                {
                    "task": "review_and_improve_news_rewrite",
                    "input": deepseek_output,
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

            deepseek_score = float(deepseek_output["deepseek_score"])
            gemini_score = float(gemini_data.get("gemini_score") or gemini_data.get("ai_score") or deepseek_score)
            combined_score = round((deepseek_score + gemini_score) / 2, 2)

            return {
                "final_title": str(gemini_data.get("final_title") or deepseek_output["final_title"]),
                "final_text": str(gemini_data.get("final_text") or deepseek_output["final_text"]),
                "ai_score": combined_score,
                "category": str(gemini_data.get("category") or deepseek_output["category"]),
                "target_persona": str(gemini_data.get("target_persona") or deepseek_output["target_persona"]),
                "deepseek_score": deepseek_score,
                "gemini_score": gemini_score,
                "combined_score": combined_score,
            }
        except Exception:
            logger.exception("Gemini enhancement failed, returning DeepSeek output")
            return deepseek_output
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