import Icon from '../../components/common/Icon';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Button from '../../components/common/Button';
import Card from '../../components/common/Card';
import EmptyState, { Spinner } from '../../components/common/EmptyState';
import PoTable from './PoTable';
import useFetch from '../../hooks/useFetch';
import { purchaseOrderService } from '../../services/purchaseOrderService';
import { usePlanningStore } from '../../store/planningStore';
import { formatQty, formatRupiah } from '../../utils/formatters';

export default function PoGeneratePanel() {
  const { run, sourcing, loadSourcing, generatePOs } = usePlanningStore();
  const generated = run.status === 'PO_GENERATED';
  const [generating, setGenerating] = useState(false);

  // Run yang sudah menghasilkan PO: ambil daftar PO milik run ini dari server.
  const pos = useFetch(
    () => (generated ? purchaseOrderService.list({ planning_run_id: run.id }) : Promise.resolve([])),
    [run.id, generated],
  );

  // Pratinjau dikelompokkan di klien dari state sourcing (dokumen PO resmi tetap dibuat server).
  useEffect(() => { if (!generated && sourcing.length === 0) loadSourcing(); }, [generated, sourcing.length, loadSourcing]);

  const groups = useMemo(() => {
    const map = new Map();
    sourcing.forEach(({ line }) => {
      if (line.selected_supplier_id == null) return;
      if (!map.has(line.selected_supplier_id)) {
        map.set(line.selected_supplier_id, { name: line.selected_supplier_name, items: [], total: 0 });
      }
      const g = map.get(line.selected_supplier_id);
      const amount = Math.round(line.order_qty * line.unit_price);
      g.items.push({ ...line, amount });
      g.total += amount;
    });
    return [...map.values()];
  }, [sourcing]);

  const missing = sourcing.filter((it) => it.line.selected_supplier_id == null).length;
  const grandTotal = groups.reduce((a, g) => a + g.total, 0);

  const confirm = async () => {
    setGenerating(true);
    await generatePOs();
    setGenerating(false);
  };

  if (generated) {
    return (
      <div className="space-y-3">
        <p className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          Purchase Order untuk run ini sudah dibuat. Terbitkan dan terima barang dari halaman detail PO.
        </p>
        <Card padded={false}>
          <PoTable rows={pos.data} loading={pos.loading} />
        </Card>
        <div className="text-right"><Link className="text-sm font-semibold text-primary-700 hover:underline" to="/purchase-orders">Semua Purchase Order</Link></div>
      </div>
    );
  }

  if (sourcing.length === 0) return <Spinner />;
  if (groups.length === 0) {
    return <EmptyState title="Belum ada supplier terpilih" description="Pilih supplier di tab Sourcing terlebih dahulu." />;
  }

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-slate-800">
        Konfirmasi Pesanan — {groups.length} PO akan dibuat (dikelompokkan per supplier)
      </h2>
      {groups.map((g) => (
        <Card key={g.name} padded={false}
              title={g.name} actions={<span className="text-sm font-semibold">{formatRupiah(g.total)}</span>}>
          <table className="w-full text-sm">
            <tbody>
              {g.items.map((it) => (
                <tr key={it.id} className="border-b border-slate-50 last:border-0">
                  <td className="px-4 py-2">{it.material_name}</td>
                  <td className="py-2 text-right">{formatQty(it.order_qty)} {it.uom}</td>
                  <td className="py-2 text-right text-slate-500">× {formatRupiah(it.unit_price)}</td>
                  <td className="px-4 py-2 text-right font-medium">{formatRupiah(it.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ))}
      <div className="flex flex-wrap items-center justify-end gap-4">
        {missing > 0 && <span className="text-sm text-amber-700">{missing} material belum dipilih supplier</span>}
        <span className="text-sm">Total <b>{formatRupiah(grandTotal)}</b></span>
        {run.is_stale && <span className="text-sm text-amber-700">Run basi — jalankan ulang planning di halaman MPS</span>}
        <Button loading={generating} disabled={missing > 0 || run.is_stale} onClick={confirm}><Icon name="check" /> Konfirmasi & Buat PO</Button>
      </div>
    </div>
  );
}
