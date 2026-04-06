import asyncio
from typing import Any

from app.backend.services import news_api_service


def test_fetch_articles_for_topics_uses_async_http_client(monkeypatch) -> None:
    calls: dict[str, Any] = {"used_async_client": False}

    class FakeResponse:
        text = "<rss><channel></channel></rss>"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "articles": [
                    {
                        "source": {"name": "demo"},
                        "title": "AI headline",
                        "description": "Short summary",
                        "content": "Longer body",
                        "url": "https://example.com/article",
                        "urlToImage": "https://example.com/image.jpg",
                        "publishedAt": "2026-04-05T00:00:00Z",
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            calls["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, params: dict[str, Any]) -> FakeResponse:
            calls["used_async_client"] = True
            calls["url"] = url
            calls["params"] = params
            return FakeResponse()

    async def passthrough_cache(key: str, ttl_seconds: int, fetcher):
        calls["cache_key"] = key
        calls["ttl"] = ttl_seconds
        return await fetcher()

    monkeypatch.setattr(news_api_service.settings, "NEWS_API_KEY", "test-key")
    monkeypatch.setattr(news_api_service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(news_api_service, "get_or_set_json", passthrough_cache)

    result = asyncio.run(news_api_service.fetch_articles_for_topics(["ai"], page_size=5))

    assert calls["used_async_client"] is True
    assert calls["url"] == news_api_service.NEWS_API_URL
    assert calls["params"]["apiKey"] == "test-key"
    assert len(result) == 1
    assert result[0]["title"] == "AI headline"


def test_fetch_articles_for_topics_mixes_country_and_global_sources(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, Any], text: str = "<rss><channel></channel></rss>") -> None:
            self._payload = payload
            self.text = text

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, params: dict[str, Any]) -> FakeResponse:
            calls.append(params)
            if "domains" in params:
                return FakeResponse(
                    {
                        "articles": [
                            {
                                "source": {"name": "local"},
                                "title": "UZ economy",
                                "description": "Local market update",
                                "content": "Detailed local content",
                                "url": "https://kun.uz/local-1",
                                "urlToImage": "https://kun.uz/local-1.jpg",
                                "publishedAt": "2026-04-05T10:00:00Z",
                            }
                        ]
                    }
                )
            return FakeResponse(
                {
                    "articles": [
                        {
                            "source": {"name": "global"},
                            "title": "Global markets",
                            "description": "World update",
                            "content": "Global details",
                            "url": "https://reuters.com/global-1",
                            "urlToImage": "https://reuters.com/global-1.jpg",
                            "publishedAt": "2026-04-05T09:00:00Z",
                        }
                    ]
                }
            )

    async def passthrough_cache(key: str, ttl_seconds: int, fetcher):
        return await fetcher()

    monkeypatch.setattr(news_api_service.settings, "NEWS_API_KEY", "test-key")
    monkeypatch.setattr(news_api_service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(news_api_service, "get_or_set_json", passthrough_cache)

    result = asyncio.run(news_api_service.fetch_articles_for_topics(["economy"], page_size=4, country_codes=["UZ"]))

    assert len(calls) >= 2
    assert any("domains" in params for params in calls)
    assert any("excludeDomains" in params for params in calls)
    assert len(result) == 2
    titles = {item["title"] for item in result}
    assert "UZ economy" in titles
    assert "Global markets" in titles
