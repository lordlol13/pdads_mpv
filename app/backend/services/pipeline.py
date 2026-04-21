import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


async def _run_cmd(cmd: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if out:
        try:
            print(out.decode(errors="ignore"))
        except Exception:
            print(out)
    return proc.returncode


async def run_pipeline(limit: int | None = None) -> None:
    """Высокоуровневый runner для локального запуска: сначала processor, затем ingestion.

    Это лёгкий оркестратор, пока без сложной интеграции — просто вызывает
    существующие CLI-скрипты в `scripts/` как подпроцессы.
    """

    # 1) Processor (collect + extract + optional AI local step)
    proc_cmd = [sys.executable, str(ROOT / "scripts" / "run" / "run_processor_limit20.py")]
    if limit:
        proc_cmd += ["--limit", str(limit)]

    rc = await _run_cmd(proc_cmd)
    if rc != 0:
        raise RuntimeError(f"processor exited with {rc}")

    # 2) Ingestion (persist -> process raw -> AI enrichment)
    ingest_cmd = [sys.executable, str(ROOT / "scripts" / "run" / "run_ingestion_pipeline_now.py")]
    rc = await _run_cmd(ingest_cmd)
    if rc != 0:
        raise RuntimeError(f"ingestion exited with {rc}")


def run_pipeline_sync(limit: int | None = None) -> None:
    asyncio.run(run_pipeline(limit=limit))
