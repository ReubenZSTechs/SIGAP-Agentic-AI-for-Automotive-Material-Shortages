export const COMPANY = 'SIGAP'; // sama dengan backend (app/hub/common.py)

// Variabel template pesan supplier: {nama} diganti nilai; yang tidak dikenal dibiarkan apa adanya.
export const TEMPLATE_VARS = [
  { key: 'waktu', label: 'Sapaan waktu', sample: 'pagi' },
  { key: 'kontak', label: 'Nama kontak', sample: 'Pak Hendra' },
  { key: 'supplier', label: 'Nama supplier', sample: 'PT Mitra Komponen' },
  { key: 'perusahaan', label: 'Perusahaan kita', sample: COMPANY },
  { key: 'item', label: 'Item / topik', sample: 'Pedal Sepeda sebanyak 50 Buah' },
  { key: 'qty', label: 'Jumlah', sample: '50' },
  { key: 'satuan', label: 'Satuan', sample: 'Buah' },
  { key: 'po', label: 'Nomor PO', sample: 'PO-202610-0012' },
  { key: 'tenggat', label: 'Tenggat', sample: 'Kamis, 22 Okt pukul 17.00' },
];
export const SAMPLE_VARS = Object.fromEntries(TEMPLATE_VARS.map((v) => [v.key, v.sample]));

export const greeting = (d = new Date()) => {
  const h = d.getHours();
  return h < 11 ? 'pagi' : h < 15 ? 'siang' : h < 18 ? 'sore' : 'malam';
};

// [{ text, key? }] agar UI bisa menyorot bagian yang berasal dari variabel.
export function templateParts(body, vars) {
  return body.split(/(\{\w+\})/g).filter(Boolean).map((p) => {
    const k = /^\{(\w+)\}$/.exec(p)?.[1];
    return k && vars[k] != null && vars[k] !== '' ? { text: String(vars[k]), key: k } : { text: p, key: k ? `!${k}` : undefined };
  });
}

export const fillTemplate = (body, vars) => templateParts(body, vars).map((p) => p.text).join('');

export const formatDeadline = (iso) => new Date(iso).toLocaleString('id-ID', {
  weekday: 'long', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
}).replace(/,?\s(\d{2})\.(\d{2})$/, ' pukul $1.$2');
