import Icon from '../components/common/Icon';
import { useEffect, useState } from 'react';
import PageHeader from '../components/layout/PageHeader';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import ConfirmDialog from '../components/common/ConfirmDialog';
import Input from '../components/common/Input';
import ProductTable from '../features/product/ProductTable';
import ProductFormModal from '../features/product/ProductFormModal';
import useFetch from '../hooks/useFetch';
import { productService } from '../services/productService';
import { useMasterStore } from '../store/masterStore';
import { toast } from '../store/toastStore';

// Master Produk Final: barang jadi yang dijual ke customer.
export default function ProductsPage() {
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [form, setForm] = useState({ open: false, product: null });
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);
  const { ensureLoaded, invalidate } = useMasterStore();

  useEffect(() => { const t = setTimeout(() => setQ(qInput), 300); return () => clearTimeout(t); }, [qInput]);
  const { data, loading, error, reload } = useFetch(
    () => productService.list({ q: q || undefined, limit: 500 }), [q]);

  const afterChange = () => { invalidate(); ensureLoaded(true); reload(); };

  const remove = async () => {
    setBusy(true);
    try {
      await productService.remove(deleting.id);
      toast.success('Produk dihapus');
      afterChange();
    } catch (e) {
      toast.error(e.status === 409 ? 'Produk masih dipakai (BOM/jadwal/planning) — nonaktifkan lewat Edit.' : e.message);
    } finally { setBusy(false); setDeleting(null); }
  };

  return (
    <>
      <PageHeader title="Produk Final" subtitle="Master Data — barang jadi yang siap dijual ke customer"
        actions={<Button onClick={() => setForm({ open: true, product: null })}><Icon name="plus" /> Tambah Produk</Button>} />
      <p className="mb-3 text-sm text-slate-500">
        Struktur produk (sub-part dan material pendukung) disusun di menu <b>BOM</b>. Produk yang sudah
        memiliki BOM dapat dijadwalkan di <b>MPS & Planning</b>.
      </p>
      <div className="mb-3">
        <Input className="max-w-xs" placeholder="Cari SKU / nama produk…" value={qInput}
               onChange={(e) => setQInput(e.target.value)} />
      </div>
      <Card padded={false}>
        {error ? <p className="p-4 text-sm text-red-600">{error.message}</p> : (
          <ProductTable rows={data} loading={loading}
            onEdit={(p) => setForm({ open: true, product: p })} onDelete={setDeleting} />
        )}
      </Card>
      <ProductFormModal open={form.open} product={form.product}
        onClose={() => setForm({ open: false, product: null })}
        onSaved={() => { setForm({ open: false, product: null }); afterChange(); }} />
      <ConfirmDialog open={!!deleting} loading={busy}
        message={`Hapus produk ${deleting?.sku} · ${deleting?.name}?`}
        onConfirm={remove} onCancel={() => setDeleting(null)} />
    </>
  );
}
