import { Select } from '../../components/common/Input';
import { byCategory } from '../../utils/constants';

// Item yang bisa memiliki BOM: Produk Final dan Sub-part (Made). Material beli tidak punya BOM.
export default function ProductPicker({ materials, value, onChange }) {
  const finals = byCategory(materials, 'FINISHED');
  const subs = byCategory(materials, 'SUB_PART');
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="bom-product" className="text-sm font-medium text-slate-700">Struktur untuk:</label>
      <Select id="bom-product" className="max-w-xs" value={value ?? ''}
              onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">Pilih produk / sub-part…</option>
        {finals.length > 0 && (
          <optgroup label="Produk Final">
            {finals.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.sku})</option>)}
          </optgroup>
        )}
        {subs.length > 0 && (
          <optgroup label="Sub-part (Made)">
            {subs.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.sku})</option>)}
          </optgroup>
        )}
      </Select>
    </div>
  );
}
