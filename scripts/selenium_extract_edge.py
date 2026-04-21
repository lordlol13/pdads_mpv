#!/usr/bin/env python3
"""Selenium-based article extractor.

Usage:
  python scripts/selenium_extract.py --urls https://uz24.uz/uz/articles/raunda-26-4-19
  python scripts/selenium_extract.py --listing https://uz24.uz/uz    # discover article links then extract

The script opens pages with a headless Chrome webdriver (webdriver-manager).
It extracts title, date, main image, article text and tags and saves results to
`scripts/selenium_parsed.json`.
"""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.microsoft import EdgeChromiumDriverManager


def init_driver(headless=True, use_edge=True):
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1200,900")
    # set a common UA to reduce bot blocking
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
    service = Service(EdgeChromiumDriverManager().install())
    driver = webdriver.Edge(service=service, options=options)
    driver.set_page_load_timeout(30)
    return driver


def extract_article(driver, url):
    out = {"url": url, "title": "", "date": "", "image_url": "", "text": "", "tags": []}
    try:
        driver.get(url)
    except Exception:
        # fallback: try again once
        driver.execute_script("window.stop();")
    time.sleep(1)

    # title
    try:
        t = driver.find_element(By.CSS_SELECTOR, "h1")
        out["title"] = t.text.strip()
    except Exception:
        try:
            meta = driver.find_element(By.CSS_SELECTOR, 'meta[property="og:title"]')
            out["title"] = meta.get_attribute("content") or ""
        except Exception:
            out["title"] = ""

    # main image: try meta og:image first
    try:
        meta = driver.find_element(By.CSS_SELECTOR, 'meta[property="og:image"]')
        out["image_url"] = meta.get_attribute("content") or ""
    except Exception:
        out["image_url"] = ""

    if not out["image_url"]:
        try:
            img = driver.find_element(By.CSS_SELECTOR, 'article img, .article img, .entry-content img, .post-content img')
            out["image_url"] = img.get_attribute("src") or ""
        except Exception:
            out["image_url"] = ""

    # date/time
    try:
        t = driver.find_element(By.CSS_SELECTOR, "time")
        out["date"] = t.get_attribute("datetime") or t.text
    except Exception:
        # look for common classes
        for sel in (".date", ".publish-date", ".post-meta", ".news-date"):
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.text:
                    out["date"] = el.text.strip()
                    break
            except Exception:
                continue

    # main text: prefer article container
    text = ""
    selectors = ["article", ".article-content", ".entry-content", ".post-content", ".news-article", ".content"]
    for sel in selectors:
        try:
            cont = driver.find_element(By.CSS_SELECTOR, sel)
            ps = cont.find_elements(By.TAG_NAME, "p")
            if ps:
                text = "\n\n".join([p.text.strip() for p in ps if p.text.strip()])
                break
        except Exception:
            continue

    if not text:
        try:
            ps = driver.find_elements(By.TAG_NAME, "p")
            text = "\n\n".join([p.text.strip() for p in ps if p.text.strip()])
        except Exception:
            text = ""

    out["text"] = text

    # tags
    tags = set()
    try:
        tag_els = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/tag"], .tags a, .post-tags a')
        for t in tag_els:
            v = t.text.strip()
            if v:
                tags.add(v)
    except Exception:
        pass
    out["tags"] = list(tags)

    return out


def discover_links(driver, listing_url, domain=None, limit=50):
    try:
        driver.get(listing_url)
    except Exception:
        driver.execute_script("window.stop();")
    time.sleep(1)
    links = []
    a_elems = driver.find_elements(By.TAG_NAME, "a")
    seen = set()
    for a in a_elems:
        try:
            href = a.get_attribute("href") or ""
            if not href:
                continue
            href = href.split("#")[0]
            if domain and domain not in href:
                continue
            # heuristic: candidate article links
            if re.search(r"/articles/|/news/|/ru/|/uz/|/article", href):
                if href not in seen:
                    seen.add(href)
                    links.append(href)
            if len(links) >= limit:
                break
        except Exception:
            continue
    return links


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", nargs="*", help="One or more article URLs to extract")
    parser.add_argument("--listing", help="Listing page URL to discover article links")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser headless (default true)")
    parser.add_argument("--limit", type=int, default=10, help="Max articles to discover from a listing")
    args = parser.parse_args()

    driver = init_driver(headless=args.headless)
    out = []
    try:
        to_process = []
        if args.urls:
            to_process.extend(args.urls)
        if args.listing:
            domain = urlparse(args.listing).netloc
            discovered = discover_links(driver, args.listing, domain=domain, limit=args.limit)
            to_process.extend(discovered)

        # dedupe
        seen = set()
        final = []
        for u in to_process:
            if u in seen:
                continue
            seen.add(u)
            final.append(u)

        print(f"Found {len(final)} urls to extract")
        for i, u in enumerate(final[: args.limit]):
            print(f"[{i+1}/{min(len(final), args.limit)}] {u}")
            try:
                data = extract_article(driver, u)
                out.append(data)
            except Exception as e:
                print("Error extracting", u, e)

    finally:
        driver.quit()

    out_path = Path(__file__).resolve().parent / "selenium_parsed.json"
    with out_path.open("w", encoding="utf8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("Saved:", out_path)


if __name__ == "__main__":
    main()
