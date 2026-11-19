import { useEffect, useRef } from 'react';

// Memanggil fn tiap `ms` milidetik; dilewati saat tab tersembunyi atau saat panggilan sebelumnya belum selesai
// (koneksi lambat ke database tidak boleh menumpuk permintaan). Jalur upgrade: ganti dengan SSE.
export default function usePolling(fn, ms, enabled = true) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (!enabled) return undefined;
    let busy = false;
    const id = setInterval(async () => {
      if (document.hidden || busy) return;
      busy = true;
      try { await ref.current(); } catch { /* the page shows its own errors */ } finally { busy = false; }
    }, ms);
    return () => clearInterval(id);
  }, [ms, enabled]);
}
