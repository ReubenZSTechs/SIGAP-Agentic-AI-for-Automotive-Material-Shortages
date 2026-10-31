import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { Spinner } from '../components/common/EmptyState';
import CommonIcon from '../components/common/Icon';
import PageHeader from '../components/layout/PageHeader';
import ChatForm from '../features/chat/ChatForm';
import ChatHistoryPanel from '../features/chat/ChatHistoryPanel';
import useAutoGrow from '../hooks/useAutoGrow';
import useFetch from '../hooks/useFetch';
import { chatService } from '../services/chatService';
import { inventoryService } from '../services/inventoryService';
import { purchaseOrderService } from '../services/purchaseOrderService';
import { useMasterStore } from '../store/masterStore';
import { toast } from '../store/toastStore';
import { OPEN_PO_STATUSES } from '../utils/constants';
import { t } from '../i18n';

/* -------------------------------------------------------------------------- */
/*  Konfigurasi                                                               */
/* -------------------------------------------------------------------------- */

const QUICK_ACTIONS = [
  'Ringkas stok saat ini untuk setiap item',
  'Item mana yang stoknya critical?',
  'Ringkas PO yang belum diterima',
  'Saya ingin membuat produk baru',
  'Daftarkan supplier baru',
];

const greeting = () => ({
  id: 'm0',
  role: 'agent',
  blocks: [
    {
      type: 'text',
      text: t('Halo, saya Agent MRP. Tanyakan ringkasan stok, item critical, supplier per material, BOM, jadwal produksi, hasil planning, atau PO terbuka; setiap jawaban diverifikasi terhadap database. Saya juga bisa membuat, mengubah, atau menghapus Purchase Order (mis. "Buat PO 50 Ban Luar Karet") — selalu dengan konfirmasi Anda dulu, lalu supplier dihubungi via Telegram — serta menambah produk final, material beli, dan supplier baru lewat formulir di chat.'),
    },
  ],
});

const TOOL_LABELS = {
  get_stock_summary: 'Ringkasan stok',
  get_critical_items: 'Item critical',
  find_materials: 'Cari material',
  get_material_suppliers: 'Supplier material',
  list_suppliers: 'Daftar supplier',
  get_open_purchase_orders: 'PO terbuka',
  get_latest_planning_run: 'Planning terakhir',
  get_bom: 'BOM',
  list_products: 'Produk final',
  estimate_production_profit: 'Estimasi keuntungan',
  get_production_schedules: 'Jadwal produksi',
  get_po_supplier_status: 'Konfirmasi supplier',
  query_database: 'Query database',
};

const ACTION_STATUS = {
  approved: { label: 'Dijalankan', tone: 'text-emerald-700', icon: 'check' },
  rejected: { label: 'Dibatalkan', tone: 'text-slate-500', icon: 'x' },
  expired: { label: 'Kedaluwarsa / digantikan', tone: 'text-slate-500', icon: 'x' },
  failed: { label: 'Gagal', tone: 'text-red-700', icon: 'alert' },
};

// Layar lebar (md+): panel riwayat berdampingan dengan chat; di bawahnya panel menimpa chat.
const isDesktop = () => window.matchMedia?.('(min-width: 768px)').matches ?? true;

let uid = 0;
const nextId = (p = 'id') => `${p}${Date.now().toString(36)}${uid++}`;

/* -------------------------------------------------------------------------- */
/*  Status bar                                                                */
/* -------------------------------------------------------------------------- */

function AgentBadge({ busy }) {
  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium ${
        busy ? 'border-indigo-200 bg-indigo-50 text-indigo-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'
      }`}
    >
      <span className="relative flex h-2 w-2">
        {busy && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75 motion-reduce:animate-none" />}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${busy ? 'bg-indigo-600' : 'bg-emerald-500'}`} />
      </span>
      {busy ? t('Agent bekerja') : t('Agent aktif')}
    </div>
  );
}

function MiniStat({ label, value, tone, to }) {
  return (
    <Link to={to} className={`flex items-baseline gap-2 rounded-lg border px-3.5 py-2 transition-colors hover:brightness-95 ${tone}`}>
      <span className="text-xl font-bold leading-none tabular-nums">{value ?? '–'}</span>
      <span className="text-xs font-medium">{label}</span>
    </Link>
  );
}

/* -------------------------------------------------------------------------- */
/*  Chat                                                                      */
/* -------------------------------------------------------------------------- */

function DataTable({ columns, rows, title }) {
  return (
    <div className="my-2 overflow-x-auto rounded-lg border border-slate-200 bg-white">
      {title && <div className="border-b border-slate-100 px-3 py-2 text-xs font-medium text-slate-600">{title}</div>}
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-500">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-3 py-2 font-medium">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((cell, j) => (
                <td key={j} className={`px-3 py-2 ${j === 0 ? 'font-medium text-slate-900' : 'text-slate-600'}`}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Notice({ text }) {
  return (
    <p className="my-2 flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
      <CommonIcon name="alert" className="mt-0.5 h-4 w-4" />
      <span>{text}</span>
    </p>
  );
}

function ActionCard({ action, onResolve, busy }) {
  if (!action) return null;
  const done = action.status !== 'pending';
  const st = ACTION_STATUS[action.status];
  const danger = action.kind === 'delete';
  return (
    <div className={`my-2 rounded-xl border border-l-4 p-4 ${danger ? 'border-red-200 border-l-red-600 bg-red-50/60' : 'border-primary-200 border-l-primary-600 bg-primary-50/70'}`}>
      <div className="text-sm font-medium text-slate-900">{t(action.title)}</div>
      <p className="mt-0.5 text-xs text-slate-600">{t(action.detail)}</p>
      {action.tables?.map((item, i) => (
        <DataTable key={i} columns={item.columns} rows={item.rows} title={t(item.title)} />
      ))}
      {action.warnings?.map((w) => <Notice key={w} text={w} />)}
      {done ? (
        <p className={`mt-2 inline-flex items-center gap-1 text-xs font-medium ${st?.tone ?? 'text-slate-500'}`}>
          <CommonIcon name={st?.icon ?? 'info'} className="h-3.5 w-3.5" />
          {t(st?.label ?? action.status)}
        </p>
      ) : (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => onResolve(action.id, 'approve')}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium text-white shadow-sm disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${danger ? 'bg-red-600 hover:bg-red-700 focus-visible:outline-red-600' : 'bg-primary-600 hover:bg-primary-700 focus-visible:outline-indigo-600'}`}
          >
            {t(action.approveLabel)}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onResolve(action.id, 'reject')}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
          >
            {t('Batal')}
          </button>
        </div>
      )}
    </div>
  );
}

function Options({ options, onPick, disabled }) {
  return (
    <div className="my-2 flex flex-wrap gap-2">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          disabled={disabled}
          onClick={() => onPick(o.value)}
          className="rounded-lg border border-indigo-200 bg-white px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
        >
          {t(o.label)}
        </button>
      ))}
    </div>
  );
}

function PageLink({ to, label }) {
  return (
    <Link to={to} className="my-1 mr-2 inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-white px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-50">
      {label}
      <CommonIcon name="chevronRight" className="h-3.5 w-3.5" />
    </Link>
  );
}

function ConfidenceBadge({ meta }) {
  if (!meta?.evaluated || meta.score == null) return null;
  const tone = meta.passed ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-800';
  const m = meta.metrics ?? {};
  const pct = (v) => (v == null ? '–' : `${Math.round(v * 100)}%`);
  const title = `Faithfulness ${pct(m.faithfulness)} · Relevansi ${pct(m.answer_relevance)} · Angka ${pct(m.numeric_grounding)} · Kelengkapan ${pct(m.completeness)}`;
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${tone}`}>
      {meta.passed && <CommonIcon name="check" className="h-3 w-3" />}
      {meta.passed ? t('Terverifikasi') : t('Belum terverifikasi')} · {t('skor')} {meta.score.toFixed(2)}
    </span>
  );
}

function Sources({ sources }) {
  if (!sources?.length) return null;
  return (
    <details className="group text-xs text-slate-500">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded px-1 hover:text-slate-700">
        <CommonIcon name="chevronDown" className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
        {t('Sumber data ({n})', { n: sources.length })}
      </summary>
      <ul className="mt-1.5 space-y-1.5">
        {sources.map((s) => (
          <li key={s.id} className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1.5">
            <span className="font-medium text-slate-700">[{s.id}] {t(TOOL_LABELS[s.tool] ?? s.tool)}</span>
            {Object.keys(s.args ?? {}).length > 0 && <span> · {Object.entries(s.args).map(([k, v]) => `${k}: ${v}`).join(', ')}</span>}
            <span> · {s.row_count} baris</span>
            {s.error && <span className="text-red-600"> · {s.error}</span>}
            {s.sql && <pre className="mt-1 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-slate-600">{s.sql}</pre>}
          </li>
        ))}
      </ul>
    </details>
  );
}

function Message({ msg, actions, onResolve, onPick, onSubmitForm, onCancelForm, busy, isLast }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-900 text-white" aria-hidden="true">
          <CommonIcon name="spark" className="h-4 w-4" />
        </div>
      )}
      <div className={`max-w-[85%] text-sm leading-relaxed ${isUser ? 'rounded-2xl rounded-br-md bg-primary-700 px-4 py-2.5 text-white' : 'min-w-0 text-slate-800'}`}>
        {msg.blocks.map((b, i) => {
          if (b.type === 'text') return <p key={i} className="whitespace-pre-wrap py-0.5">{b.text}</p>;
          if (b.type === 'table') return <DataTable key={i} columns={b.columns} rows={b.rows} title={t(b.title)} />;
          if (b.type === 'notice') return <Notice key={i} text={b.text} />;
          if (b.type === 'action') return <ActionCard key={i} action={actions[b.actionId]} onResolve={onResolve} busy={busy} />;
          if (b.type === 'options') return <Options key={i} options={b.options} onPick={onPick} disabled={busy || !isLast} />;
          if (b.type === 'form') return <ChatForm key={i} block={b} editable={isLast && !busy} onSubmit={onSubmitForm} onCancel={onCancelForm} />;
          if (b.type === 'link') return <PageLink key={i} to={b.to} label={t(b.label)} />;
          return null;
        })}
        {!isUser && msg.meta && (
          <div className="mt-2 flex flex-wrap items-start gap-2">
            <ConfidenceBadge meta={msg.meta} />
            <Sources sources={msg.meta.sources} />
          </div>
        )}
      </div>
    </div>
  );
}

function Progress({ steps }) {
  return (
    <div className="flex gap-3" role="status" aria-label={t('Agent sedang bekerja')}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-900 text-white" aria-hidden="true"><CommonIcon name="spark" className="h-4 w-4" /></div>
      <ol className="space-y-1 pt-1.5 text-xs text-slate-500">
        {steps.length === 0 && (
          <li className="flex items-center gap-1 pt-1">
            {[0, 150, 300].map((d) => (
              <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 motion-reduce:animate-none" style={{ animationDelay: `${d}ms` }} />
            ))}
          </li>
        )}
        {steps.map((s, i) => {
          const active = i === steps.length - 1;
          return (
            <li key={s.key} className={`flex items-center gap-2 ${active ? 'font-medium text-indigo-700' : ''}`}>
              {active
                ? <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600 motion-reduce:animate-none" />
                : <CommonIcon name="check" className="h-3.5 w-3.5 text-emerald-600" />}
              {t(s.label)}
              {s.tool && <span className="text-slate-400">· {t(TOOL_LABELS[s.tool] ?? s.tool)}</span>}
              {s.score != null && <span className={s.passed ? 'text-emerald-700' : 'text-amber-700'}>· skor {s.score.toFixed(2)}</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Composer({ onSend, busy }) {
  const [text, setText] = useState('');
  const box = useAutoGrow(text, 192);          // memanjang mengikuti pesan, maksimal ±8 baris lalu bergulir

  const submit = () => {
    if (busy || !text.trim()) return;
    onSend(text);
    setText('');
  };

  return (
    <div className="border-t border-slate-200 bg-slate-50/60 p-4">
      <div className="mb-3 flex flex-wrap gap-2">
        {QUICK_ACTIONS.map((q) => t(q)).map((q) => (   // dikirim dalam bahasa yang dipilih
          <button
            key={q}
            type="button"
            disabled={busy}
            onClick={() => onSend(q)}
            className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>

      <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white p-2 shadow-sm focus-within:border-primary-500 focus-within:ring-3 focus-within:ring-primary-500/20">
        <textarea
          ref={box}
          rows={1}
          value={text}
          maxLength={2000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
          }}
          placeholder={t('Tanyakan data MRP, minta ubah PO, atau tambah produk/material/supplier baru')}
          className="max-h-48 min-h-[2.25rem] flex-1 resize-none bg-transparent px-1 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
        />
        <button
          type="button"
          aria-label={t('Kirim')}
          onClick={submit}
          disabled={busy || !text.trim()}
          className="rounded-lg bg-primary-600 p-2 text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          <CommonIcon name="send" className="h-5 w-5" />
        </button>
      </div>
      <p className="mt-1.5 text-xs text-slate-400">{t('Enter untuk kirim, Shift+Enter untuk baris baru.')}</p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Halaman                                                                   */
/* -------------------------------------------------------------------------- */

export default function AgenticMrpPage() {
  const inv = useFetch(() => inventoryService.list(), []);
  const pos = useFetch(() => purchaseOrderService.list(), []);
  const count = (s) => inv.data?.filter((r) => r.status === s).length;
  const openPo = pos.data?.filter((p) => OPEN_PO_STATUSES.includes(p.status)).length;

  const [threadId, setThreadId] = useState(() => chatService.threadId());
  const [messages, setMessages] = useState(() => [greeting()]);
  const [actions, setActions] = useState({});
  const [busy, setBusy] = useState(false);
  const [steps, setSteps] = useState([]);
  const endRef = useRef(null);
  const abortRef = useRef(null);

  // Riwayat percakapan: daftar di panel kiri, dibuka ulang dengan memilihnya, dihapus satu per satu atau semua.
  const convos = useFetch(() => chatService.threads(), []);
  const [historyOpen, setHistoryOpen] = useState(isDesktop);
  const [historyLoading, setHistoryLoading] = useState(false);   // isi percakapan sedang dimuat
  const [toDelete, setToDelete] = useState(null);                // percakapan atau null
  const [deleting, setDeleting] = useState(false);
  const pickedFromList = useRef(false);                          // galat muat hanya ditampilkan bila pengguna yang memilih

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, steps]);

  useEffect(() => {
    let alive = true;
    const picked = pickedFromList.current;
    pickedFromList.current = false;
    setMessages([greeting()]);
    setActions({});
    setHistoryLoading(true);
    chatService
      .history(threadId)
      .then((res) => {
        if (alive && res.messages?.length) {
          setMessages([greeting(), ...res.messages.map((m) => ({ id: nextId('h'), ...m }))]);
        }
        if (alive && res.actions) setActions(res.actions);
      })
      .catch((e) => { if (alive && picked) toast.error(t('Gagal memuat percakapan: {msg}', { msg: e.message })); })
      .finally(() => { if (alive) setHistoryLoading(false); });
    return () => { alive = false; };
  }, [threadId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const push = (msg) => setMessages((m) => [...m, { id: nextId('m'), ...msg }]);

  const onProgress = useCallback((e) => {
    if (e.type !== 'progress') return;
    setSteps((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.stage === e.stage && !e.tool) {
        return [...prev.slice(0, -1), { ...last, ...e, key: last.key }];
      }
      return [...prev, { ...e, key: nextId('s') }];
    });
  }, []);

  /** Runs one streamed turn: a new message, or a resume answer to a confirmation card. */
  const runTurn = async (payload) => {
    setBusy(true);
    setSteps([]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await chatService.stream({ ...payload, threadId, onEvent: onProgress, signal: controller.signal });
      if (res.type === 'final') {
        if (res.actions) setActions((a) => ({ ...a, ...res.actions }));
        if (res.action_updates) {
          setActions((a) => Object.fromEntries(Object.entries(a).map(([id, v]) => [id, res.action_updates[id] ? { ...v, ...res.action_updates[id] } : v])));
        }
        push({ role: 'agent', blocks: res.blocks, meta: res.meta });
        // Produk/material/supplier baru tersimpan -> dropdown master di halaman lain perlu dimuat ulang.
        if (res.meta?.intent === 'master_data' && Object.values(res.action_updates ?? {}).some((u) => u.status === 'approved')) {
          useMasterStore.getState().invalidate();
        }
      } else {
        push({ role: 'agent', blocks: [{ type: 'text', text: res.message ?? t('Agent gagal merespons. Coba kirim ulang.') }] });
      }
    } catch (e) {
      if (e?.name !== 'AbortError') {
        push({ role: 'agent', blocks: [{ type: 'text', text: t('Agent gagal merespons: {msg}', { msg: e.message }) }] });
      }
    } finally {
      setBusy(false);
      setSteps([]);
      abortRef.current = null;
      convos.reload();                // percakapan baru muncul di riwayat, yang lama naik ke atas
    }
  };

  const handleSend = async (text) => {
    const content = text.trim();
    if (!content || busy || historyLoading) return;
    push({ role: 'user', blocks: [{ type: 'text', text: content }] });
    // Pesan baru menggantikan kartu konfirmasi yang masih menunggu (backend menandainya superseded).
    setActions((a) => Object.fromEntries(Object.entries(a).map(([id, v]) => [id, v.status === 'pending' ? { ...v, status: 'expired' } : v])));
    await runTurn({ message: content });
  };

  const handleResolve = async (id, decision) => {
    if (busy) return;
    await runTurn({ resume: { actionId: id, decision } });
  };

  const handleSubmitForm = async (formId, values, title) => {
    if (busy) return;
    push({ role: 'user', blocks: [{ type: 'text', text: t('Formulir {title} dikirim.', { title: title.toLowerCase() }) }] });
    await runTurn({ resume: { actionId: formId, decision: 'submit', values } });
  };

  const handleCancelForm = async (formId) => {
    if (busy) return;
    await runTurn({ resume: { actionId: formId, decision: 'reject' } });
  };

  // Di layar kecil panel riwayat menutupi chat, jadi ditutup setelah memilih.
  const closeHistoryOnMobile = () => {
    if (!isDesktop()) setHistoryOpen(false);
  };

  const newConversation = () => {
    abortRef.current?.abort();
    setThreadId(chatService.threadId({ reset: true }));
    closeHistoryOnMobile();
  };

  const openConversation = (id) => {
    closeHistoryOnMobile();
    if (id === threadId) return;
    abortRef.current?.abort();
    pickedFromList.current = true;
    setThreadId(chatService.openThread(id));
  };

  const confirmDelete = async () => {
    const target = toDelete;
    setDeleting(true);
    try {
      await chatService.deleteThread(target.thread_id);
    } catch (e) {
      // 404 = sudah terhapus (mis. dari tab lain): tujuannya tercapai, lanjutkan seperti berhasil.
      if (e?.status !== 404) {
        toast.error(e.message);
        setDeleting(false);
        return;
      }
    }
    toast.success('Percakapan dihapus');
    if (target.thread_id === threadId) newConversation();   // yang sedang dibuka ikut hilang
    setToDelete(null);
    setDeleting(false);
    convos.reload();
  };

  return (
    <>
      <PageHeader title={t('Agentic MRP Assistant')} />

      {(inv.error || pos.error) && (
        <p className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {(inv.error ?? pos.error).message} — {t('pastikan backend berjalan dan dapat dijangkau.')}
        </p>
      )}

      {/* Quick status bar */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <AgentBadge busy={busy} />
        <span className="mx-1 hidden h-6 w-px bg-slate-200 sm:block" aria-hidden="true" />
        <MiniStat label={t('Stok Critical')} value={count('CRITICAL')} to="/inventory" tone="border-red-200 bg-red-50 text-red-700" />
        <MiniStat label={t('Stok Warning')} value={count('WARNING')} to="/inventory" tone="border-amber-200 bg-amber-50 text-amber-800" />
        <MiniStat label={t('PO Terbuka')} value={openPo} to="/purchase-orders" tone="border-indigo-200 bg-indigo-50 text-indigo-700" />
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => setHistoryOpen((o) => !o)}
            aria-pressed={historyOpen}
            aria-controls="chat-history"
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium shadow-sm ${
              historyOpen ? 'border-primary-300 bg-primary-50 text-primary-800' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
            }`}
          >
            <CommonIcon name="clock" className="h-3.5 w-3.5" />
            {t('Riwayat')}
          </button>
          <button
            type="button"
            onClick={newConversation}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <CommonIcon name="plus" className="h-3.5 w-3.5" />
            {t('Percakapan baru')}
          </button>
        </div>
      </div>

      {/* Split view */}
      <div className="relative flex h-[calc(100vh-17rem)] min-h-[34rem] overflow-hidden rounded-2xl border border-slate-200 bg-white">
        {historyOpen && (
          <>
            {/* Layar kecil: panel menimpa chat; klik di luar menutupnya */}
            <div className="anim-fade absolute inset-0 z-10 bg-primary-950/40 md:hidden" onClick={() => setHistoryOpen(false)} aria-hidden="true" />
            <aside
              id="chat-history"
              aria-label={t('Riwayat percakapan')}
              className="absolute inset-y-0 left-0 z-20 w-72 max-w-[85%] border-r border-slate-200 bg-white shadow-xl md:static md:z-auto md:max-w-none md:shrink-0 md:shadow-none"
            >
              <ChatHistoryPanel
                threads={convos.data?.threads}
                loading={convos.loading}
                error={convos.error}
                activeId={threadId}
                busy={busy}
                onOpen={openConversation}
                onDelete={setToDelete}
                onRetry={convos.reload}
                onClose={() => setHistoryOpen(false)}
              />
            </aside>
          </>
        )}
        <section className="flex min-w-0 flex-1 flex-col" aria-label={t('Percakapan dengan Agent')}>
          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-6" role="log" aria-live="polite">
            {historyLoading ? (
              <Spinner label="Memuat percakapan…" />
            ) : (
              messages.map((m, i) => (
                <Message
                  key={m.id}
                  msg={m}
                  actions={actions}
                  onResolve={handleResolve}
                  onPick={handleSend}
                  onSubmitForm={handleSubmitForm}
                  onCancelForm={handleCancelForm}
                  busy={busy}
                  isLast={i === messages.length - 1}
                />
              ))
            )}
            {busy && <Progress steps={steps} />}
            <div ref={endRef} />
          </div>
          <Composer onSend={handleSend} busy={busy || historyLoading} />
        </section>
      </div>

      <ConfirmDialog
        open={toDelete != null}
        title="Hapus percakapan?"
        message={t('Percakapan "{title}" akan dihapus permanen dan tidak bisa dikembalikan.', { title: toDelete?.title ?? '' })}
        confirmLabel="Hapus"
        loading={deleting}
        onConfirm={confirmDelete}
        onCancel={() => { if (!deleting) setToDelete(null); }}
      />
    </>
  );
}