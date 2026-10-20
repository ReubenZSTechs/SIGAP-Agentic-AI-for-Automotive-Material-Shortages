import { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Toaster from '../common/Toaster';
import Icon from '../common/Icon';
import useDisclosure from '../../hooks/useDisclosure';
import usePolling from '../../hooks/usePolling';
import { useHubStore } from '../../store/hubStore';

const KEY = 'sidebarCollapsed';
const readCollapsed = () => { try { return localStorage.getItem(KEY) === '1'; } catch { return false; } };

export default function AppLayout() {
  const menu = useDisclosure();
  const refreshStatus = useHubStore((s) => s.refreshStatus);
  useEffect(() => { refreshStatus(); }, [refreshStatus]);
  usePolling(refreshStatus, 15000); // lencana Hub di Sidebar
  const [collapsed, setCollapsed] = useState(readCollapsed); // hanya berlaku di desktop

  const toggle = () => setCollapsed((c) => {
    try { localStorage.setItem(KEY, c ? '0' : '1'); } catch { /* abaikan */ }
    return !c;
  });

  useEffect(() => { // pintasan Ctrl/Cmd + B
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); toggle(); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="flex min-h-full">
      {/* Desktop: sidebar 232px, dapat disembunyikan (invisible = keluar dari urutan tab) */}
      <aside aria-hidden={collapsed}
        className={`fixed inset-y-0 left-0 z-30 hidden transition-[transform,visibility] duration-200 motion-reduce:transition-none md:block ${
          collapsed ? 'invisible -translate-x-full' : ''}`}>
        <Sidebar onCollapse={toggle} />
      </aside>

      {/* Mobile: sidebar sebagai drawer */}
      {menu.open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="anim-fade absolute inset-0 bg-primary-950/55" onClick={menu.hide} />
          <div className="anim-slide absolute inset-y-0 left-0 shadow-2xl"><Sidebar onNavigate={menu.hide} /></div>
        </div>
      )}

      <div className={`min-w-0 flex-1 transition-[margin] duration-200 motion-reduce:transition-none ${collapsed ? 'md:ml-0' : 'md:ml-[232px]'}`}>
        {/* Mobile: bar atas. Desktop: bar tipis hanya saat sidebar tersembunyi */}
        <div className={`sticky top-0 z-30 items-center bg-primary-900 px-4 py-2.5 ${collapsed ? 'flex' : 'flex md:hidden'}`}>
          <button onClick={() => { if (window.matchMedia('(min-width: 768px)').matches) toggle(); else menu.show(); }}
            aria-label="Buka menu" title="Tampilkan menu (Ctrl+B)"
            className="-ml-1 rounded-lg p-1.5 text-primary-100 hover:bg-white/10"><Icon name="menu" className="h-5 w-5" /></button>
          <span className="ml-3 text-sm font-bold text-white">MRP MVP</span>
        </div>
        <main className={`mx-auto px-4 py-6 sm:px-6 lg:px-8 lg:py-8 ${collapsed ? 'max-w-[96rem]' : 'max-w-7xl'}`}><Outlet /></main>
      </div>
      <Toaster />
    </div>
  );
}
