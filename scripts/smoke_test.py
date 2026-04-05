import argparse
import json
import time

import requests
from requests import RequestException


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Full backend smoke test for PDADS MVP")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="FastAPI base URL")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Max task polling duration")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base = args.base_url.rstrip("/")
    timeout = args.timeout

    session = requests.Session()

    # Preflight API availability check to fail fast with a clear message.
    try:
        health_response = session.get(f"{base}/health", timeout=timeout)
        health_response.raise_for_status()
    except RequestException as exc:
        raise SystemExit(
            f"Cannot reach API at {base}. Start FastAPI first: "
            "python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000"
        ) from exc

    uid = int(time.time())
    username = f"smoke_{uid}"
    email = f"{username}@example.com"
    password = "Test12345!"

    register_payload = {
        "username": username,
        "email": email,
        "password": password,
        "location": "Tashkent",
        "interests": {"topics": ["ai"]},
        "country_code": "UZ",
        "region_code": "TAS",
    }
    response = session.post(f"{base}/auth/register", json=register_payload, timeout=timeout)
    print("register", response.status_code)
    if response.status_code not in (200, 409):
        print(response.text)
        raise SystemExit(1)

    response = session.post(
        f"{base}/auth/login",
        json={"identifier": email, "password": password},
        timeout=timeout,
    )
    print("login", response.status_code)
    response.raise_for_status()
    token = response.json()["access_token"]
    session.headers["Authorization"] = f"Bearer {token}"

    response = session.get(f"{base}/auth/me", timeout=timeout)
    print("me", response.status_code)
    response.raise_for_status()

    ingest_payload = {
        "title": "Smoke test news item",
        "source_url": f"https://example.com/smoke/{uid}",
        "raw_text": "Automated smoke test content for end-to-end backend verification.",
        "category": "technology",
        "region": "global",
        "is_urgent": False,
    }
    response = session.post(f"{base}/ingestion/raw-news", json=ingest_payload, timeout=timeout)
    print("ingest", response.status_code)
    response.raise_for_status()
    raw_news_id = response.json()["id"]

    response = session.post(f"{base}/pipeline/process/{raw_news_id}", timeout=timeout)
    print("enqueue", response.status_code)
    response.raise_for_status()
    task_id = response.json()["task_id"]

    final_state = "PENDING"
    task_result = None
    for _ in range(args.poll_seconds):
        time.sleep(1)
        response = session.get(f"{base}/pipeline/tasks/{task_id}", timeout=timeout)
        data = response.json()
        final_state = data["state"]
        task_result = data.get("result")
        if final_state in ("SUCCESS", "FAILURE"):
            break

    print("task_state", final_state)
    print("task_result", task_result)
    if final_state != "SUCCESS":
        raise SystemExit(1)

    response = session.get(f"{base}/feed/me?limit=10", timeout=timeout)
    print("feed", response.status_code)
    response.raise_for_status()
    feed = response.json()
    print("feed_count", len(feed))
    if not feed:
        raise SystemExit("feed empty")

    item = feed[0]
    interaction_payload = {
        "user_id": item["user_id"],
        "ai_news_id": item["ai_news_id"],
        "liked": True,
        "viewed": True,
        "watch_time": 10,
    }
    response = session.post(f"{base}/feed/interactions", json=interaction_payload, timeout=timeout)
    print("interaction", response.status_code)
    response.raise_for_status()

    print(
        "SMOKE_OK",
        json.dumps(
            {
                "user": username,
                "raw_news_id": raw_news_id,
                "task_id": task_id,
                "feed_count": len(feed),
            },
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    main()
