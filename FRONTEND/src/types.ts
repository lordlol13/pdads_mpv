export type AuthStep = 1 | 2 | 3 | 4;

export interface AuthFormData {
  name: string;
  email: string;
  password?: string;
  verificationCode: string[];
  interests: string[];
  profession: string;
  country: string;
  city: string;
}

export const INTERESTS_LIST = [
  "Design", "Development", "Marketing", "Business", "Photography", 
  "Music", "Art", "Science", "Technology", "Gaming", "Cooking", "Travel"
];
