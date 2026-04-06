import { Home, Search, UserRound } from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';

import { useI18n } from '../../context/I18nContext';

const tabs = [
  { to: '/app/home', key: 'tabs.home', icon: Home },
  { to: '/app/search', key: 'tabs.search', icon: Search },
  { to: '/app/profile', key: 'tabs.profile', icon: UserRound },
] as const;

export function MainTabsLayout() {
  const { t } = useI18n();

  return (
    <div className="relative min-h-screen bg-black">
      <Outlet />

      <nav className="fixed inset-x-0 bottom-0 z-[80] border-t border-white/15 bg-black/80 backdrop-blur-xl">
        <div className="mx-auto grid max-w-xl grid-cols-3 px-2 py-2">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <NavLink
                key={tab.to}
                to={tab.to}
                className={({ isActive }) =>
                  `flex flex-col items-center justify-center rounded-xl px-3 py-2 text-[11px] transition ${
                    isActive ? 'text-white' : 'text-white/65 hover:text-white/90'
                  }`
                }
              >
                <Icon size={18} />
                <span className="mt-1 font-semibold">{t(tab.key)}</span>
              </NavLink>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
