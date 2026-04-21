#!/usr/bin/env python3
from pathlib import Path
import json
from collections import defaultdict

from app.backend.services.article_detector import ArticleDetector


def main():
    p = Path("data/processed/parsed_today.json")
    if not p.exists():
        print("data/processed/parsed_today.json not found")
        return

    data = json.loads(p.read_text(encoding="utf-8"))
    det = ArticleDetector()
    filtered = det.filter_items(data)

    out_p = Path("data/processed/parsed_today_filtered.json")
    summary_p = Path("data/processed/parsed_today_filtered_summary.json")

    out_p.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = defaultdict(int)
    examples = {}
    for it in filtered:
        s = it.get("source") or "UNKNOWN"
        counts[s] += 1
        if s not in examples:
            examples[s] = []
        if len(examples[s]) < 5:
            examples[s].append({
                "url": it.get("url"),
                "title": it.get("title"),
                "published_at": it.get("published_at"),
            })

    summary = {"counts": dict(counts), "total_before": len(data), "total_after": len(filtered), "examples": examples}
    summary_p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Filtered {len(filtered)}/{len(data)} items — wrote {out_p} and {summary_p}")


if __name__ == '__main__':
    main()
