import { create } from 'zustand';

// Pengaturan tampilan per pengguna (bahasa & tema), disimpan di localStorage browser.
const KEY = 'sigap-settings';

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) ?? {};
  } catch {
    return {};
  }
}

function save(settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    /* storage tidak tersedia: pengaturan hanya berlaku selama halaman terbuka */
  }
}

const prefersDark = () => {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    return false;
  }
};

/** Pasang pengaturan ke elemen <html> (CSS tema & atribut bahasa membaca dari sini). */
function apply({ lang, theme }) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.lang = lang;
}

const saved = load();
const initial = { lang: saved.lang ?? 'id', theme: saved.theme ?? (prefersDark() ? 'dark' : 'light') };
apply(initial);

export const useSettings = create((set, get) => ({
  ...initial,
  setLang: (lang) => {
    set({ lang });
    save({ lang, theme: get().theme });
    apply(get());
  },
  toggleLang: () => get().setLang(get().lang === 'id' ? 'en' : 'id'),
  toggleTheme: () => {
    const theme = get().theme === 'dark' ? 'light' : 'dark';
    set({ theme });
    save({ lang: get().lang, theme });
    apply(get());
  },
}));

/** Bahasa aktif tanpa hook (untuk fungsi biasa: formatter, service, toast). */
export const currentLang = () => useSettings.getState().lang;
