"""Простой scheduler для запуска `today_scraper.py` по расписанию.

Использует `APScheduler` если установлен, иначе проста петля с `time.sleep`.
"""
from __future__ import annotations
import os
import time
import subprocess
import logging

LOG = logging.getLogger("today_scheduler")

INTERVAL_SECONDS = int(os.getenv("SCRAPER_INTERVAL_SECONDS", 60 * 20))  # по умолчанию 20 минут


def run_once(out_path: str = "data/processed/parsed_today.json"):
    cmd = ["python", "-u", "scripts/run/today_scraper.py", "--out", out_path]
    LOG.info("running: %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, check=False)
        LOG.info("run finished: returncode=%s", r.returncode)
    except Exception as e:
        LOG.exception("run failed: %s", e)


def main():
    LOG.info("starting simple scheduler (interval=%s seconds)", INTERVAL_SECONDS)
    while True:
        run_once()
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
