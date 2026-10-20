import { create } from 'zustand';
import { hubService } from '../services/hubService';

const applyStatus = (st) => ({
  paused: st.paused, pending: st.pending, telegram: st.telegram ?? null, counts: st.counts ?? {}, aiConfigured: !!st.ai_configured,
});

export const useHubStore = create((set, get) => ({
  items: [], loading: false, error: null, pending: 0, paused: false, telegram: null, counts: {}, aiConfigured: false,
  // silent = polling latar belakang: tidak menampilkan spinner dan tidak menimpa galat
  async load(silent = false) {
    if (!silent) set({ loading: true, error: null });
    try {
      const [items, st] = await Promise.all([hubService.listApprovals(), hubService.status()]);
      set({ items, ...applyStatus(st), loading: false, error: null });
    } catch (e) { set({ loading: false, error: silent ? get().error : e }); }
  },
  async refreshStatus() {
    try { set(applyStatus(await hubService.status())); } catch { /* abaikan */ }
  },
  async decide(id, mode, body) {
    try { await hubService.decide(id, mode, body); } finally { await get().load(true); } // 409: muat ulang agar tampil basi
  },
  async setPaused(p, approver) { await hubService.setPaused(p, approver); set({ paused: p }); },
}));
