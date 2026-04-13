import { apiRequest, clearAuthToken, setAuthToken } from './client';
import {
  CheckAvailabilityResponse,
  AuthResendVerificationResponse,
  OAuthProvidersResponse,
  CommentItem,
  CommentLikeToggleResponse,
  FeedItem,
  InteractionResponse,
  RegisterStartResponse,
  SavedToggleResponse,
  TokenResponse,
  UserPublic,
  VerifyCodeResponse,
} from '../types';

export const authService = {
  getOAuthProviders: () =>
    apiRequest<OAuthProvidersResponse>('/auth/oauth/providers', { method: 'GET', auth: false }),

  checkAvailability: (payload: { username?: string; email?: string }) =>
    apiRequest<CheckAvailabilityResponse>('/auth/check-availability', { method: 'POST', body: payload, auth: false }),

  registerStart: (payload: { username: string; email: string; password: string }) =>
    apiRequest<RegisterStartResponse>('/auth/register/start', { method: 'POST', body: payload, auth: false }),

  verifyCode: (payload: { verification_id: string; code: string }) =>
    apiRequest<VerifyCodeResponse>('/auth/register/verify', { method: 'POST', body: payload, auth: false }),

  resendCode: (payload: { verification_id: string }) =>
    apiRequest<AuthResendVerificationResponse>('/auth/register/resend', { method: 'POST', body: payload, auth: false }),

  registerComplete: (payload: {
    verification_id: string;
    interests: string[];
    custom_interests: string[];
    profession?: string | null;
    country_code?: string | null;
    country_name?: string | null;
    city?: string | null;
    region_code?: string | null;
  }) => apiRequest<UserPublic>('/auth/register/complete', { method: 'POST', body: payload, auth: false }),

  login: async (payload: { identifier: string; password: string }): Promise<TokenResponse> => {
    const response = await apiRequest<TokenResponse>('/auth/login', {
      method: 'POST',
      body: payload,
      auth: false,
    });
    setAuthToken(response.access_token);
    return response;
  },

  forgotPassword: (payload: { email: string }) =>
    apiRequest<{ sent: boolean }>('/auth/password/forgot', { method: 'POST', body: payload, auth: false }),

  resetPassword: (payload: { email: string; code: string; new_password: string }) =>
    apiRequest<{ success: boolean }>('/auth/password/reset', { method: 'POST', body: payload, auth: false }),

  getMe: () => apiRequest<UserPublic>('/auth/me'),

  logout: () => {
    clearAuthToken();
  },
};

export const newsService = {
  getFeed: (limit = 50) => apiRequest<FeedItem[]>('/feed/me', { params: { limit } }),

  search: (query: string, limit = 50) => apiRequest<FeedItem[]>('/feed/search', { params: { q: query, limit } }),

  react: (payload: { user_id: number; ai_news_id: number; liked?: boolean; viewed?: boolean; watch_time?: number | null }) =>
    apiRequest<InteractionResponse>('/feed/interactions', { method: 'POST', body: payload }),

  toggleSaved: (payload: { ai_news_id: number }) =>
    apiRequest<SavedToggleResponse>('/feed/saved/toggle', { method: 'POST', body: payload }),

  getComments: (aiNewsId: number) => apiRequest<CommentItem[]>(`/feed/comments/${aiNewsId}`),

  createComment: (payload: { ai_news_id: number; parent_comment_id?: number | null; content: string }) =>
    apiRequest<CommentItem>('/feed/comments', { method: 'POST', body: payload }),

  toggleCommentLike: (commentId: number) =>
    apiRequest<CommentLikeToggleResponse>(`/feed/comments/${commentId}/like-toggle`, { method: 'POST' }),
};
