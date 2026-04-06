import axios from 'axios';

const API_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://127.0.0.1:8889';

export const apiClient = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
