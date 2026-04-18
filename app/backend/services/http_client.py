from __future__ import annotations

import asyncio
from typing import Dict

import httpx

# Shared AsyncClient per event loop to reuse connections and keep TCP pools warm.
# Clients are created lazily and closed on application shutdown.

_CLIENTS: Dict[int, httpx.AsyncClient] = {}


def _default_timeout() -> httpx.Timeout:
    return httpx.Timeout(10.0, connect=5.0)


def _default_limits() -> httpx.Limits:
    return httpx.Limits(max_connections=100, max_keepalive_connections=20)


async def get_async_client() -> httpx.AsyncClient:
    """Return a shared AsyncClient for the current event loop.

    Reusing a single client avoids repeated TCP/TLS handshakes and speeds up
    high-concurrency HTTP workloads. The client is safe to use concurrently
    across coroutines running on the same event loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    key = id(loop) if loop is not None else 0
    client = _CLIENTS.get(key)
    if client is None or client.is_closed:
        # Use a common browser User-Agent to avoid simple bot blocks from some RSS endpoints.
        client = httpx.AsyncClient(
            timeout=_default_timeout(),
            limits=_default_limits(),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/115.0.0.0 Safari/537.36"
                )
            },
        )
        _CLIENTS[key] = client
    return client


async def close_async_clients() -> None:
    """Close all managed AsyncClient instances.

    Call this from application shutdown to ensure sockets are closed.
    """
    keys = list(_CLIENTS.keys())
    for k in keys:
        client = _CLIENTS.pop(k, None)
        if client is None:
            continue
        try:
            await client.aclose()
        except Exception:
            # Best-effort close; ignore errors during shutdown.
            pass
