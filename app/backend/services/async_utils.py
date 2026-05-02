"""Concurrency utilities for bounded async operations."""

import asyncio
from typing import Any, Coroutine, List, Optional


async def gather_with_concurrency(
    n: int,
    coros: List[Coroutine[Any, Any, Any]],
    return_exceptions: bool = False,
) -> List[Any]:
    """
    Run coroutines with bounded concurrency.
    
    Args:
        n: Max concurrent tasks
        coros: List of coroutines to run
        return_exceptions: If True, return exceptions instead of raising
    
    Returns:
        List of results in order (or mixed with exceptions if return_exceptions=True)
    """
    semaphore = asyncio.Semaphore(n)

    async def sem_task(coro):
        async with semaphore:
            return await coro

    tasks = [asyncio.create_task(sem_task(c)) for c in coros]
    results = await asyncio.gather(*tasks, return_exceptions=return_exceptions)
    return results


async def gather_with_timeout(
    n: int,
    coros: List[Coroutine[Any, Any, Any]],
    timeout: float = 30.0,
) -> List[Optional[Any]]:
    """Run coroutines with concurrency limit and timeout."""
    try:
        return await asyncio.wait_for(
            gather_with_concurrency(n, coros, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return [None] * len(coros)
