const ENGLISH_TITLE_STOPWORDS = new Set([
  'the',
  'and',
  'of',
  'to',
  'in',
  'for',
  'with',
  'on',
  'from',
  'by',
  'is',
  'are',
  'was',
  'were',
  'after',
  'before',
  'into',
  'warning',
  'adds',
  'uncertainty',
  'shipping',
  'today',
  'breaking',
  'report',
  'story',
  'latest',
  'update',
  'watch',
  'video',
  'more',
]);

function looksEnglishHeavy(value: string): boolean {
  const tokens = (value.toLowerCase().match(/[a-z']+/g) || []).filter(Boolean);
  if (tokens.length < 4) {
    return false;
  }

  const stopwordHits = tokens.reduce((count, token) => count + (ENGLISH_TITLE_STOPWORDS.has(token) ? 1 : 0), 0);
  return stopwordHits >= 2 && stopwordHits / tokens.length >= 0.2;
}

function stripHeadingPrefix(value: string): string {
  return value.replace(/^(?:yangilik|yanglik|news|новость|headline|sarlavha)\s*[:\-–—]+\s*/i, '').trim();
}

export function normalizeFeedTitle(value: string | null | undefined): string {
  const source = String(value || '').trim();
  if (!source) {
    return '';
  }

  const cleaned = stripHeadingPrefix(source).replace(/\s{2,}/g, ' ').trim();
  if (!cleaned || looksEnglishHeavy(cleaned)) {
    return '';
  }

  return cleaned;
}

export function getUzbekHeadlineFallback(id: number): string {
  return `Dolzarb xabar #${id}`;
}