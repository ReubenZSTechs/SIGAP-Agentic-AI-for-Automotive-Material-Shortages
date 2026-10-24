import Button from '../../components/common/Button';
import DataTable from '../../components/common/DataTable';
import Modal from '../../components/common/Modal';
import useFetch from '../../hooks/useFetch';
import { inventoryService } from '../../services/inventoryService';
import { MOVEMENT_TYPE } from '../../utils/constants';
import { formatDateTime, formatQty } from '../../utils/formatters';
import { t } from '../../i18n';

// Riwayat pergerakan stok satu material (GET /stock-movements?material_id=).
export default function MovementHistoryModal({ open, row, onClose }) {
  const { data, loading, error } = useFetch(
    () => (open && row ? inventoryService.movements({ material_id: row.material_id, limit: 200 }) : Promise.resolve([])),
    [open, row?.material_id]);

  const columns = [
    { key: 'created_at', header: 'Waktu', render: (m) => formatDateTime(m.created_at) },
    { key: 'type', header: 'Jenis', render: (m) => MOVEMENT_TYPE[m.type] ?? m.type },
    { key: 'qty', header: 'Qty', align: 'right', render: (m) => (
      <span className={m.qty < 0 ? 'text-red-600' : 'text-green-700'}>{m.qty > 0 ? '+' : ''}{formatQty(m.qty)}</span>
    ) },
    { key: 'note', header: 'Referensi', render: (m) => m.note ?? '—' },
  ];
  return (
    <Modal open={open} onClose={onClose} size="lg" title={row ? t('Riwayat Stok · {name}', { name: row.name }) : t('Riwayat Stok')}
      footer={<Button variant="secondary" onClick={onClose}>{t('Tutup')}</Button>}>
      {error ? <p className="text-sm text-red-600">{error.message}</p>
        : <DataTable columns={columns} rows={data} loading={loading} emptyText={t('Belum ada pergerakan stok')} />}
    </Modal>
  );
}
