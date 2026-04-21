#!/usr/bin/env python3
"""Entry point: `scripts/run/run_pipeline.py` — запускает последовательность processor -> ingestion.

Использует `app.backend.services.pipeline.run_pipeline` когда модуль доступен,
что даёт удобный programmatic hook для CI / локальных запусков.
"""
from __future__ import annotations
import argparse
import asyncio

from app.backend.services.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="лимит для processor (кол-во ссылок)")
    args = parser.parse_args()
    asyncio.run(run_pipeline(limit=args.limit))


if __name__ == "__main__":
    main()
