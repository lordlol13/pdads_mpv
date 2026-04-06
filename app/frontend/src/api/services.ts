import { apiClient } from './client';
import {
  CommentCreateRequest,
  CommentItem,
  CommentLikeToggleResponse,
  CheckAvailabilityRequest,
  CheckAvailabilityResponse,
  FeedItem,
  InteractionCreateRequest,
  InteractionResponse,
  LoginRequest,
  RegisterCompleteRequest,
  RegisterRequest,
  SavedToggleRequest,
  SavedToggleResponse,
  RegisterStartRequest,
  RegisterStartResponse,
  TokenResponse,
  User,
  VerifyCodeRequest,
  VerifyCodeResponse,
} from '../types';

export const authService = {
  checkAvailability: async (data: CheckAvailabilityRequest): Promise<CheckAvailabilityResponse> => {
    const response = await apiClient.post('/auth/check-availability', data);
    return response.data;
  },

  registerStart: async (data: RegisterStartRequest): Promise<RegisterStartResponse> => {
    const response = await apiClient.post('/auth/register/start', data);
    return response.data;
  },

  verifyCode: async (data: VerifyCodeRequest): Promise<VerifyCodeResponse> => {
    const response = await apiClient.post('/auth/register/verify', data);
    return response.data;
  },

  registerComplete: async (data: RegisterCompleteRequest): Promise<User> => {
    const response = await apiClient.post('/auth/register/complete', data);
    return response.data;
  },

  register: async (data: RegisterRequest): Promise<User> => {
    const response = await apiClient.post('/auth/register', data);
    return response.data;
  },

  login: async (data: LoginRequest): Promise<TokenResponse> => {
    const response = await apiClient.post('/auth/login', data);
    return response.data;
  },

  getMe: async (): Promise<User> => {
    const response = await apiClient.get('/auth/me');
    return response.data;
  },
};

export const newsService = {
  getFeed: async (limit = 50): Promise<FeedItem[]> => {
    const response = await apiClient.get('/feed/me', { params: { limit } });
    return response.data;
  },

  react: async (payload: InteractionCreateRequest): Promise<InteractionResponse> => {
    const response = await apiClient.post('/feed/interactions', payload);
    return response.data;
  },

  toggleSaved: async (payload: SavedToggleRequest): Promise<SavedToggleResponse> => {
    const response = await apiClient.post('/feed/saved/toggle', payload);
    return response.data;
  },

  getComments: async (aiNewsId: number): Promise<CommentItem[]> => {
    const response = await apiClient.get(`/feed/comments/${aiNewsId}`);
    return response.data;
  },

  createComment: async (payload: CommentCreateRequest): Promise<CommentItem> => {
    const response = await apiClient.post('/feed/comments', payload);
    return response.data;
  },

  toggleCommentLike: async (commentId: number): Promise<CommentLikeToggleResponse> => {
    const response = await apiClient.post(`/feed/comments/${commentId}/like-toggle`);
    return response.data;
  },
};
