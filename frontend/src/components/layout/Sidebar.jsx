import { NavLink } from 'react-router-dom';
import Icon from '../common/Icon';
import DisplayToggles from './DisplayToggles';
import { t } from '../../i18n';
import { useHubStore } from '../../store/hubStore';

const GROUPS = [
  { label: null, links: [{ to: '/', label: 'Dashboard', icon: 'spark', end: true }] },
  { label: 'Master', links: [
    { to: '/products', label: 'Produk Final', icon: 'box' },
    { to: '/materials', label: 'Material Beli', icon: 'layers' },
    { to: '/suppliers', label: 'Supplier', icon: 'truck' },
    { to: '/inventory', label: 'Inventory', icon: 'warehouse' },
  ] },
  { label: 'Produksi', links: [
    { to: '/bom', label: 'BOM', icon: 'tree' },
    { to: '/mps', label: 'MPS & Planning', icon: 'calendar' },
  ] },
  { label: 'Pembelian', links: [{ to: '/purchase-orders', label: 'Purchase Order', icon: 'file' }] },
  { label: 'Agent', links: [{ to: '/supplier-hub', label: 'Hub Supplier', icon: 'inbox', badge: true }] },
];

export default function Sidebar({ onNavigate, onCollapse }) {
  const pending = useHubStore((s) => s.pending);
  return (
    <nav className="flex h-full w-[232px] flex-col bg-primary-900 px-3 py-5" aria-label={t('Menu utama')}>
      <div className="mb-3 flex items-center gap-2.5 px-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-white"><Icon name="box" className="h-[18px] w-[18px]" /></span>
        <span className="leading-tight">
          <span className="block text-sm font-bold text-white">MRP MVP</span>
          <span className="block text-xs text-primary-300">Vendor Sourcing</span>
        </span>
        {onCollapse && (
          <button type="button" onClick={onCollapse} aria-label={t('Sembunyikan menu')} title={t('Sembunyikan menu (Ctrl+B)')}
            className="ml-auto rounded-lg p-1.5 text-primary-300 transition-colors hover:bg-white/10 hover:text-white">
            <Icon name="panelLeft" className="h-[18px] w-[18px]" />
          </button>
        )}
      </div>
      <DisplayToggles className="mb-6 px-2" />
      <div className="flex-1 overflow-y-auto">
        {GROUPS.map((g, i) => (
          <div key={i} className="mb-5">
            {g.label && <div className="mb-1.5 px-2 text-xs font-medium text-primary-300/80">{t(g.label)}</div>}
            <div className="space-y-0.5">
              {g.links.map((l) => (
                <NavLink key={l.to} to={l.to} end={l.end} onClick={onNavigate}
                  className={({ isActive }) =>
                    `relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-white/10 text-white before:absolute before:inset-y-2 before:-left-3 before:w-[3px] before:rounded-r before:bg-brand'
                        : 'text-primary-100/80 hover:bg-white/5 hover:text-white'}`}>
                  <Icon name={l.icon} className="h-[18px] w-[18px]" />
                  {t(l.label)}
                  {l.badge && pending > 0 && (
                    <span className="ml-auto rounded-md bg-amber-400 px-1.5 text-xs font-bold text-primary-950" aria-label={t('{n} menunggu persetujuan', { n: pending })}>{pending}</span>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </div>
    </nav>
  );
}
