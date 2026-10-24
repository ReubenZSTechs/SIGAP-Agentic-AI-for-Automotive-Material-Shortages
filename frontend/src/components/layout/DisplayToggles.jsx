import Icon from '../common/Icon';
import { t } from '../../i18n';
import { useSettings } from '../../store/settingsStore';

// Tombol bahasa (ID / EN) dan tema (terang / gelap). Dipakai di Sidebar dan bar atas.
export default function DisplayToggles({ className = '' }) {
  const { lang, theme, toggleLang, toggleTheme } = useSettings();
  const dark = theme === 'dark';
  const btn = 'inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-primary-100 '
    + 'ring-1 ring-inset ring-white/15 transition-colors hover:bg-white/10 hover:text-white';
  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      <button type="button" onClick={toggleLang} className={btn}
        aria-label={t('Ganti bahasa')} title={t('Ganti bahasa')}>
        <Icon name="globe" className="h-3.5 w-3.5" />
        <span className={lang === 'id' ? 'text-white' : 'opacity-60'}>ID</span>
        <span className="opacity-40">/</span>
        <span className={lang === 'en' ? 'text-white' : 'opacity-60'}>EN</span>
      </button>
      <button type="button" onClick={toggleTheme} className={btn}
        aria-label={dark ? t('Mode terang') : t('Mode gelap')} title={dark ? t('Mode terang') : t('Mode gelap')}>
        <Icon name={dark ? 'sun' : 'moon'} className="h-3.5 w-3.5" />
        {dark ? t('Terang') : t('Gelap')}
      </button>
    </div>
  );
}
