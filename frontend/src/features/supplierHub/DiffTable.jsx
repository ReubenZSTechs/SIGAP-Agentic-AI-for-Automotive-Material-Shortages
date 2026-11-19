import Input from '../../components/common/Input';
import { delta, fmt } from './meta';
import { t } from '../../i18n';

// Perbandingan lama dan baru. selectable: centang baris yang disetujui; baris editable: nilai baru boleh diubah.
export default function DiffTable({ rows, selectable = false, readOnly = false, selected, onToggle, edits, onEdit }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500">
            {selectable && <th className="w-10 px-3 py-2" />}
            <th className="px-3 py-2 text-left font-medium">{t('Item')}</th>
            <th className="px-3 py-2 text-right font-medium">{t('Lama')}</th>
            <th className="px-3 py-2 text-right font-medium">{t('Baru')}</th>
            <th className="px-3 py-2 text-right font-medium">{t('Selisih')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => {
            const on = !selectable || selected.has(r.key);
            const live = edits?.[r.key] !== undefined ? { ...r, after: edits[r.key] } : r;
            const d = delta(live);
            return (
              <tr key={r.key} className={on ? '' : 'text-slate-400'}>
                {selectable && (
                  <td className="px-3 py-2.5">
                    <input type="checkbox" checked={on} disabled={readOnly} onChange={() => onToggle(r.key)}
                      aria-label={t('Setujui {item}', { item: t(r.label) })} className="h-4 w-4 rounded border-slate-300 accent-primary-600" />
                  </td>
                )}
                <td className="px-3 py-2.5 font-medium text-slate-800">{t(r.label)}</td>
                <td className="px-3 py-2.5 text-right text-slate-500 line-through decoration-slate-300">{fmt(r.before, r.unit)}</td>
                <td className="px-3 py-2.5 text-right font-semibold text-slate-900">
                  {r.editable && on && !readOnly
                    ? <Input type="number" className="ml-auto h-8 w-28 text-right" value={edits?.[r.key] ?? r.after}
                        onChange={(e) => onEdit(r.key, e.target.value === '' ? '' : Number(e.target.value))} aria-label={t('Nilai baru {field}', { field: t(r.label) })} />
                    : fmt(live.after, r.unit)}
                </td>
                <td className={`px-3 py-2.5 text-right text-xs font-semibold ${d?.tone ?? ''}`}>{d?.text ?? '-'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
