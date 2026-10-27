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

// Waktu relatif mengikuti bahasa UI ("5 menit yang lalu" / "5 minutes ago"); lebih dari seminggu -> tanggal.
// `iso` = waktu UTC dari backend (tanpa 'Z', sama seperti formatDateTime).
export const timeAgo = (iso) => {
  if (!iso) return '';
  const then = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
  const seconds = Math.round((then.getTime() - Date.now()) / 1000); // negatif = sudah lewat
  const abs = Math.abs(seconds);
  const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' });
  if (abs < 60) return rtf.format(0, 'second');
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour');
  if (abs < 7 * 86400) return rtf.format(Math.round(seconds / 86400), 'day');
  return then.toLocaleDateString(locale(), { day: '2-digit', month: 'short', year: 'numeric' });
};

export const formatLead = (d) => t('{n} hari', { n: d });

export const todayISO = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};