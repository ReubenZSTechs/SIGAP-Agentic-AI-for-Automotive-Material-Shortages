import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Badge from '../../components/common/Badge';
import Button from '../../components/common/Button';
import { formatDate, formatLead, formatQty, formatRupiah } from '../../utils/formatters';
import { t } from '../../i18n';

function QtyInput({ line, minQty, locked, onCommit }) {
  const [val, setVal] = useState(String(line.order_qty ?? ''));
  const [err, setErr] = useState(null);
  useEffect(() => { setVal(String(line.order_qty ?? '')); setErr(null); },
    [line.order_qty, line.selected_supplier_id]);

  const commit = () => {
    const n = Number(val);
    if (!(n > 0) || n < minQty) { setErr(t('Minimal {n} (defisit / MOQ)', { n: formatQty(minQty) })); return; }
    setErr(null);
    if (n !== line.order_qty) onCommit(n);
  };

  return (
    <div className="flex flex-col items-end">
      <div className="flex items-center gap-2">
        <label htmlFor={`qty-${line.id}`}>{t('Qty pesan')}</label>
        <input id={`qty-${line.id}`} type="number" min={minQty} step="any" value={val} disabled={locked}
               onChange={(e) => setVal(e.target.value)} onBlur={commit}
               onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
               className={`w-24 rounded border px-2 py-1 text-right ${err ? 'border-red-400' : 'border-slate-300'}`} />
        <span>{line.uom}</span>
      </div>
      {err && <span className="mt-1 text-xs text-red-600">{err}</span>}
    </div>
  );
}

export default function SourcingCard({ item, locked, onSelect, onClear }) {
  const { line, options } = item;
  const selected = options.find((o) => o.supplier_id === line.selected_supplier_id);
  const hasSelection = line.selected_supplier_id != null;
  const minQty = Math.max(line.shortfall, selected?.moq ?? 0);

  // Ganti supplier: pertahankan qty yang sudah diatur user bila masih memenuhi defisit & MOQ opsi baru.
  const pick = (o) => {
    const keep = line.order_qty != null && line.order_qty >= Math.max(line.shortfall, o.moq);
    onSelect(line.id, o.supplier_id, keep ? line.order_qty : o.suggested_qty);
  };

  return (
    <section className={`rounded-lg border bg-white ${options.length === 0 ? 'border-red-200' : 'border-slate-200'}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <h3 className="font-medium text-slate-900">{line.sku} · {line.material_name}</h3>
        <span className="text-sm text-slate-500">
          Defisit: <b className="text-slate-800">{formatQty(line.shortfall)} {line.uom}</b>
          {line.needed_by && <> · Dibutuhkan: {formatDate(line.needed_by)}</>}
        </span>
      </header>

      {options.length === 0 ? (
        <p className="px-4 py-3 text-sm text-red-600">
          Belum ada supplier untuk material ini. Tambahkan di <Link className="underline" to="/materials">{t('Master Material')}</Link>.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-400">
              <th className="w-10 px-4 py-1" /><th className="py-1 text-left font-medium">{t('Supplier')}</th>
              <th className="py-1 text-right font-medium">{t('Harga/Unit')}</th><th className="py-1 text-right font-medium">{t('Lead')}</th>
              <th className="py-1 text-right font-medium">MOQ</th><th className="py-1 text-right font-medium">{t('Est. Total')}</th>
              <th className="py-1 pl-4 text-left font-medium">{t('Label')}</th>
            </tr>
          </thead>
          <tbody>
            {options.map((o) => {
              const isSel = o.supplier_id === line.selected_supplier_id;
              return (
                <tr key={o.supplier_id}
                    className={`border-b border-slate-50 last:border-0 ${isSel ? 'bg-indigo-50' : ''}`}>
                  <td className="px-4 py-2">
                    <input type="radio" name={`sel-${line.id}`} checked={isSel} disabled={locked}
                           aria-label={t('Pilih {name}', { name: o.supplier_name })} onChange={() => pick(o)} />
                  </td>
                  <td className="py-2 font-medium">{o.supplier_name}</td>
                  <td className="py-2 text-right">{formatRupiah(o.unit_price)}</td>
                  <td className="py-2 text-right">{formatLead(o.lead_time_days)}</td>
                  <td className="py-2 text-right">{formatQty(o.moq)}</td>
                  <td className="py-2 text-right">{formatRupiah(o.est_total)}</td>
                  <td className="py-2 pl-4 pr-4">
                    <div className="flex flex-wrap gap-1">
                      {o.rank === 1 && <Badge tone="slate">{t('Pilihan utama')}</Badge>}
                      {o.is_cheapest && <Badge tone="green">{t('Termurah')}</Badge>}
                      {o.is_fastest && <Badge tone="indigo">{t('Tercepat')}</Badge>}
                      {!o.meets_moq && <Badge tone="amber">MOQ {formatQty(o.moq)}</Badge>}
                      {o.will_be_late && <Badge tone="amber">{t('Telat dari jadwal')}</Badge>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {hasSelection && (
        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-4 py-2 text-sm">
          <span className="text-slate-500">
            Terpilih: <b className="text-slate-800">{line.selected_supplier_name}</b>
            {!selected && <span className="ml-1 text-amber-700">{t('(di luar filter strategi saat ini)')}</span>}
          </span>
          <div className="flex items-center gap-3">
            <QtyInput line={line} minQty={minQty} locked={locked}
                      onCommit={(n) => onSelect(line.id, line.selected_supplier_id, n)} />
            {!locked && <Button size="sm" variant="ghost" onClick={() => onClear(line.id)}>{t('Batal pilih')}</Button>}
          </div>
        </footer>
      )}
    </section>
  );
}
