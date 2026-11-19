import Card from '../../components/common/Card';
import DataTable from '../../components/common/DataTable';
import useFetch from '../../hooks/useFetch';
import { inventoryService } from '../../services/inventoryService';
import { formatDateTime, formatQty } from '../../utils/formatters';
import { t } from '../../i18n';

// Riwayat penerimaan stok milik PO ini (dari GET /stock-movements).
export default function PoMovementHistory({ po }) {
  const { data, loading } = useFetch(async () => {
    const ids = [...new Set(po.items.map((i) => i.material_id))];
    const all = await Promise.all(ids.map((id) => inventoryService.movements({ material_id: id, type: 'GOODS_RECEIPT' })));
    return all.flat().filter((m) => m.ref_type === 'PO' && m.ref_id === po.id)
      .sort((a, b) => b.id - a.id);
  }, [po.id, po.status]);

  const columns = [
    { key: 'created_at', header: 'Waktu', render: (m) => formatDateTime(m.created_at) },
    { key: 'sku', header: 'SKU', className: 'font-mono text-xs' },
    { key: 'qty', header: 'Qty Masuk', align: 'right', render: (m) => `+${formatQty(m.qty)}` },
  ];
  return (
    <Card title={t('Riwayat Penerimaan')} padded={false}>
      <DataTable columns={columns} rows={data} loading={loading} emptyText={t('Belum ada penerimaan')} />
    </Card>
  );
}
