import Icon from '../components/common/Icon';
import { useEffect, useMemo, useState } from 'react';
import PageHeader from '../components/layout/PageHeader';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import { Select } from '../components/common/Input';
import InventoryTable from '../features/material/InventoryTable';
import InventoryEditModal from '../features/material/InventoryEditModal';
import MovementHistoryModal from '../features/material/MovementHistoryModal';
import useFetch from '../hooks/useFetch';
import { inventoryService } from '../services/inventoryService';
import { useMasterStore } from '../store/masterStore';
import { t } from '../i18n';

export default function InventoryPage() {
  const [status, setStatus] = useState('');
  const [modal, setModal] = useState({ open: false, row: null });
  const [history, setHistory] = useState(null);
  const { materials, ensureLoaded } = useMasterStore();
  useEffect(() => { ensureLoaded(); }, [ensureLoaded]);

  // Satu fetch tanpa filter; filter status dilakukan di klien (status dihitung di server dari
  // available vs safety_stock, jadi hasilnya sama) sehingga ganti filter tidak memanggil API lagi.
  const { data: all, loading, error, reload } = useFetch(() => inventoryService.list(), []);

  const data = useMemo(
    () => (status ? (all ?? []).filter((r) => r.status === status) : all), [all, status]);

  // Material BUY aktif yang belum punya baris inventory
  const candidates = useMemo(() => {
    const have = new Set((all ?? []).map((r) => r.material_id));
    return materials.filter((m) => m.category === 'PURCHASED' && m.is_active && !have.has(m.id));
  }, [all, materials]);

  const refresh = reload;

  return (
    <>
      <PageHeader title={t('Inventory Material Beli')} subtitle={t('Stok fisik, stok terkunci, dan stok tersedia per material beli')}
        actions={<Button variant="secondary" onClick={() => setModal({ open: true, row: null })}><Icon name="plus" /> {t('Atur Stok Material')}</Button>} />
      <div className="mb-3">
        <Select className="w-48" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t('Status: Semua')}</option>
          <option value="CRITICAL">{t('Critical')}</option>
          <option value="WARNING">{t('Warning')}</option>
          <option value="SAFE">{t('Aman')}</option>
        </Select>
      </div>
      <p className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1.5"><i className="h-2 w-5 rounded-full bg-slate-300" />{t('Stok fisik')}</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-2 w-5 rounded-full bg-green-600" />{t('Stok tersedia (warna mengikuti status)')}</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-3.5 w-0.5 rounded bg-slate-800" />{t('Safety stock')}</span>
      </p>
      <Card padded={false}>
        {error ? <p className="p-4 text-sm text-red-600">{error.message}</p> : (
          <InventoryTable rows={data} loading={loading} onEdit={(row) => setModal({ open: true, row })} onHistory={setHistory} />
        )}
      </Card>
      <MovementHistoryModal open={!!history} row={history} onClose={() => setHistory(null)} />
      <InventoryEditModal open={modal.open} row={modal.row} candidates={candidates}
        onClose={() => setModal({ open: false, row: null })}
        onSaved={() => { setModal({ open: false, row: null }); refresh(); }} />
    </>
  );
}