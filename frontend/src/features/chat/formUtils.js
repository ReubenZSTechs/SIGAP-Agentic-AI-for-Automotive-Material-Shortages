// Helper kecil untuk formulir chat (produk / material / supplier baru).
// Nilai form adalah objek bersarang; kolom dirujuk dengan path bertitik, mis. "components.0.qty".

/** Ambil nilai pada path bertitik. */
export function getIn(obj, path) {
  return path.split('.').reduce((cur, key) => (cur == null ? undefined : cur[key]), obj);
}

/** Salinan `obj` dengan nilai baru pada path bertitik (tidak mengubah objek asli). */
export function setIn(obj, path, value) {
  const [key, ...rest] = path.split('.');
  const copy = Array.isArray(obj) ? [...obj] : { ...obj };
  copy[key] = rest.length ? setIn(obj?.[key] ?? {}, rest.join('.'), value) : value;
  return copy;
}

const blank = (v) => v === null || v === undefined || String(v).trim() === '';

export const EMPTY_NEW_MATERIAL = {
  sku: '', name: '', uom: 'Buah', initial_stock: 0, safety_stock: 0,
  supplier_id: null, new_supplier: null, unit_price: null, lead_time_days: null,
};
export const EMPTY_NEW_SUPPLIER = { code: '', name: '', contact: '', payment_term_days: 0 };

/** Baris kosong baru untuk tiap jenis formulir. */
export function emptyRow(entity) {
  if (entity === 'product') return { material_id: null, new_material: null, qty: 1 };
  const terms = { unit_price: null, lead_time_days: null, moq: 1, is_preferred: false };
  if (entity === 'material') return { supplier_id: null, new_supplier: null, ...terms };
  return { material_id: null, new_material: null, ...terms };
}

export const ROWS_KEY = { product: 'components', material: 'suppliers', supplier: 'materials' };

/**
 * Cek kolom wajib di browser sebelum dikirim (server tetap memeriksa ulang semua aturan).
 * Mengembalikan { path: pesan }.
 */
export function checkRequired(entity, values) {
  const errors = {};
  const need = (path) => {
    if (blank(getIn(values, path))) errors[path] = 'Wajib diisi';
  };
  const needNumber = (path, { positive = false } = {}) => {
    need(path);
    const v = getIn(values, path);
    if (!blank(v) && (Number.isNaN(Number(v)) || Number(v) < 0 || (positive && Number(v) <= 0))) {
      errors[path] = positive ? 'Harus lebih dari 0' : 'Harus angka ≥ 0';
    }
  };
  const needNewMaterial = (base) => ['sku', 'name', 'uom'].forEach((k) => need(`${base}.${k}`));

  if (entity === 'product') {
    ['sku', 'name', 'uom'].forEach(need);
    needNumber('selling_price');
  } else if (entity === 'material') {
    ['sku', 'name', 'uom'].forEach(need);
  } else {
    ['code', 'name'].forEach(need);
  }

  const rowsKey = ROWS_KEY[entity];
  (values[rowsKey] ?? []).forEach((row, i) => {
    const base = `${rowsKey}.${i}`;
    if (entity === 'material') {
      if (row.new_supplier) ['code', 'name'].forEach((k) => need(`${base}.new_supplier.${k}`));
      else if (blank(row.supplier_id)) errors[`${base}.supplier_id`] = 'Pilih supplier';
    } else if (row.new_material) {
      needNewMaterial(`${base}.new_material`);
    } else if (blank(row.material_id)) {
      errors[`${base}.material_id`] = 'Pilih material';
    }
    if (entity === 'product') {
      needNumber(`${base}.qty`, { positive: true });
      if (row.new_material?.new_supplier) {
        ['code', 'name'].forEach((k) => need(`${base}.new_material.new_supplier.${k}`));
      }
      if (row.new_material && (row.new_material.new_supplier || !blank(row.new_material.supplier_id))) {
        needNumber(`${base}.new_material.unit_price`);
        needNumber(`${base}.new_material.lead_time_days`);
      }
    } else {
      needNumber(`${base}.unit_price`);
      needNumber(`${base}.lead_time_days`);
    }
  });
  return errors;
}
