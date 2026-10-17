import { create } from 'zustand';
import { materialService } from '../services/materialService';
import { supplierService } from '../services/supplierService';
import { productionLineService } from '../services/productionLineService';
import { toast } from './toastStore';

// Cache lookup untuk dropdown (material & supplier).
export const useMasterStore = create((set, get) => ({
  materials: [],
  suppliers: [],
  lines: [], // production line aktif
  loaded: false,
  async ensureLoaded(force = false) {
    if (get().loaded && !force) return;
    try {
      const [materials, suppliers, lines] = await Promise.all([
        materialService.list({ limit: 500 }),
        supplierService.list({ is_active: true }),
        productionLineService.list({ is_active: true }),
      ]);
      set({ materials, suppliers, lines, loaded: true });
    } catch (e) { toast.error(e.message); }
  },
  invalidate: () => set({ loaded: false }), // panggil setelah create/update/delete
}));
