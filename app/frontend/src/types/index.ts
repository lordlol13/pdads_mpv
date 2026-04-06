export interface User {
  id: number;
  username: string;
  email: string | null;
  location: string | null;
  interests: Record<string, unknown> | null;
  is_active: boolean | null;
  is_verified: boolean | null;
  country_code: string | null;
  region_code: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  location?: string | null;
  interests?: Record<string, unknown> | null;
  country_code?: string | null;
  region_code?: string | null;
}

export interface LoginRequest {
  identifier: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
}

export interface CheckAvailabilityRequest {
  username?: string;
  email?: string;
}

export interface CheckAvailabilityResponse {
  username_exists: boolean | null;
  email_exists: boolean | null;
}

export interface RegisterStartRequest {
  username: string;
  email: string;
  password: string;
}

export interface RegisterStartResponse {
  verification_id: string;
  expires_in_seconds: number;
  debug_code?: string | null;
}

export interface VerifyCodeRequest {
  verification_id: string;
  code: string;
}

export interface VerifyCodeResponse {
  verification_id: string;
  verified: boolean;
}

export interface RegisterCompleteRequest {
  verification_id: string;
  interests: string[];
  custom_interests?: string[];
  profession?: string | null;
  country_code?: string | null;
  country_name?: string | null;
  city?: string | null;
  region_code?: string | null;
}

export interface FeedItem {
  user_feed_id: number;
  user_id: number;
  ai_news_id: number;
  raw_news_id: number | null;
  target_persona: string | null;
  final_title: string | null;
  final_text: string | null;
  image_urls: string[] | null;
  video_urls: string[] | null;
  category: string | null;
  ai_score: number | null;
  vector_status: string | null;
  liked: boolean | null;
  saved: boolean | null;
  comment_count: number;
  created_at: string | null;
}

export interface InteractionCreateRequest {
  user_id: number;
  ai_news_id: number;
  liked?: boolean;
  viewed?: boolean;
  watch_time?: number;
}

export interface InteractionResponse {
  id: number;
  status: string;
}

export interface SavedToggleRequest {
  ai_news_id: number;
}

export interface SavedToggleResponse {
  ai_news_id: number;
  saved: boolean;
}

export interface CommentCreateRequest {
  ai_news_id: number;
  parent_comment_id?: number | null;
  content: string;
}

export interface CommentItem {
  id: number;
  ai_news_id: number;
  user_id: number;
  username: string;
  parent_comment_id: number | null;
  content: string;
  like_count: number;
  liked_by_me: boolean;
  created_at: string | null;
  replies: CommentItem[];
}

export interface CommentLikeToggleResponse {
  comment_id: number;
  liked: boolean;
  like_count: number;
}
