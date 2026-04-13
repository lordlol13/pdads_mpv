export type AuthStep = 1 | 2 | 3 | 4;

export interface AuthFormData {
  name: string;
  email: string;
  password: string;
  verificationCode: string[];
  interests: string[];
  customInterests: string[];
  profession: string;
  country: string;
  countryCode: string;
  countryName: string;
  city: string;
  regionCode: string;
  verificationId: string;
}

export const INTERESTS_LIST = [
  "Design", "Development", "Marketing", "Business", "Photography", 
  "Music", "Art", "Science", "Technology", "Gaming", "Cooking", "Travel"
];

export interface UserPublic {
  id: number;
  username: string;
  email?: string | null;
  location?: string | null;
  interests?: Record<string, unknown> | null;
  is_active?: boolean | null;
  is_verified?: boolean | null;
  country_code?: string | null;
  region_code?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
}

export interface RegisterStartResponse {
  verification_id: string;
  expires_in_seconds: number;
  debug_code?: string | null;
}

export interface VerifyCodeResponse {
  verification_id: string;
  verified: boolean;
}

export interface AuthResendVerificationResponse {
  verification_id: string;
  expires_in_seconds: number;
  sent: boolean;
  debug_code?: string | null;
}

export interface CheckAvailabilityResponse {
  username_exists?: boolean | null;
  email_exists?: boolean | null;
}

export interface OAuthProvidersResponse {
  providers: string[];
}

export interface FeedItem {
  user_feed_id: number;
  user_id: number;
  ai_news_id: number;
  raw_news_id?: number | null;
  target_persona?: string | null;
  final_title?: string | null;
  final_text?: string | null;
  image_urls?: string[] | null;
  video_urls?: string[] | null;
  category?: string | null;
  ai_score?: number | null;
  vector_status?: string | null;
  liked?: boolean | null;
  like_count: number;
  saved?: boolean | null;
  comment_count: number;
  created_at?: string | null;
}

export interface CommentItem {
  id: number;
  ai_news_id: number;
  user_id: number;
  username: string;
  parent_comment_id?: number | null;
  content: string;
  like_count: number;
  liked_by_me: boolean;
  created_at?: string | null;
  replies: CommentItem[];
}

export interface SavedToggleResponse {
  ai_news_id: number;
  saved: boolean;
}

export interface CommentLikeToggleResponse {
  comment_id: number;
  liked: boolean;
  like_count: number;
}

export interface InteractionResponse {
  id: number;
  status: string;
}
