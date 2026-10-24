import Icon from '../components/common/Icon';
import { useState } from 'react';
import PageHeader from '../components/layout/PageHeader';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import ConfirmDialog from '../components/common/ConfirmDialog';
import SupplierTable from '../features/material/SupplierTable';
import SupplierFormModal from '../features/material/SupplierFormModal';
import useFetch from '../hooks/useFetch';
import { supplierService } from '../services/supplierService';
import { useMasterStore } from '../store/masterStore';
import { toast } from '../store/toastStore';
import { t } from '../i18n';

export default function SuppliersPage() {
  const [form, setForm] = useState({ open: false, supplier: null });
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);
  const { ensureLoaded, invalidate } = useMasterStore();
  const { data, loading, error, reload } = useFetch(() => supplierService.list(), []);

  const afterChange = () => { invalidate(); ensureLoaded(true); reload(); };

  const remove = async () => {
    setBusy(true);
    try {
      await supplierService.remove(deleting.id);
      toast.success('Supplier dihapus');
      afterChange();
    } catch (e) {
      toast.error(e.status === 409 ? t('Supplier masih dipakai (relasi material/PO) — nonaktifkan lewat Edit.') : e.message);
    } finally { setBusy(false); setDeleting(null); }
  };

  return (
    <>
      <PageHeader title={t('Supplier')} subtitle={t('Phase 0 — Master Supplier')}
        actions={<Button onClick={() => setForm({ open: true, supplier: null })}><Icon name="plus" /> {t('Tambah Supplier')}</Button>} />
      <Card padded={false}>
        {error ? <p className="p-4 text-sm text-red-600">{error.message}</p> : (
          <SupplierTable rows={data} loading={loading}
            onEdit={(s) => setForm({ open: true, supplier: s })} onDelete={setDeleting} />
        )}
      </Card>
      <SupplierFormModal open={form.open} supplier={form.supplier}
        onClose={() => setForm({ open: false, supplier: null })}
        onSaved={() => { setForm({ open: false, supplier: null }); afterChange(); }} />
      <ConfirmDialog open={!!deleting} loading={busy}
        message={t('Hapus supplier {name}?', { name: deleting?.name })} onConfirm={remove} onCancel={() => setDeleting(null)} />
    </>
  );
}
