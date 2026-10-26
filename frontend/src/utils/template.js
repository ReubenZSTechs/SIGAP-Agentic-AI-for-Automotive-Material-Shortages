import { locale } from '../i18n';

// Tenggat misi dalam bahasa sehari-hari, mis. "Kamis, 22 Okt pukul 17.00".
export const formatDeadline = (iso) => new Date(iso).toLocaleString(locale(), {
  weekday: 'long', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
}).replace(/,?\s(\d{2})\.(\d{2})$/, ' pukul $1.$2');
