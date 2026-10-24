import { formatDate, formatQty, formatRupiah } from '../../utils/formatters';
import { locale, t } from '../../i18n';

// Registry jenis kartu. Jenis tak dikenal otomatis memakai tampilan generik.
export const TYPE = {
  PO_REVISION: { label: 'Revisi PO', tone: 'violet', options: true },
  PRICE_UPDATE: { label: 'Harga', tone: 'indigo', selectable: true },
  PO_DELAY: { label: 'Keterlambatan PO', tone: 'amber', hero: true },
  STOCK_CHECK: { label: 'Stok', tone: 'slate' },
};
export const typeMeta = (t) => TYPE[t] ?? { label: 'Tindakan lain', tone: 'slate' };
export const RISK = { LOW: { label: 'Rendah', tone: 'slate' }, MEDIUM: { label: 'Sedang', tone: 'amber' }, HIGH: { label: 'Tinggi', tone: 'red' } };
export const DECISION = {
  PENDING: { label: 'Menunggu', tone: 'amber' }, APPROVED: { label: 'Disetujui', tone: 'green' },
  REJECTED: { label: 'Ditolak', tone: 'red' }, REVISION: { label: 'Revisi diminta', tone: 'slate' },
  EXPIRED: { label: 'Kedaluwarsa', tone: 'slate' }, FAILED: { label: 'Gagal diterapkan', tone: 'red' },
};
export const CONFIDENCE = { HIGH: { label: 'Keyakinan tinggi', dot: 'bg-green-600' }, MEDIUM: { label: 'Keyakinan sedang', dot: 'bg-amber-500' }, LOW: { label: 'Keyakinan rendah', dot: 'bg-red-500' } };

export const msLeft = (iso) => new Date(iso).getTime() - Date.now();
export const isUrgent = (it) => it.status === 'PENDING' && msLeft(it.expires_at) < 2 * 3600e3;
export function timeLeft(iso) {
  const ms = msLeft(iso);
  if (ms <= 0) return t('kedaluwarsa');
  const h = Math.floor(ms / 3600e3); const m = Math.floor((ms % 3600e3) / 60e3);
  return h > 0 ? t('{h} jam {m} mnt', { h, m }) : t('{m} mnt', { m });
}

export function fmt(v, unit) {
  if (v == null) return '-';
  if (unit === 'Rp') return formatRupiah(v);
  if (unit === 'qty') return formatQty(v);
  if (unit === 'date') return formatDate(v);
  return String(v);
}
// Selisih numerik atau tanggal. tone mengikuti arti bisnis (direction), bukan arah angka.
export function delta(r) {
  let value; let text;
  if (r.before == null || r.after == null) return null; // nilai lama kosong (mis. tanggal belum diisi): tanpa selisih
  if (r.unit === 'date') {
    value = Math.round((new Date(r.after) - new Date(r.before)) / 864e5);
    text = `${value > 0 ? '+' : ''}${t('{n} hari', { n: value })}`;
  } else if (typeof r.before === 'number' && typeof r.after === 'number' && r.before !== 0) {
    value = ((r.after - r.before) / r.before) * 100;
    text = `${value > 0 ? '+' : ''}${value.toFixed(1).replace('.', ',')}%`;
  } else return null;
  const sign = Math.sign(value);
  let tone = 'text-slate-500';
  if (sign !== 0 && r.direction !== 'neutral') {
    const good = r.direction === 'higher-better' ? sign > 0 : sign < 0;
    tone = good ? 'text-green-700' : 'text-red-700';
  }
  return { text, tone, sign };
}

// ---- Percakapan ----
export const THREAD_MODE = { AGENT: { label: 'Ditangani Agent', tone: 'indigo' }, HUMAN: { label: 'Diambil alih', tone: 'amber' } };
// Telegram Bot API tidak memberi tanda baca, jadi hanya terkirim / gagal / tersimpan (sandbox).
export const MSG_STATUS = {
  SENT: { label: 'Terkirim', icon: 'check' }, SANDBOX: { label: 'Tersimpan (sandbox)', icon: 'check' },
  FAILED: { label: 'Gagal', icon: 'alert' },
};
export const TELEGRAM = {
  CONNECTED: { label: 'Terhubung', tone: 'green' }, PENDING: { label: 'Menunggu', tone: 'amber' },
  NOT_CONNECTED: { label: 'Belum terhubung', tone: 'slate' }, FAILED: { label: 'Gagal', tone: 'red' },
};

// ---- Misi ----
// needsItem: misi dari material wajib memilih item; poOnly: hanya bisa dibuat dari PO (ke supplier PO saja).
export const SCENARIO = {
  PRICE_QUOTE: { label: 'Penawaran harga', icon: 'tag', desc: 'Minta harga dan lead time terbaru dari beberapa supplier.', needsItem: true },
  STOCK_CHECK: { label: 'Cek ketersediaan stok', icon: 'box', desc: 'Pastikan supplier sanggup sebelum PO disetujui atau diterbitkan.', needsItem: true },
  DELIVERY_CONFIRM: { label: 'Konfirmasi jadwal kirim', icon: 'truck', desc: 'Tanyakan apakah PO yang sudah terbit masih sesuai jadwal.', poOnly: true },
  DOC_REQUEST: { label: 'Minta dokumen', icon: 'file', desc: 'Minta invoice, surat jalan, atau faktur pajak.', poSupplierOnly: true },
};
export const MISSION_STATUS = {
  ACTIVE: { label: 'Berjalan', tone: 'indigo' }, SUMMARIZING: { label: 'Merangkum', tone: 'amber' },
  DONE: { label: 'Selesai', tone: 'green' }, CANCELLED: { label: 'Dibatalkan', tone: 'slate' },
};
export const MISSION_STEPS = ['Rencana', 'Kirim', 'Kumpulkan', 'Rangkum', 'Ajukan'];
export const TARGET_STATE = {
  QUEUED: { label: 'Antre', tone: 'slate' }, SENT: { label: 'Menunggu balasan', tone: 'indigo' },
  PAUSED: { label: 'Ditunda (ada percakapan PO)', tone: 'amber' }, REPLIED: { label: 'Dibalas', tone: 'green' },
  NO_REPLY: { label: 'Tanpa balasan', tone: 'amber' }, ESCALATED: { label: 'Eskalasi', tone: 'red' },
};
export const AUTONOMY = {
  AUTO: { label: 'Kirim otomatis', desc: 'Pesan template langsung dikirim. Balasan disimpan otomatis.' },
  REVIEW: { label: 'Draf dulu', desc: 'Setiap pesan menunggu review Anda di Percakapan sebelum dikirim.' },
};

// ---- Dokumen ----
export const DOC_TYPE = { INVOICE: 'Invoice', DELIVERY_NOTE: 'Surat jalan', TAX_INVOICE: 'Faktur pajak', OTHER: 'Dokumen lain' };
export const DOC_STATUS = {
  NEEDS_REVIEW: { label: 'Perlu validasi', tone: 'amber' }, ARCHIVED: { label: 'Diarsipkan', tone: 'green' }, REREQUESTED: { label: 'Diminta ulang', tone: 'slate' },
};

// ---- Waktu ----
const toDate = (iso) => new Date(iso);
export const clock = (iso) => toDate(iso).toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit' });
const sameDay = (a, b) => a.toDateString() === b.toDateString();
export function dayLabel(iso) {
  const d = toDate(iso); const today = new Date(); const yday = new Date(Date.now() - 864e5);
  if (sameDay(d, today)) return t('Hari ini');
  if (sameDay(d, yday)) return t('Kemarin');
  return d.toLocaleDateString(locale(), { weekday: 'long', day: 'numeric', month: 'long' });
}
// "10.42" untuk hari ini, "Kemarin" atau "18 Okt" untuk sebelumnya.
export function shortTime(iso) {
  if (!iso) return '';
  const d = toDate(iso);
  if (sameDay(d, new Date())) return clock(iso);
  if (sameDay(d, new Date(Date.now() - 864e5))) return t('Kemarin');
  return d.toLocaleDateString(locale(), { day: 'numeric', month: 'short' });
}
export const dayTime = (iso) => toDate(iso).toLocaleString(locale(), { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
export const initials = (name) => name.replace(/^(PT|CV|UD)\.?\s+/i, '').split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();

// Nama approver diingat peramban (MVP tanpa autentikasi, sama dengan DecisionModal).
export const approverName = () => { try { return localStorage.getItem('approverName') || 'Admin'; } catch { return 'Admin'; } };
