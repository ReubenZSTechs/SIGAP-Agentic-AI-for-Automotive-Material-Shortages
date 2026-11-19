import Icon from '../components/common/Icon';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import PageHeader from '../components/layout/PageHeader';
import EmptyState, { Spinner } from '../components/common/EmptyState';
import ManualPoForm from '../features/procurement/ManualPoForm';
import useFetch from '../hooks/useFetch';
import { purchaseOrderService } from '../services/purchaseOrderService';
import { useMasterStore } from '../store/masterStore';
import { toast } from '../store/toastStore';
import { t } from '../i18n';

// /purchase-orders/new  dan  /purchase-orders/:id/edit (Manual PO berstatus DRAFT / REJECTED)
export default function ManualPoPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { ensureLoaded, loaded } = useMasterStore();
  const [saving, setSaving] = useState(null); // 'draft' | 'submit' | null
  useEffect(() => { ensureLoaded(true); }, [ensureLoaded]);
  const po = useFetch(() => (id ? purchaseOrderService.get(id) : Promise.resolve(null)), [id]);

  if (!loaded || (id && po.loading)) return <Spinner />;
  if (id && (po.error || !po.data)) {
    return <EmptyState title={t('Data tidak ditemukan')} description={po.error?.message}
      action={<Link className="text-indigo-700 underline" to="/purchase-orders">{t('Kembali ke daftar PO')}</Link>} />;
  }
  if (id && !(po.data.source === 'MANUAL' && ['DRAFT', 'REJECTED'].includes(po.data.status))) {
    return <EmptyState title={t('PO ini tidak dapat diedit')}
      description={t('Hanya Manual PO berstatus Draft atau Ditolak yang dapat diedit.')}
      action={<Link className="text-indigo-700 underline" to={`/purchase-orders/${id}`}>{t('Lihat detail PO')}</Link>} />;
  }

  const save = async (payload, submit) => {
    setSaving(submit ? 'submit' : 'draft');
    try {
      const saved = id ? await purchaseOrderService.update(id, payload) : await purchaseOrderService.createManual(payload);
      if (saved.warnings?.length) toast.info(`Perhatian: ${saved.warnings.join('; ')}`);
      if (submit) { await purchaseOrderService.submit(saved.id); toast.success(t('PO disimpan & dikirim untuk approval')); }
      else toast.success('Draft PO disimpan');
      navigate(`/purchase-orders/${saved.id}`);
    } catch (e) { toast.error(e.message); } finally { setSaving(null); }
  };

  return (
    <>
      <PageHeader title={id ? t('Edit {po}', { po: po.data.po_number }) : t('Buat PO Manual')}
        subtitle={<Link className="inline-flex items-center gap-1 font-medium text-primary-700 hover:underline" to="/purchase-orders"><Icon name="arrowLeft" className="h-3.5 w-3.5" /> {t('Semua PO')}</Link>} />
      <ManualPoForm initial={po.data} saving={saving} onSubmit={save} />
    </>
  );
}
