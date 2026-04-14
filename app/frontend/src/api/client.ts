import { TokenResponse } from '../types';

// Production hosts — used as fallbacks when VITE_API_BASE_URL is not set in env
const PROD_FRONTEND_ORIGIN = 'https://pdads-mpv.vercel.app';
const PROD_API_BASE = 'https://pdadsmpv-production.up.railway.app/api';

const rawEnvBase = import.meta.env.VITE_API_BASE_URL || '';
const envBase = rawEnvBase ? rawEnvBase.replace(/\/+$, '') : '';

const API_BASE = (() => {
  if (envBase) return envBase;
  if (typeof window !== 'undefined' && window.location?.origin === PROD_FRONTEND_ORIGIN) {
    return PROD_API_BASE;
  }
  return '/api';
})();

const TOKEN_KEY = 'token';

export function buildApiUrl(path: string, params?: RequestOptions['params']): string {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === null || value === undefined || value === '') {
        continue;
      }
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
  params?: Record<string, string | number | boolean | null | undefined>;
};

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  if (options.auth !== false) {
    const token = getAuthToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }

  const response = await fetch(buildApiUrl(path, options.params), {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();

  if (!response.ok) {
    const message =
      typeof payload === 'string'
        ? payload
        : payload?.detail?.message ||
          payload?.detail ||
          payload?.error?.message ||
          payload?.message ||
          'Request failed';
    throw new Error(message);
  }

  return payload as T;
}

export function isTokenResponse(value: unknown): value is TokenResponse {
  return Boolean(value && typeof value === 'object' && 'access_token' in value);
}
