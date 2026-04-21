from __future__ import annotations

import hashlib


def generate_hash(title: str | None, content: str | None) -> str:
    t = (title or "").strip()
    c = (content or "")[:500]
    payload = (t + c).lower()
    return hashlib.md5(payload.encode("utf-8")).hexdigest()
