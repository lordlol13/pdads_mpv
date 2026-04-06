import json
from typing import Any


def coerce_json_string_list(value: Any) -> list[str] | None:
    """Normalize image/video URL fields from DB (JSON text, PG array, or Python list)."""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        return []
    return None
