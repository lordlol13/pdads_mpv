import { ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthLayout } from './components/layout/AuthLayout';
import { MainTabsLayout } from './components/layout/MainTabsLayout';
import { I18nProvider, useI18n } from './context/I18nContext';
import { AuthPage } from './pages/auth/AuthPage';
import { NewsFeed } from './pages/feed/NewsFeed';
import { SearchPage } from './pages/search/SearchPage';
import { ProfilePage } from './pages/profile/ProfilePage';
import { AuthProvider, useAuth } from './context/AuthContext';

const queryClient = new QueryClient();

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const { t } = useI18n();

  if (isLoading) {
    return <div className="p-8 text-center text-sm text-on-surface-variant">{t('common.loading')}</div>;
  }

  if (!user) {
    return <Navigate to="/auth" replace />;
  }

  return children;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route element={<AuthLayout />}>
                <Route path="/auth" element={<AuthPage />} />
                <Route path="/register/step1" element={<Navigate to="/auth" replace />} />
                <Route path="/register/step2" element={<Navigate to="/auth" replace />} />
                <Route path="/register/step3" element={<Navigate to="/auth" replace />} />
                <Route path="/register/success" element={<Navigate to="/app/home" replace />} />
                <Route path="/" element={<Navigate to="/auth" replace />} />
              </Route>
              <Route
                path="/app"
                element={
                  <RequireAuth>
                    <MainTabsLayout />
                  </RequireAuth>
                }
              >
                <Route path="home" element={<NewsFeed />} />
                <Route path="search" element={<SearchPage />} />
                <Route path="profile" element={<ProfilePage />} />
                <Route index element={<Navigate to="/app/home" replace />} />
              </Route>

              <Route path="/feed" element={<Navigate to="/app/home" replace />} />

              <Route path="*" element={<Navigate to="/auth" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
