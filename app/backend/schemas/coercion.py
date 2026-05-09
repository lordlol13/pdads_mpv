import json
import csv
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
        if stripped.startswith("{") and stripped.endswith("}"):
            inner = stripped[1:-1].strip()
            if not inner:
                return []
            reader = csv.reader([inner], skipinitialspace=True)
            return [item.strip().strip('"') for item in next(reader, []) if item and item.strip()]
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [part.strip().strip('"') for part in stripped.split(",") if part.strip()]
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        return []
    return None
