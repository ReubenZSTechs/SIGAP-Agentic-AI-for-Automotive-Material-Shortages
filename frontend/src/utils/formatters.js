import { locale, t } from '../i18n';

export const formatRupiah = (n) =>
  new Intl.NumberFormat(locale(), { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(n ?? 0);

export const formatQty = (n) =>
  new Intl.NumberFormat(locale(), { maximumFractionDigits: 3 }).format(n ?? 0);

// Tanggal 'YYYY-MM-DD' di-parse sebagai tanggal lokal (hindari geser hari karena zona waktu).
export const formatDate = (iso) => {
  if (!iso) return '—';
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso);
  return d.toLocaleDateString(locale(), { day: '2-digit', month: 'short', year: 'numeric' });
};

export const formatDateTime = (iso) =>
  iso ? new Date(iso.endsWith('Z') ? iso : `${iso}Z`).toLocaleString(locale(), {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }) : '—';

export const formatLead = (d) => t('{n} hari', { n: d });

export const todayISO = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};
