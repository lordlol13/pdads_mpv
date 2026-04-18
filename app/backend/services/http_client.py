from __future__ import annotations

import asyncio
from typing import Dict
import time

import httpx
from app.backend.core.logging import ContextLogger


logger = ContextLogger(__name__)

# Shared AsyncClient per event loop to reuse connections and keep TCP pools warm.
# Clients are created lazily and closed on application shutdown.

_CLIENTS: Dict[int, httpx.AsyncClient] = {}
_CLIENTS_META: Dict[int, dict] = {}


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
    if client is None or getattr(client, "is_closed", False):
        # Log creation to aid diagnosing httpx/anyio lifecycle issues.
        logger.info(
            "Creating AsyncClient",
            loop_id=(id(loop) if loop is not None else None),
            httpx_version=getattr(httpx, "__version__", "unknown"),
        )

        created_at = time.time()

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
        _CLIENTS_META[key] = {"created_at": created_at, "loop": (id(loop) if loop is not None else None)}
    else:
        logger.debug("Reusing AsyncClient", key=key, is_closed=getattr(client, "is_closed", None))

    return client


async def close_async_clients() -> None:
    """Close all managed AsyncClient instances.

    Call this from application shutdown to ensure sockets are closed.
    """
    keys = list(_CLIENTS.keys())
    if not keys:
        logger.debug("No AsyncClient instances to close")
        return

    logger.info("Closing AsyncClient instances", count=len(keys))

    close_tasks = []
    for k in keys:
        client = _CLIENTS.pop(k, None)
        _CLIENTS_META.pop(k, None)
        if client is None:
            continue
        try:
            # Schedule close as background task and consume any exception so
            # the event loop does not log "Task exception was never retrieved"
            task = asyncio.create_task(client.aclose())

            def _consume_exception(fut: asyncio.Future) -> None:
                try:
                    # Force retrieval of exception so it doesn't remain unobserved
                    _ = fut.exception()
                except Exception:
                    # swallow any error retrieving exception
                    pass

            task.add_done_callback(_consume_exception)
            close_tasks.append(task)
        except Exception as exc:  # pragma: no cover - best-effort shutdown
            logger.warning("Failed to schedule AsyncClient.aclose()", error=str(exc))

    if close_tasks:
        # Give background close tasks a short window to run; don't fail shutdown
        # if they don't complete — we're best-effort here.
        try:
            done, pending = await asyncio.wait(close_tasks, timeout=2.0)
            logger.debug("AsyncClient close tasks completed", completed=len(done), pending=len(pending))
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("Error while waiting for client close tasks", error=str(exc))


def get_clients_info() -> list:
    """Return lightweight debug info about managed clients."""
    info = []
    for k, client in _CLIENTS.items():
        meta = _CLIENTS_META.get(k, {})
        info.append(
            {
                "key": k,
                "is_closed": getattr(client, "is_closed", None),
                "created_at": meta.get("created_at"),
                "loop": meta.get("loop"),
            }
        )
    return info


def log_clients_state() -> None:
    """Log current clients for diagnostics."""
    logger.info("AsyncClient pool state", count=len(_CLIENTS), clients=get_clients_info())
