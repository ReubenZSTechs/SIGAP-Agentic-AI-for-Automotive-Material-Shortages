// Terjemahan sederhana: teks sumber di kode tetap Bahasa Indonesia, kamus `en.js` memberi versi Inggris.
//
//   t('Simpan')                         -> 'Save' (bila bahasa = en)
//   t('Hapus {name}?', { name: 'X' })   -> 'Delete X?'
//
// Teks yang belum ada di kamus tampil dalam Bahasa Indonesia (tidak pernah menampilkan "key" mentah).
// Saat bahasa diganti, seluruh aplikasi digambar ulang (lihat App.jsx), jadi `t` cukup fungsi biasa.
import { currentLang } from '../store/settingsStore';
import EN from './en';

export function t(text, vars) {
  if (typeof text !== 'string') return text;
  let out = currentLang() === 'en' ? (EN[text] ?? text) : text;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, String(v));
  }
  return out;
}

/** Terjemahkan bila nilainya teks biasa (untuk komponen umum yang menerima label/children). */
export const tx = (value) => (typeof value === 'string' ? t(value) : value);

/** Locale untuk format angka & tanggal. */
export const locale = () => (currentLang() === 'en' ? 'en-US' : 'id-ID');
