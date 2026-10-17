import { Link } from 'react-router-dom';
import EmptyState from '../components/common/EmptyState';

export default function NotFoundPage() {
  return (
    <EmptyState title="Halaman tidak ditemukan" description="Alamat yang Anda buka tidak tersedia."
      action={<Link className="text-indigo-700 underline" to="/">Ke Dashboard</Link>} />
  );
}
