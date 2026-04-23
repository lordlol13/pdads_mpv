from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import random

# keywords and domains to reject
BAD_IMAGE_KEYWORDS = [
    "logo", "icon", "avatar", "banner", "ads", "sprite", "placeholder",
    "pixel", "badge"
]

BAD_DOMAINS = [
    "logo", "icon", "placeholder", "ads",
    "doubleclick", "googlesyndication"
]


def is_bad_image(url: str) -> bool:
    if not url:
        return True

    url = url.lower()

    # reject base64/data URIs and SVGs
    if url.startswith("data:"):
        return True
    if ".svg" in url:
        return True

    # reject known placeholder/logo domains or keywords
    if any(d in url for d in BAD_DOMAINS):
        return True
    if any(k in url for k in BAD_IMAGE_KEYWORDS):
        return True

    return False


def get_best_from_srcset(img, base_url):
    srcset = img.get("srcset")
    if not srcset:
        return None

    parts = [p.strip() for p in srcset.split(",") if p.strip()]
    if not parts:
        return None

    # prefer the last (usually largest) descriptor
    best = parts[-1].split()[0]
    return urljoin(base_url, best)


def extract_meta_image(soup, base_url):
    # og:image
    tag = soup.find("meta", property="og:image")
    if tag and tag.get("content"):
        return urljoin(base_url, tag["content"])

    # twitter:image
    tag = soup.find("meta", attrs={"name": "twitter:image"})
    if tag and tag.get("content"):
        return urljoin(base_url, tag["content"])

    # link rel
    link = soup.find("link", rel=lambda x: x and "image" in x)
    if link and link.get("href"):
        return urljoin(base_url, link["href"])

    return None


def extract_content_image(soup, base_url):
    images = soup.find_all("img")

    for img in images:
        src = img.get("src") or img.get("data-src") or get_best_from_srcset(img, base_url)
        if not src:
            continue

        # protocol-relative -> https
        if src.startswith("//"):
            src = "https:" + src

        full_url = urljoin(base_url, src)

        if is_bad_image(full_url):
            continue

        # skip tiny images by attributes
        width = img.get("width")
        if width and str(width).isdigit() and int(width) < 200:
            continue

        height = img.get("height")
        if height and str(height).isdigit() and int(height) < 150:
            continue

        return full_url

    return None


def extract_keywords(title: str):
    words = re.findall(r"\w+", (title or "").lower())
    stopwords = {"the", "a", "an", "and", "or", "of", "in", "on", "это", "как", "что", "в", "на", "по"}
    words = [w for w in words if w not in stopwords]
    return " ".join(words[:2]) or "news"


def fallback_image(title: str):
    keywords = extract_keywords(title)
    # add randomness to reduce repeated identical fallbacks
    seed = random.randint(1, 10000)
    return f"https://source.unsplash.com/800x600/?{keywords}&sig={seed}"


def resolve_image(html: str, title: str, base_url: str, candidate_url: str = None):
    soup = BeautifulSoup(html or "", "html.parser")

    # 1. candidate from parser (normalize)
    if candidate_url:
        candidate = candidate_url.strip()
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        if base_url and candidate.startswith("/"):
            candidate = urljoin(base_url, candidate)
        if not candidate.lower().startswith("http") and base_url:
            candidate = urljoin(base_url, candidate)

        if candidate and not is_bad_image(candidate):
            return candidate

    # 2. meta tags
    meta_img = extract_meta_image(soup, base_url)
    if meta_img and not is_bad_image(meta_img):
        return meta_img

    # 3. content images
    content_img = extract_content_image(soup, base_url)
    if content_img:
        return content_img

    # 4. fallback
    return fallback_image(title)
