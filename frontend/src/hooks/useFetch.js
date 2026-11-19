import { useCallback, useEffect, useRef, useState } from 'react';

// Pengganti React Query yang cukup untuk MVP. `reload()` mengambil ulang data.
export default function useFetch(fetcher, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const seq = useRef(0); // abaikan respons usang bila deps berubah cepat

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fetcher();
      if (mine === seq.current) setState({ data, loading: false, error: null });
    } catch (e) {
      if (mine === seq.current) setState({ data: null, loading: false, error: e });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => { load(); }, [load]);
  return { ...state, reload: load };
}
