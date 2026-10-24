import { Spinner } from './EmptyState';
import { tx } from '../../i18n';

// columns: [{ key, header, render?(row), align? ('left'|'right'|'center'), className? }]
export default function DataTable({
  columns, rows, loading = false, emptyText = 'Belum ada data', onRowClick, rowKey = 'id', rowClassName,
}) {
  const align = (a) => (a === 'right' ? 'text-right' : a === 'center' ? 'text-center' : 'text-left');
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
            {columns.map((c) => (
              <th key={c.key} className={`whitespace-nowrap px-4 py-2.5 font-medium ${align(c.align)}`}>{tx(c.header)}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {loading && <tr><td colSpan={columns.length}><Spinner /></td></tr>}
          {!loading && (rows ?? []).length === 0 && (
            <tr><td colSpan={columns.length} className="px-4 py-10 text-center text-slate-500">{tx(emptyText)}</td></tr>
          )}
          {!loading && (rows ?? []).map((row, i) => (
            <tr key={row[rowKey] ?? i}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={`transition-colors ${onRowClick ? 'cursor-pointer hover:bg-primary-50/60' : 'hover:bg-slate-50/70'} ${rowClassName?.(row) ?? ''}`}>
              {columns.map((c) => (
                <td key={c.key} className={`px-4 py-3 ${align(c.align)} ${c.className ?? ''}`}>
                  {c.render ? c.render(row) : row[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
