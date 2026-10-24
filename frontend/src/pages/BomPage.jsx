import { useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import PageHeader from '../components/layout/PageHeader';
import Tabs from '../components/common/Tabs';
import EmptyState from '../components/common/EmptyState';
import ProductPicker from '../features/bom/ProductPicker';
import BomTree from '../features/bom/BomTree';
import ExplosionTable from '../features/bom/ExplosionTable';
import { useMasterStore } from '../store/masterStore';
import { byCategory } from '../utils/constants';
import { t } from '../i18n';

// Struktur produk: Produk Final / Sub-part → komponen (sub-part "Made" + material beli).
// Produk dipilih lewat query ?product=ID (dipakai tombol "BOM →" di halaman Produk Final).
export default function BomPage() {
  const { materials, ensureLoaded, loaded } = useMasterStore();
  const [params, setParams] = useSearchParams();
  const productId = Number(params.get('product')) || null;
  const tab = params.get('tab') === 'explosion' ? 'explosion' : 'tree';

  useEffect(() => { ensureLoaded(true); }, [ensureLoaded]); // selalu segar

  const update = (patch) => setParams((p) => {
    const next = new URLSearchParams(p);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    return next;
  }, { replace: true });

  // Tanpa pilihan: otomatis pilih produk final pertama
  useEffect(() => {
    if (productId == null && loaded) {
      const first = byCategory(materials, 'FINISHED')[0] ?? byCategory(materials, 'SUB_PART')[0];
      if (first) update({ product: String(first.id) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, materials, productId]);

  const hasProducts = byCategory(materials, 'FINISHED').length > 0;

  return (
    <>
      <PageHeader title={t('BOM')} subtitle={t('Susun struktur produk: sub-part (Made) dan material beli pendukungnya')} />
      {loaded && !hasProducts && (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {t('Belum ada Produk Final.')} <Link className="font-medium underline" to="/products">{t('Buat produk final')}</Link>{' '}
          {t('terlebih dahulu, lalu susun BOM-nya di sini.')}
        </p>
      )}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <ProductPicker materials={materials} value={productId}
                       onChange={(id) => update({ product: id ? String(id) : null })} />
        <Tabs variant="segmented" value={tab} onChange={(item) => update({ tab: item === 'explosion' ? 'explosion' : null })}
              tabs={[{ id: 'tree', label: 'Struktur' }, { id: 'explosion', label: 'Eksplosi' }]} />
      </div>
      {productId == null
        ? <EmptyState title={t('Pilih produk')} description={t('Pilih Produk Final atau Sub-part untuk melihat strukturnya.')} />
        : tab === 'tree'
          ? <BomTree key={productId} productId={productId} />
          : <ExplosionTable key={productId} productId={productId} />}
    </>
  );
}
