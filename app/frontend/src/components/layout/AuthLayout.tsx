import React from 'react';
import { Outlet } from 'react-router-dom';
import { useI18n } from '../../context/I18nContext';

export const AuthLayout = () => {
  const { t } = useI18n();

  return (
    <div className="min-h-screen flex flex-col bg-surface">
      <main className="flex-grow flex flex-col items-center px-4 py-16">
        <Outlet />
      </main>
      <footer className="w-full py-8 text-center text-[0.6875rem] uppercase tracking-[0.05em] font-medium text-on-surface/40">
        {t('layout.footer')}
      </footer>
    </div>
  );
};
