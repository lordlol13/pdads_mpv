import asyncio
from datetime import datetime, timedelta

import httpx

from app.backend.services import today_pipeline_utils as tpu


def test_extract_date_jsonld():
    html = '<html><head><script type="application/ld+json">{"@context":"http://schema.org","@type":"NewsArticle","datePublished":"2026-04-19T12:34:00+05:00"}</script></head><body></body></html>'
    dt = tpu.extract_date(html, "https://example.com/article")
    assert dt is not None
    assert dt.isoformat().startswith("2026-04-19T12:34:00")


def test_extract_date_meta():
    html = '<meta property="article:published_time" content="2026-04-19T10:00:00+05:00">'
    dt = tpu.extract_date(html, "https://example.com")
    assert dt is not None
    assert dt.isoformat().startswith("2026-04-19T10:00:00")


def test_extract_date_time_tag():
    html = '<time datetime="2026-04-19T08:00:00+05:00">8:00</time>'
    dt = tpu.extract_date(html, "https://u")
    assert dt is not None
    assert dt.isoformat().startswith("2026-04-19T08:00:00")


def test_parse_relative_today():
    now_date = datetime.now(tpu.TZ).date()
    html = '<time>сегодня 12:30</time>'
    dt = tpu.extract_date(html, "https://u")
    assert dt is not None
    assert dt.astimezone(tpu.TZ).date() == now_date


def test_parse_uzbek_relative_hours():
    dt = tpu._parse_relative_or_local_text("2 soat oldin")
    assert dt is not None
    delta = datetime.now(tpu.TZ) - dt
    assert 0 < delta.total_seconds() < 4 * 3600


def test_is_today_true_false():
    today_dt = datetime.now(tpu.TZ)
    assert tpu.is_today(today_dt)
    yesterday = today_dt - timedelta(days=1)
    assert not tpu.is_today(yesterday)


def test_extract_links_minimal():
    async def fake_fetch(client, url, attempts=3):
        return '<html><body><a href="/a1">a1</a><a href="https://other.com/x">x</a><a href="/tag/test">tag</a></body></html>'

    # monkeypatch module-level fetch
    tpu._fetch_html = fake_fetch
    client = httpx.AsyncClient()
    links = asyncio.run(tpu.extract_links(client, "https://example.com/"))
    assert any("/a1" in l or l.endswith("/a1") for l in links)
    assert not any("other.com" in l for l in links)
    asyncio.run(client.aclose())
