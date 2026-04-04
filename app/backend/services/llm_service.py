from typing import TypedDict


class GeneratedNews(TypedDict):
    final_title: str
    final_text: str
    ai_score: float
    category: str
    target_persona: str


async def generate_news(raw_text: str, title: str, category: str | None) -> GeneratedNews:
    return {
        "final_title": f"[AI] {title}",
        "final_text": (raw_text or "")[:1200],
        "ai_score": 8.5,
        "category": category or "general",
        "target_persona": "general",
    }