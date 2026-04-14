from fastapi.testclient import TestClient

from app.backend.main import app


def test_generate_article_endpoint_returns_structured_article():
    client = TestClient(app)

    payload = {
        "title": "HUMO на National AI Hackathon",
        "raw_text": "Milliy banklararo protsessing markazi (HUMO) принял участие в National AI Hackathon. Это событие, организованное по инициативе президента, фокусировалось на финтех‑решениях и привлечении студентов.",
        "category": "tech",
        "target_persona": "students",
    }

    resp = client.post("/api/llm/generate_article", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, dict)
    assert "final_title" in data and "final_text" in data and "ai_score" in data
    assert isinstance(data["final_text"], str) and len(data["final_text"].split()) >= 50
