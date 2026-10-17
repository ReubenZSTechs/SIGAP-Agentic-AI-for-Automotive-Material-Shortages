import { useState } from 'react';
import Button from '../../components/common/Button';
import Card from '../../components/common/Card';
import DataTable from '../../components/common/DataTable';
import Input from '../../components/common/Input';
import { bomService } from '../../services/bomService';
import { formatQty } from '../../utils/formatters';

export default function ExplosionTable({ productId }) {
  const [qty, setQty] = useState('50');
  const [rows, setRows] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const compute = async () => {
    if (!(Number(qty) > 0)) { setError('Jumlah produk harus > 0'); return; }
    setLoading(true); setError(null);
    try { setRows(await bomService.explosion(productId, Number(qty))); }
    catch (e) { setRows(null); setError(e.message); } // 422: sub-assembly MAKE tanpa BOM
    finally { setLoading(false); }
  };

  const columns = [
    { key: 'sku', header: 'SKU', className: 'font-mono text-xs' },
    { key: 'name', header: 'Nama' },
    { key: 'uom', header: 'Satuan' },
    { key: 'gross_qty', header: 'Kebutuhan Kotor', align: 'right', render: (r) => formatQty(r.gross_qty) },
  ];

  return (
    <Card title="Eksplosi BOM (kebutuhan kotor material BUY)">
      <div className="mb-3 flex items-end gap-2">
        <label className="text-sm font-medium text-slate-700">Jumlah produk
          <Input type="number" min="1" className="mt-1 w-32" value={qty} onChange={(e) => setQty(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && compute()} />
        </label>
        <Button loading={loading} onClick={compute}>Hitung</Button>
      </div>
      {error && (
        <p className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{error}</p>
      )}
      {rows && <DataTable columns={columns} rows={rows} rowKey="material_id" />}
    </Card>
  );
}
