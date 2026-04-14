Recommended steps to enable a heavier OpenAI model in production

1) Safety first
- Do not change the model and enable heavy usage without monitoring. Heavy models (gpt-4o-mini / gpt-4o) can increase cost and latency.

2) Environment variables to set in Railway (Project/Service variables):
- `OPENAI_API_KEY` = <your API key>
- Option A (explicit model): `OPENAI_MODEL` = "gpt-4o-mini" and optionally `LLM_ENABLE_HEAVY_MODEL` = "true"
- Option B (enable default heavy): `LLM_ENABLE_HEAVY_MODEL` = "true" (uses `OPENAI_MODEL_DEFAULT_HEAVY` which defaults to "gpt-4o-mini")
- `INTERNAL_API_KEY` = <strong random string>  # required to enable `/api/llm/generate_article` in production
 - `EDITORIAL_FORCE_LANGUAGE` = "uz"  # enforce Uzbek for generated article body and headline
 - Optional: `OPENAI_MODEL` = "gpt-4o"  # if you want full model vs mini; expect higher cost/latency

3) Recommended rollout
- Set `OPENAI_API_KEY` and `INTERNAL_API_KEY` first.
- Keep `LLM_ENABLE_HEAVY_MODEL=false` initially. Deploy and run smoke tests.
- Flip `LLM_ENABLE_HEAVY_MODEL=true` during a maintenance window and monitor logs, latency, and cost.
- If problems occur, flip back to `LLM_ENABLE_HEAVY_MODEL=false` or set `OPENAI_MODEL` to a smaller model.

4) Rate limiting & monitoring
- The app uses `LLM_RATE_LIMIT_PER_MINUTE` (default 5). Adjust this in env if you expect more throughput.
- Check Railway logs and Cloud provider metrics for 429s, 5xx, and CPU/memory spikes.

5) Rollback
- To disable heavy model quickly: set `LLM_ENABLE_HEAVY_MODEL=false` and/or unset `OPENAI_MODEL`.

6) Notes
- The code will refuse `/api/llm/generate_article` in production unless `INTERNAL_API_KEY` is configured, to avoid accidental public triggering.
- This file can be attached to the PR that updates Railway variables.
 - Make sure `INTERNAL_API_KEY` is kept secret and set at Project-level so all services (web + workers) can use it if needed.
 - Start with `EDITORIAL_FORCE_LANGUAGE=uz` to ensure headlines and articles are generated in Uzbek; change only if you need a different default.
