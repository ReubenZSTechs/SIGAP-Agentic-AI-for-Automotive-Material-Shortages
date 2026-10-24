import { Link } from 'react-router-dom';
import EmptyState from '../components/common/EmptyState';
import { t } from '../i18n';

export default function NotFoundPage() {
  return (
    <EmptyState title={t('Halaman tidak ditemukan')} description={t('Alamat yang Anda buka tidak tersedia.')}
      action={<Link className="text-indigo-700 underline" to="/">{t('Ke Dashboard')}</Link>} />
  );
}
