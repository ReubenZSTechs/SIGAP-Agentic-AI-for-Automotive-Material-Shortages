import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageHeader from '../components/layout/PageHeader';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Icon from '../components/common/Icon';
import PoTable from '../features/procurement/PoTable';
import useFetch from '../hooks/useFetch';
import { purchaseOrderService } from '../services/purchaseOrderService';
import { PO_SOURCE, PO_STATUS } from '../utils/constants';

// Chip filter: satu pilihan aktif; klik chip aktif tidak mengubah apa pun, gunakan "Semua" / Reset.
function Chip({ active, onClick, children }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick}
      className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
        active ? 'bg-primary-600 text-white shadow-sm' : 'bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900'}`}>
      {children}
    </button>
  );
}

function FilterRow({ label, value, onChange, options }) {
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-slate-700">{label}</div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={`Filter ${label.toLowerCase()}`}>
        <Chip active={value === ''} onClick={() => onChange('')}>Semua</Chip>
        {options.map(([k, v]) => <Chip key={k} active={value === k} onClick={() => onChange(k)}>{v}</Chip>)}
      </div>
    </div>
  );
}

// Chip ringkas filter aktif di luar popover; klik untuk menghapus filter tersebut.
function ActiveTag({ children, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-lg bg-primary-50 py-1 pl-2.5 pr-1 text-sm font-medium text-primary-700 ring-1 ring-inset ring-primary-200">
      {children}
      <button type="button" onClick={onRemove} aria-label={`Hapus filter ${children}`}
        className="rounded-md p-0.5 text-primary-500 hover:bg-primary-100 hover:text-primary-800"><Icon name="x" className="h-3.5 w-3.5" /></button>
    </span>
  );
}

export default function PurchaseOrdersPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState('');
  const [source, setSource] = useState('');
  const { data, loading, error } = useFetch(
    () => purchaseOrderService.list({ status: status || undefined, source: source || undefined }), [status, source]);
  const activeCount = (status ? 1 : 0) + (source ? 1 : 0);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (!wrapRef.current?.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open]);

  return (
    <>
      <PageHeader title="Purchase Order" subtitle="PO hasil planning & Manual PO (dengan approval) · penerimaan barang"
        actions={<Button onClick={() => navigate('/purchase-orders/new')}><Icon name="plus" /> Buat PO Manual</Button>} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div ref={wrapRef} className="relative">
          <Button variant="secondary" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <Icon name="filter" /> Filter
            {activeCount > 0 && (
              <span className="ml-0.5 flex h-5 min-w-5 items-center justify-center rounded-md bg-primary-600 px-1 text-xs font-semibold text-white">{activeCount}</span>
            )}
            <Icon name="chevronDown" className={`h-4 w-4 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
          </Button>
          {open && (
            <div role="dialog" aria-label="Filter Purchase Order"
              className="anim-pop absolute left-0 top-full z-20 mt-2 w-[min(26rem,calc(100vw-2rem))] rounded-xl border border-slate-200 bg-white shadow-xl">
              <div className="space-y-5 p-4">
                <FilterRow label="Status" value={status} onChange={setStatus}
                  options={Object.entries(PO_STATUS).map(([k, v]) => [k, v.label])} />
                <FilterRow label="Sumber" value={source} onChange={setSource}
                  options={Object.entries(PO_SOURCE).map(([k, v]) => [k, v.label])} />
              </div>
              <div className="flex items-center justify-between rounded-b-xl border-t border-slate-200 bg-slate-50 px-4 py-2.5">
                <Button size="sm" variant="ghost" disabled={activeCount === 0} onClick={() => { setStatus(''); setSource(''); }}>Reset</Button>
                <Button size="sm" onClick={() => setOpen(false)}>Selesai</Button>
              </div>
            </div>
          )}
        </div>
        {status && <ActiveTag onRemove={() => setStatus('')}>{PO_STATUS[status]?.label ?? status}</ActiveTag>}
        {source && <ActiveTag onRemove={() => setSource('')}>{PO_SOURCE[source]?.label ?? source}</ActiveTag>}
        {!loading && !error && <span className="ml-auto text-sm text-slate-500" role="status">{(data ?? []).length} PO</span>}
      </div>

      <Card padded={false}>
        {error ? <p className="p-4 text-sm text-red-600">{error.message}</p>
          : <PoTable rows={data} loading={loading}
              emptyText={activeCount > 0 ? 'Tidak ada PO yang cocok dengan filter ini' : undefined} />}
      </Card>
    </>
  );
}
