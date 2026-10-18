import Icon from '../components/common/Icon';
import { useEffect, useState } from 'react';
import PageHeader from '../components/layout/PageHeader';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import ConfirmDialog from '../components/common/ConfirmDialog';
import Input from '../components/common/Input';
import MaterialTable from '../features/material/MaterialTable';
import MaterialFormModal from '../features/material/MaterialFormModal';
import MaterialSupplierModal from '../features/material/MaterialSupplierModal';
import useFetch from '../hooks/useFetch';
import { materialService } from '../services/materialService';
import { useMasterStore } from '../store/masterStore';
import { toast } from '../store/toastStore';

export default function MaterialsPage() {
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [form, setForm] = useState({ open: false, material: null });
  const [supplierFor, setSupplierFor] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);
  const { ensureLoaded, invalidate } = useMasterStore();

  useEffect(() => { ensureLoaded(); }, [ensureLoaded]); // dropdown supplier untuk modal relasi
  useEffect(() => { const t = setTimeout(() => setQ(qInput), 300); return () => clearTimeout(t); }, [qInput]);

  const { data, loading, error, reload } = useFetch(
    () => materialService.list({ category: 'PURCHASED', q: q || undefined, limit: 500 }), [q]);

  const afterChange = () => { invalidate(); ensureLoaded(true); reload(); };

  const remove = async () => {
    setBusy(true);
    try {
      await materialService.remove(deleting.id);
      toast.success('Material dihapus');
      setDeleting(null); afterChange();
    } catch (e) {
      toast.error(e.status === 409 ? 'Material masih dipakai BOM/PO/jadwal — nonaktifkan lewat Edit.' : e.message);
      setDeleting(null);
    } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Material Beli" subtitle="Master Data — material yang dibeli dari supplier (purchased)"
        actions={<Button onClick={() => setForm({ open: true, material: null })}><Icon name="plus" /> Tambah Material</Button>} />
      <div className="mb-3 flex flex-wrap gap-2">
        <Input className="max-w-xs" placeholder="Cari SKU / nama…" value={qInput}
               onChange={(e) => setQInput(e.target.value)} />
      </div>
      <Card padded={false}>
        {error ? <p className="p-4 text-sm text-red-600">{error.message}</p> : (
          <MaterialTable rows={data} loading={loading}
            onSuppliers={setSupplierFor}
            onEdit={(m) => setForm({ open: true, material: m })}
            onDelete={setDeleting} />
        )}
      </Card>

      <MaterialFormModal open={form.open} material={form.material}
        onClose={() => setForm({ open: false, material: null })}
        onSaved={() => { setForm({ open: false, material: null }); afterChange(); }} />
      <MaterialSupplierModal open={!!supplierFor} material={supplierFor} onClose={() => setSupplierFor(null)} />
      <ConfirmDialog open={!!deleting} loading={busy}
        message={`Hapus material ${deleting?.sku} · ${deleting?.name}?`}
        onConfirm={remove} onCancel={() => setDeleting(null)} />
    </>
  );
}
