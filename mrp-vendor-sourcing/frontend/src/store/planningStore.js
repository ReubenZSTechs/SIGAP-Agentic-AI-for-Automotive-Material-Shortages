import { create } from 'zustand';
import { planningService } from '../services/planningService';
import { toast } from './toastStore';

// Inti alur Phase 2–4: run aktif, hasil sourcing, strategi, dan PO hasil generate.
export const usePlanningStore = create((set, get) => ({
  run: null, // ringkasan run (+ n_critical/n_warning/n_safe)
  lines: [], // PlanningLineOut[]
  sourcing: [], // [{ line, deficit, no_supplier, options[] }]
  strategy: 'CHEAPEST', // CHEAPEST | FASTEST | BALANCED
  pos: [], // PO hasil generate
  busy: false,
  error: null,

  async loadRun(runId) {
    set({ busy: true, run: null, lines: [], sourcing: [], pos: [], error: null });
    try {
      const [run, lines] = await Promise.all([
        planningService.getRun(runId), planningService.getLines(runId),
      ]);
      set({ run, lines });
    } catch (e) {
      set({ error: e });
      if (e.status !== 404) toast.error(e.message);
    } finally { set({ busy: false }); }
  },

  // Muat ulang run tanpa mengosongkan layar (mis. setelah 409).
  async refreshRun() {
    const { run } = get();
    if (!run) return;
    try {
      const [fresh, lines] = await Promise.all([
        planningService.getRun(run.id), planningService.getLines(run.id),
      ]);
      set({ run: fresh, lines });
    } catch (e) { toast.error(e.message); }
  },

  async loadSourcing() {
    const { run, strategy } = get();
    if (!run) return;
    try {
      const sourcing = await planningService.getSourcing(run.id, { strategy, respect_moq: true });
      set({ sourcing });
    } catch (e) { toast.error(e.message); }
  },

  setStrategy(strategy) { set({ strategy }); return get().loadSourcing(); },

  // Mengembalikan true bila berhasil (dipakai UI untuk reset input).
  async select(lineId, supplierId, orderQty) {
    try {
      const line = await planningService.selectSupplier(lineId, {
        supplier_id: supplierId, order_qty: orderQty,
      });
      set((s) => ({ // merge hasil PUT ke state, tanpa refetch
        sourcing: s.sourcing.map((it) => (it.line.id === lineId ? { ...it, line } : it)),
      }));
      return true;
    } catch (e) {
      toast.error(e.message); // 400/409 dari backend tampil apa adanya
      if (e.status === 409) await get().refreshRun();
      return false;
    }
  },

  async clearSelection(lineId) {
    try {
      await planningService.clearSelection(lineId);
      const blank = { selected_supplier_id: null, selected_supplier_name: null, order_qty: null,
                      unit_price: null, lead_time_days: null };
      set((s) => ({
        sourcing: s.sourcing.map((it) => (it.line.id === lineId ? { ...it, line: { ...it.line, ...blank } } : it)),
      }));
    } catch (e) {
      toast.error(e.message);
      if (e.status === 409) await get().refreshRun();
    }
  },

  async autoSelect() {
    const { run, strategy } = get();
    try {
      const res = await planningService.autoSelect(run.id, strategy);
      await get().loadSourcing();
      if (res.skipped_no_supplier?.length) {
        toast.error(`Belum ada supplier untuk: ${res.skipped_no_supplier.join(', ')}`);
      } else {
        toast.success('Supplier terpilih otomatis untuk baris yang kosong');
      }
    } catch (e) {
      toast.error(e.message);
      if (e.status === 409) await get().refreshRun();
    }
  },

  async generatePOs() {
    const { run } = get();
    try {
      const pos = await planningService.generatePOs(run.id);
      set({ pos, run: { ...run, status: 'PO_GENERATED' } });
      toast.success(`${pos.length} Purchase Order dibuat`);
      return pos;
    } catch (e) {
      toast.error(e.message);
      if (e.status === 409) await get().refreshRun(); // sinkronkan status run
      return null;
    }
  },
}));
