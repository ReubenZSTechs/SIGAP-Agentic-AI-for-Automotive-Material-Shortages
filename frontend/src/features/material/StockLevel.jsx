// Penanda tingkat stok: bar abu = stok fisik, bar berwarna = stok tersedia, garis tegak = safety stock.
const FILL = { CRITICAL: 'bg-red-500', WARNING: 'bg-amber-500', SAFE: 'bg-green-600' };

export default function StockLevel({ row }) {
  const { on_hand = 0, available = 0, safety_stock = 0, status } = row;
  const max = Math.max(on_hand, safety_stock * 1.5, 1);
  const pct = (n) => `${Math.min(100, Math.max(0, (n / max) * 100))}%`;
  return (
    <div className="relative h-2 w-32 rounded-full bg-slate-100" role="img"
         aria-label={`Fisik ${on_hand}, tersedia ${available}, safety stock ${safety_stock}`}
         title={`Fisik ${on_hand} · Tersedia ${available} · Safety ${safety_stock}`}>
      <div className="absolute inset-y-0 left-0 rounded-full bg-slate-300" style={{ width: pct(on_hand) }} />
      <div className={`absolute inset-y-0 left-0 rounded-full ${FILL[status] ?? 'bg-slate-500'}`} style={{ width: pct(available) }} />
      {safety_stock > 0 && (
        <div className="absolute -top-[3px] h-[14px] w-0.5 rounded bg-slate-800" style={{ left: pct(safety_stock) }} />
      )}
    </div>
  );
}
