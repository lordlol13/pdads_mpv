PR: Improve LLM article generation — force Uzbek, safer heavy model rollout, protected endpoint

Summary

This PR makes several targeted changes to improve AI-generated articles quality and safety:

- Add a stricter journalist editorial prompt that enforces publication-quality, JSON-only output and a natural article structure (intro, main story, stats, comparison, insights, impact, conclusion).
- Introduce `EDITORIAL_FORCE_LANGUAGE` config (default: `uz`) so generated headlines and article bodies are produced in Uzbek when required.
- Add safer heavy-model selection: `LLM_ENABLE_HEAVY_MODEL` must be explicitly set to enable `OPENAI_MODEL_DEFAULT_HEAVY` (defaults to `gpt-4o-mini`).
- Add `INTERNAL_API_KEY` protection and a rate-limited API endpoint `/api/llm/generate_article` for internal testing of article generation.
- Provide deployment notes in `DEPLOYMENT_LLMS.md` describing exact Railway variables to set and recommended rollout steps.

Files changed (high level)

- `app/backend/services/llm_service.py` — new editorial prompt, language forcing, model selection safety.
- `app/backend/core/config.py` — new config fields: `OPENAI_MODEL_DEFAULT_HEAVY`, `LLM_ENABLE_HEAVY_MODEL`, `INTERNAL_API_KEY`, `EDITORIAL_FORCE_LANGUAGE`.
- `app/backend/api/routes/llm.py` — protected `/api/llm/generate_article` endpoint.
- `DEPLOYMENT_LLMS.md` — updated deployment instructions.
- `tests/*` — small tests validating prompt and endpoint behavior.

Railway variables to set

Required:
- `OPENAI_API_KEY` = <your OpenAI API key>
- `INTERNAL_API_KEY` = <strong random secret>  # used to call `/api/llm/generate_article` in production
- `EDITORIAL_FORCE_LANGUAGE` = "uz"  # ensures generated headline and article are in Uzbek

Optional / rollout flags:
- `OPENAI_MODEL` = "gpt-4o-mini"  # overrides default model; choose carefully
- `LLM_ENABLE_HEAVY_MODEL` = "true"|"false"  # must be true to allow default heavy model fallback
- `LLM_RATE_LIMIT_PER_MINUTE` = 5  # adjust if you need more throughput

Deployment checklist (recommended)

1) Add `OPENAI_API_KEY` and `INTERNAL_API_KEY` to Railway Project variables (not in public repo).
2) Keep `LLM_ENABLE_HEAVY_MODEL=false` initially; deploy and smoke test generation using `/api/llm/generate_article` with `INTERNAL_API_KEY` header.
3) Monitor latencies, 429s, 5xx, and cost for a few hours/days.
4) Flip `LLM_ENABLE_HEAVY_MODEL=true` and optionally set `OPENAI_MODEL=gpt-4o-mini` or `gpt-4o` in a controlled window; monitor.
5) Rollback by setting `LLM_ENABLE_HEAVY_MODEL=false` or unsetting `OPENAI_MODEL`.

Testing the endpoint (example curl)

curl -X POST https://<your-backend>/api/llm/generate_article \
  -H "Content-Type: application/json" \
  -H "X-Internal-Api-Key: <INTERNAL_API_KEY>" \
  -d '{"title":"HUMO на National AI Hackathon","raw_text":"...","category":"tech","target_persona":"students"}'

Notes
- Keep `INTERNAL_API_KEY` secret and rotate if exposed.
- Prefer `gpt-4o-mini` as a balance of quality/cost; `gpt-4o` is higher cost and latency.

If you want, I can: create a git branch, commit these changes under that branch, and prepare the PR body ready to open on GitHub (I can show the exact git commands to run and the PR text).