#!/usr/bin/env python3
"""Quick smoke tests for media selection helpers."""
from __future__ import annotations

from app.backend.services import media_service as ms


def run():
    samples = [
        "https://cdn.example.com/images/abc_800x600.jpg",
        "https://cdn.example.com/images/abc_1600x900.jpg",
        "https://ichef.bbci.co.uk/news/240/cpsprodpb/abc.jpg",
        "https://images.unsplash.com/photo-123?auto=format&fit=crop&w=1600&q=80",
        "https://example.com/assets/logo.png",
        "https://example.com/placeholder_200x150.jpg",
    ]

    print("--- dimension hints and lookups ---")
    for s in samples:
        print(s)
        print("  dims:", ms.extract_image_dimensions(s))
        print("  canonical:", ms.canonical_image_key(s))
        print("  visual:", ms.visual_image_key(s))
        print("  looks_like_news_photo:", ms._looks_like_news_photo(s))

    print("\n--- select best per visual group ---")
    best = ms._select_best_per_visual_group(samples)
    for b in best:
        print(b)

    print("\n--- ranked urls (topic=\"f1\") ---")
    ranked = ms._rank_image_urls(samples, topic="f1", source_url="https://example.com/article")
    for r in ranked:
        print(r)

    print("\n--- collect unique urls (limit=4) ---")
    unique = ms._collect_unique_urls(ranked, limit=4)
    for u in unique:
        print(u)


if __name__ == "__main__":
    run()
