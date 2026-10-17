import Icon from '../components/common/Icon';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import PageHeader from '../components/layout/PageHeader';
import Card from '../components/common/Card';
import EmptyState, { Spinner } from '../components/common/EmptyState';
import PoHeader from '../features/procurement/PoHeader';
import PoItemsTable from '../features/procurement/PoItemsTable';
import GoodsReceiptForm from '../features/procurement/GoodsReceiptForm';
import ReceiptResultTable from '../features/procurement/ReceiptResultTable';
import PoMovementHistory from '../features/procurement/PoMovementHistory';
import useFetch from '../hooks/useFetch';
import { purchaseOrderService } from '../services/purchaseOrderService';

export default function PurchaseOrderDetailPage() {
  const { id } = useParams();
  const { data: po, loading, error, reload } = useFetch(() => purchaseOrderService.get(id), [id]);
  const [result, setResult] = useState(null); // respons POST …/receipts

  if (loading && !po) return <Spinner />;
  if (error) {
    return <EmptyState title={error.status === 404 ? 'Data tidak ditemukan' : 'Gagal memuat PO'}
      description={error.message} action={<Link className="text-indigo-700 underline" to="/purchase-orders">Kembali ke daftar PO</Link>} />;
  }

  const canReceive = po.status === 'ISSUED' || po.status === 'PARTIALLY_RECEIVED';
  const hasReceipts = po.items.some((i) => i.qty_received > 0);

  return (
    <>
      <PageHeader title="Detail Purchase Order"
        subtitle={<Link className="inline-flex items-center gap-1 font-medium text-primary-700 hover:underline" to="/purchase-orders"><Icon name="arrowLeft" className="h-3.5 w-3.5" /> Semua PO</Link>} />
      <PoHeader po={po} onChanged={() => { setResult(null); reload(); }} />
      <div className="space-y-5">
        {canReceive ? (
          <Card title="Penerimaan Barang">
            <GoodsReceiptForm key={`${po.status}-${po.items.map((i) => i.qty_received).join(',')}`} po={po}
              onDone={(res) => { setResult(res); reload(); }} />
          </Card>
        ) : (
          <PoItemsTable items={po.items} />
        )}
        {result && <ReceiptResultTable changes={result.changes} items={po.items} />}
        {canReceive && hasReceipts && <PoItemsTable items={po.items} />}
        {hasReceipts && <PoMovementHistory po={po} />}
        {['DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED'].includes(po.status) && (
          <p className="text-sm text-slate-500">Penerimaan barang tersedia setelah PO diterbitkan.</p>
        )}
      </div>
    </>
  );
}
