import Icon from '../../../components/common/Icon';
import Input from '../../../components/common/Input';
import Tabs from '../../../components/common/Tabs';
import { t } from '../../../i18n';

// Matriks per skenario: pesan keluar boleh otomatis atau draf dulu; perubahan data bisnis selalu perlu persetujuan.
export default function AutonomyMatrix({ rows, onChange }) {
  const set = (key, patch) => onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500">
            <th className="px-4 py-2.5 text-left font-medium">{t('Skenario')}</th>
            <th className="px-4 py-2.5 text-left font-medium">{t('Pesan keluar ke supplier')}</th>
            <th className="px-4 py-2.5 text-left font-medium">{t('Perubahan data')}</th>
            <th className="px-4 py-2.5 text-left font-medium">{t('Batas keputusan')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="px-4 py-3 font-medium text-slate-800">{t(r.label)}{r.note && <span className="block text-xs font-normal text-slate-500">{t(r.note)}</span>}</td>
              <td className="px-4 py-3">
                {r.locked ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-slate-600" title={r.note ?? undefined}>
                    <Icon name="shield" className="h-4 w-4 text-primary-600" /> {r.outbound === 'REVIEW' ? t('Selalu draf dulu') : t('Otomatis (tetap)')}
                  </span>
                ) : (
                  <Tabs variant="segmented" value={r.outbound} onChange={(v) => set(r.key, { outbound: v })}
                    tabs={[{ id: 'AUTO', label: 'Otomatis' }, { id: 'REVIEW', label: 'Draf dulu' }]} />
                )}
              </td>
              <td className="px-4 py-3">
                {r.data ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-slate-700"><Icon name="shield" className="h-4 w-4 text-primary-600" /> {t('{data}: selalu persetujuan', { data: t(r.data) })}</span>
                ) : <span className="text-xs text-slate-400">{t('Tidak mengubah data')}</span>}
              </td>
              <td className="px-4 py-3">
                {r.expiry_hours != null ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Input type="number" min="1" max="168" className="h-8 w-20 text-right" value={r.expiry_hours} aria-label={t('Batas keputusan {field} (jam)', { field: t(r.label) })}
                      onChange={(e) => set(r.key, { expiry_hours: e.target.value === '' ? '' : Number(e.target.value) })} />
                    <span className="text-xs text-slate-500">{t('jam')}</span>
                  </span>
                ) : <span className="text-xs text-slate-400">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
