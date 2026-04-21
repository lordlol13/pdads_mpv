from __future__ import annotations
import os
import re
import logging
from typing import Optional
from bs4 import BeautifulSoup

from app.backend.services.content_extractors import extract_by_domain

LOG = logging.getLogger("ai_enrich")

try:
    import openai
except Exception:
    openai = None


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _clean_text(text: str) -> str:
    if not text:
        return ""
    # phrases to remove
    bad_phrases = [
        "Izoh qoldirish",
        "Izoh qoldirish uchun",
        "ro‘yxatdan o‘ting",
        "ro‘yxatdan oting",
        "ro‘yxatdan",
        "Xato topdingizmi",
        "internet-nashrining",
        "Daryo internet-nashrining",
        "Matnli materiallarni to‘liq ko‘chirish",
        "Biz sayt ishlashini",
        "cookies-fayllardan",
        "cookies",
        "Maxfiylik siyosati",
        "Tungi ko‘rinish",
        "Guvohnoma",
        "Kabinet",
        "Ctrl+Enter",
        "Ctrl+Enter’ni bosing",
        "18+",
        "Chop etiladigan",
        "Muassis",
        "Ishlab chiquvchi",
        "Elektron manzil",
        "Saytda e’lon qilingan",
        "Saytda e'lon qilingan",
        "Saytda e\u02bclon qilingan",
    ]

    # markers that indicate footer/legal/cookie blocks — cut text at first occurrence
    cut_markers = ["©", "Elektron manzil:", "Guvohnoma:", "Saytda e’lon qilingan", "Saytda e'lon qilingan", "Maxfiylik siyosati", "cookies"]

    # additional attribution/legal patterns often embedded in Daryo pages
    attr_patterns = [r"\d{3,6}-sonli", "guvohnoma", "axborot va ommaviy kommunikatsiyalar agentligi",
                     "o'zmaa", "o‘zmaa", "o‘zbekiston matbuot va axborot agentligi"]

    t = text
    # remove emails
    t = re.sub(r"\S+@\S+", "", t)

    # cut at common legal/attribution regex patterns (e.g. "0944-sonli guvohnoma")
    try:
        lt = t.lower()
        # split regex patterns vs plain substrings
        regex_patterns = [p for p in attr_patterns if p.startswith(r"\\d")]
        plain_patterns = [p for p in attr_patterns if not p.startswith(r"\\d")]

        start_pos = None
        end_pos = None
        for rp in regex_patterns:
            m = re.search(rp, lt)
            if m:
                s, e = m.start(), m.end()
                if start_pos is None or s < start_pos:
                    start_pos, end_pos = s, e
        for pp in plain_patterns:
            idx = lt.find(pp)
            if idx != -1:
                s, e = idx, idx + len(pp)
                if start_pos is None or s < start_pos:
                    start_pos, end_pos = s, e

        if start_pos is not None:
            # if pattern is near the start, assume leading legal block -> keep text AFTER it
            if start_pos <= 200:
                tail = None
                for sep in ["\n\n", "\r\n\r\n", ". ", "? ", "! ", "\n"]:
                    idx2 = t.find(sep, end_pos)
                    if idx2 != -1:
                        tail = idx2 + len(sep)
                        break
                if tail:
                    t = t[tail:].strip()
                else:
                    t = t[end_pos:].strip()
            else:
                # trailing legal block -> cut it off
                t = t[:start_pos].strip()
    except Exception:
        pass

    # cut at markers (remove trailing boilerplate)
    for mk in cut_markers:
        if mk in t:
            t = t.split(mk)[0]

    # remove bad phrases anywhere
    for ph in bad_phrases:
        t = t.replace(ph, "")

    # collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()

    # final heuristic: if cookie notice is still at start, try to drop short leading sentence
    if t and len(t) < 120:
        parts = re.split(r'[\n\.\!\?]+', text)
        parts = [p.strip() for p in parts if p.strip()]
        if parts:
            # pick longest segment as likely article body
            longest = max(parts, key=len)
            if len(longest) > len(t):
                t = re.sub(r"\s+", " ", longest).strip()

    return t


def is_good_paragraph(text: str) -> bool:
    """Простая эвристика: длинный абзац без явных UI/boilerplate фраз."""
    if not text:
        return False
    t = text.strip()
    if len(t) < 50:
        return False

    bad_phrases = [
        "Izoh qoldirish",
        "Izoh qoldirish uchun",
        "ro‘yxatdan o‘ting",
        "ro‘yxatdan oting",
        "ro‘yxatdan",
        "Xato topdingizmi",
        "Daryo internet-nashri",
        "Daryo internet nashr",
        "internet-nashr",
        "cookies",
        "cookie",
        "Guvohnoma",
        "Elektron manzil",
        "Matnli materiallarni to‘liq ko‘chirish",
        "©",
    ]
    low = t.lower()
    # also treat legal/attribution patterns as bad
    if re.search(r"\d{3,6}-sonli", low) or "guvohnoma" in low or "o‘zmaa" in low or "axborot va ommaviy kommunikatsiyalar agentligi" in low:
        return False
    for ph in bad_phrases:
        if ph.lower() in low:
            return False
    return True


def extract_text_from_html(html: Optional[str], url: Optional[str] = None) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    try:
        txt = extract_by_domain(url or "", soup)
    except Exception:
        LOG.exception("extract_by_domain failed")
        txt = ""

    # quick boilerplate guard: if extractor returned a known legal/attribution block,
    # treat as empty so we don't summarize site-level boilerplate.
    try:
        lower_txt = (txt or "").lower()
        bp_marks = ["0944-sonli", "guvohnoma", "daryo internet-nashr", "o‘zmaa", "axborot va ommaviy kommunikatsiyalar agentligi", "muallifligini"]
        is_bp = False
        for bm in bp_marks:
            if bm in lower_txt:
                LOG.info("extractor returned boilerplate for %s, attempting paragraph fallback", url)
                is_bp = True
                break

        if is_bp:
            # try paragraph-level fallback: pick <p> elements that look good and don't contain boilerplate
            try:
                ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
                candidates = [p for p in ps if is_good_paragraph(p) and not any(bm in p.lower() for bm in bp_marks)]
                if candidates:
                    joined = " ".join(candidates[:6])
                    cleaned = _clean_text(joined)
                    if len(cleaned) >= 200:
                        txt = cleaned
                    else:
                        txt = ""
                else:
                    txt = ""
            except Exception:
                txt = ""
    except Exception:
        pass

    if not txt or len(txt) < 200:
        try:
            from readability import Document

            doc = Document(html)
            summary_html = doc.summary() or ""
            soup2 = BeautifulSoup(summary_html, "lxml")
            ps = [p.get_text(" ", strip=True) for p in soup2.find_all("p")]
            txt2 = "\n".join([p for p in ps if p])
            if len(txt2) > len(txt):
                txt = txt2
        except Exception:
            LOG.debug("readability not available or failed")

    # Paragraph-level filtering: удаляем явный UI/boilerplate, но не отбрасываем
    # короткие, но релевантные абзацы. Если после фильтрации есть содержимое —
    # собираем первые N абзацев и возвращаем очищенный текст.
    try:
        import re as _re

        paragraphs = [p.strip() for p in _re.split(r'\r\n|\r|\n', txt) if p.strip()]
        if len(paragraphs) <= 1:
            paragraphs = [p.strip() for p in _re.split(r'(?<=[.!?])\s+', txt) if p.strip()]
    except Exception:
        paragraphs = [txt.strip()] if txt and txt.strip() else []

    bad_checks = [bp.lower() for bp in [
        "Izoh qoldirish", "ro‘yxatdan", "Xato topdingizmi", "Daryo internet-nashri",
        "cookies", "cookie", "Guvohnoma", "Elektron manzil", "Matnli materiallarni",
        "kabinet", "ctrl+enter", "18+", "chop etiladigan", "muallif", "muallifligini",
    ]]

    def is_ui(p: str) -> bool:
        low = p.lower()
        for ph in bad_checks:
            if ph in low:
                return True
        return False

    # Попробуем найти первый содержательный абзац (skip leading UI/meta)
    start_idx = 0
    for i, p in enumerate(paragraphs):
        if not is_ui(p) and len(p) > 100:
            start_idx = i
            break

    content_paras = [p for p in paragraphs[start_idx:] if not is_ui(p)]
    if content_paras:
        joined = " ".join(content_paras[:6])
        cleaned_joined = _clean_text(joined)
        if len(cleaned_joined) >= 200:
            return cleaned_joined

    # fallback: если не получилось, возьмём первые неплохие абзацы
    filtered = [p for p in paragraphs if not is_ui(p)]
    if filtered:
        joined2 = " ".join(filtered[:6])
        cleaned2 = _clean_text(joined2)
        if len(cleaned2) >= 200:
            return cleaned2

    # окончательный fallback: очищаем весь текст и вернём если он достаточно длинный
    cleaned = _clean_text(txt)
    if len(cleaned) >= 200:
        return cleaned
    return ""


def summarize_text(text: str, max_sentences: int = 3) -> str:
    if not text:
        return ""

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
    if openai and api_key:
        try:
            openai.api_key = api_key
            prompt = f"Summarize the following text in {max_sentences} short sentences:\n\n{text}"
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=200,
            )
            choice = resp.choices[0]
            msg = getattr(choice, "message", None)
            if msg:
                return msg.get("content", "").strip()
            return (choice.get("text") or "").strip()
        except Exception as e:
            LOG.debug("OpenAI summarization failed: %s", e)

    sents = _split_sentences(re.sub(r"\s+", " ", text))
    return " ".join(sents[:max_sentences])


def classify_text(text: str) -> str:
    if not text:
        return "other"
    t = text.lower()
    categories = {
        "politics": ["prezident", "hukumat", "siyosat", "saylov", "ministr", "parlament", "politik", "президент", "ҳукумат"],
        "sports": ["futbol", "liga", "superliga", "chempionat", "gol", "sport", "jamoa", "мусобақа"],
        "economy": ["dollar", "bank", "iqtisod", "narx", "invest", "inflation", "iqtisodiyot"],
        "tech": ["robot", "texnolog", "ai", "chatgpt", "sun'iy", "texnologiya", "gadjet"],
        "health": ["sog'liq", "tibbiyot", "virus", "vakcin", "вакцин", "kasal", "эпидem"],
        "culture": ["kino", "film", "san'at", "madaniyat", "konsert", "muzey", "foto"],
    }
    scores = {k: 0 for k in categories}
    for cat, kws in categories.items():
        for kw in kws:
            if kw in t:
                scores[cat] += 1
    best_cat, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score == 0:
        return "other"
    return best_cat


__all__ = ["extract_text_from_html", "summarize_text", "classify_text"]
