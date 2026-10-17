import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import CommonIcon from '../components/common/Icon';
import PageHeader from '../components/layout/PageHeader';
import useFetch from '../hooks/useFetch';
import { inventoryService } from '../services/inventoryService';
import { purchaseOrderService } from '../services/purchaseOrderService';
import { OPEN_PO_STATUSES } from '../utils/constants';

/* -------------------------------------------------------------------------- */
/*  Konfigurasi                                                               */
/* -------------------------------------------------------------------------- */

const QUICK_ACTIONS = [
  'Jalankan Eksplosi BOM',
  'Cek Stok Critical',
  'Buat Draft PO Multi-Vendor',
  'Ringkas PO yang belum diterima',
];

const INITIAL_ACTIONS = {
  seed1: {
    id: 'seed1',
    title: 'Buat 2 PO baru untuk item stok critical',
    detail: 'Agent mengelompokkan kebutuhan ke 2 vendor dengan harga dan lead time terbaik.',
    approveLabel: 'Buat draft PO',
    status: 'pending',
  },
};

const INITIAL_MESSAGES = [
  {
    id: 'm0',
    role: 'agent',
    blocks: [
      {
        type: 'text',
        text: 'Halo, saya Agent MRP. Saya bisa menjalankan eksplosi BOM, memeriksa stok, memilih vendor, dan menyiapkan draft PO. Setiap tindakan yang mengubah data akan saya minta persetujuan Anda dulu.',
      },
      { type: 'action', actionId: 'seed1' },
    ],
  },
];

/* -------------------------------------------------------------------------- */
/*  Util                                                                      */
/* -------------------------------------------------------------------------- */

let uid = 0;
const nextId = (p = 'id') => `${p}${Date.now().toString(36)}${uid++}`;

// Field inventory belum pasti namanya — sesuaikan dengan response backend Anda.
const pick = (row, ...keys) => {
  for (const k of keys) if (row?.[k] !== undefined && row?.[k] !== null) return row[k];
  return '–';
};

/**
 * Titik integrasi backend agent.
 * Ganti isi fungsi ini dengan panggilan ke endpoint agent Anda, mis.:
 *   const res = await agentService.chat({ message, attachments });
 *   return res; // { blocks, actions, step }
 * Bentuk keluaran:
 *   blocks:  [{ type:'text', text } | { type:'table', columns, rows } | { type:'action', actionId }]
 *   actions: { [id]: { id, title, detail, approveLabel, status:'pending' } }
 *   step:    nomor langkah workflow yang sedang dikerjakan (0–5)
 */
async function runAgent(message, { inventory }) {
  await new Promise((r) => setTimeout(r, 900));
  const q = message.toLowerCase();

  if (q.includes('critical') || q.includes('stok')) {
    const rows = (inventory ?? [])
      .filter((r) => r.status === 'CRITICAL')
      .slice(0, 8)
      .map((r) => [
        pick(r, 'material_name', 'item_name', 'name'),
        pick(r, 'on_hand', 'stock', 'qty'),
        pick(r, 'safety_stock', 'min_stock', 'reorder_point'),
      ]);
    if (!rows.length) {
      return {
        step: 2,
        blocks: [{ type: 'text', text: 'Tidak ada item dengan status Critical saat ini.' }],
      };
    }
    const id = nextId('a');
    return {
      step: 2,
      blocks: [
        { type: 'text', text: `Ada ${rows.length} item stok Critical. Berikut daftarnya:` },
        { type: 'table', columns: ['Material', 'Stok', 'Batas aman'], rows },
        { type: 'text', text: 'Saya bisa mencarikan vendor terbaik untuk semuanya.' },
        { type: 'action', actionId: id },
      ],
      actions: {
        [id]: {
          id,
          title: 'Jalankan Smart Sourcing untuk item Critical',
          detail: 'Membandingkan harga dan lead time vendor. Belum ada PO yang dibuat.',
          approveLabel: 'Jalankan sourcing',
          status: 'pending',
        },
      },
    };
  }

  if (q.includes('eksplosi') || q.includes('bom')) {
    const id = nextId('a');
    return {
      step: 1,
      blocks: [
        { type: 'text', text: 'Eksplosi BOM akan dihitung dari jadwal produksi (MPS) yang aktif, lalu dibandingkan dengan stok saat ini.' },
        { type: 'action', actionId: id },
      ],
      actions: {
        [id]: {
          id,
          title: 'Jalankan eksplosi BOM',
          detail: 'Membuat run planning baru dari MPS aktif.',
          approveLabel: 'Jalankan',
          status: 'pending',
        },
      },
    };
  }

  if (q.includes('po')) {
    const id = nextId('a');
    return {
      step: 4,
      blocks: [
        { type: 'text', text: 'Draft PO multi-vendor siap dibuat berdasarkan hasil sourcing terakhir. Anda masih bisa mengubah draft sebelum dikirim ke vendor.' },
        { type: 'action', actionId: id },
      ],
      actions: {
        [id]: {
          id,
          title: 'Buat draft PO multi-vendor',
          detail: 'Satu PO per vendor, status Draft.',
          approveLabel: 'Buat draft PO',
          status: 'pending',
        },
      },
    };
  }

  return {
    step: null,
    blocks: [
      { type: 'text', text: 'Saya belum paham permintaan itu. Coba salah satu aksi cepat di bawah, atau sebutkan langkah MRP yang ingin dikerjakan.' },
    ],
  };
}

/* -------------------------------------------------------------------------- */
/*  Ikon                                                                      */
/* -------------------------------------------------------------------------- */

const Icon = ({ d, className = 'h-5 w-5' }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
    <path d={d} />
  </svg>
);
const ICONS = {
  send: 'M20 4L4 11l6 2 2 6 8-15z',
  clip: 'M21 11.5l-8.6 8.6a5 5 0 01-7-7l9-9a3.3 3.3 0 014.7 4.7l-9 9a1.7 1.7 0 01-2.4-2.4l8.3-8.3',
  close: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12.5l4.5 4.5L19 7',
};

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
      {busy ? 'Agent bekerja' : 'Agent aktif'}
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

function DataTable({ columns, rows }) {
  return (
    <div className="my-2 overflow-x-auto rounded-lg border border-slate-200 bg-white">
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

function ActionCard({ action, onResolve }) {
  if (!action) return null;
  const done = action.status !== 'pending';
  return (
    <div className="my-2 rounded-xl border border-primary-200 border-l-4 border-l-primary-600 bg-primary-50/70 p-4">
      <div className="text-sm font-medium text-slate-900">{action.title}</div>
      <p className="mt-0.5 text-xs text-slate-600">{action.detail}</p>
      {done ? (
        <p className={`mt-2 inline-flex items-center gap-1 text-xs font-medium ${action.status === 'approved' ? 'text-emerald-700' : 'text-slate-500'}`}>
          {action.status === 'approved' && <Icon d={ICONS.check} className="h-3.5 w-3.5" />}
          {action.status === 'approved' ? 'Disetujui' : 'Dilewati'}
        </p>
      ) : (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => onResolve(action.id, 'approved')}
            className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-primary-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
          >
            {action.approveLabel}
          </button>
          <button
            type="button"
            onClick={() => onResolve(action.id, 'rejected')}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
          >
            Lewati
          </button>
        </div>
      )}
    </div>
  );
}

function Message({ msg, actions, onResolve }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-900 text-white" aria-hidden="true">
          <CommonIcon name="spark" className="h-4 w-4" />
        </div>
      )}
      <div className={`max-w-[85%] text-sm leading-relaxed ${isUser ? 'rounded-2xl rounded-br-md bg-primary-700 px-4 py-2.5 text-white' : 'text-slate-800'}`}>
        {msg.blocks.map((b, i) => {
          if (b.type === 'text') return <p key={i} className="whitespace-pre-wrap py-0.5">{b.text}</p>;
          if (b.type === 'table') return <DataTable key={i} columns={b.columns} rows={b.rows} />;
          if (b.type === 'action') return <ActionCard key={i} action={actions[b.actionId]} onResolve={onResolve} />;
          return null;
        })}
        {msg.attachments?.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {msg.attachments.map((f) => (
              <span key={f} className="rounded-md bg-white/15 px-2 py-0.5 text-xs">{f}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Typing() {
  return (
    <div className="flex gap-3" role="status" aria-label="Agent sedang mengetik">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-900 text-white" aria-hidden="true"><CommonIcon name="spark" className="h-4 w-4" /></div>
      <div className="flex items-center gap-1 pt-2.5">
        {[0, 150, 300].map((d) => (
          <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 motion-reduce:animate-none" style={{ animationDelay: `${d}ms` }} />
        ))}
      </div>
    </div>
  );
}

function Composer({ onSend, busy }) {
  const [text, setText] = useState('');
  const [files, setFiles] = useState([]);
  const fileRef = useRef(null);

  const submit = () => {
    if (busy || (!text.trim() && !files.length)) return;
    onSend(text, files.map((f) => f.name));
    setText('');
    setFiles([]);
  };

  return (
    <div className="border-t border-slate-200 bg-slate-50/60 p-4">
      <div className="mb-3 flex flex-wrap gap-2">
        {QUICK_ACTIONS.map((q) => (
          <button
            key={q}
            type="button"
            disabled={busy}
            onClick={() => onSend(q, [])}
            className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>

      {files.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {files.map((f, i) => (
            <span key={f.name + i} className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700">
              {f.name}
              <button type="button" aria-label={`Hapus ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))} className="text-slate-400 hover:text-slate-700">
                <Icon d={ICONS.close} className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white p-2 shadow-sm focus-within:border-primary-500 focus-within:ring-3 focus-within:ring-primary-500/20">
        <input ref={fileRef} type="file" multiple hidden onChange={(e) => { setFiles((p) => [...p, ...Array.from(e.target.files)]); e.target.value = ''; }} />
        <button type="button" aria-label="Lampirkan file" onClick={() => fileRef.current?.click()} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-700">
          <Icon d={ICONS.clip} />
        </button>
        <textarea
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
          }}
          placeholder="Minta Agent mengerjakan sesuatu…"
          className="max-h-32 min-h-[2.25rem] flex-1 resize-none bg-transparent px-1 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
        />
        <button
          type="button"
          aria-label="Kirim"
          onClick={submit}
          disabled={busy || (!text.trim() && !files.length)}
          className="rounded-lg bg-primary-600 p-2 text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          <Icon d={ICONS.send} />
        </button>
      </div>
      <p className="mt-1.5 text-xs text-slate-400">Enter untuk kirim, Shift+Enter untuk baris baru.</p>
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

  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [actions, setActions] = useState(INITIAL_ACTIONS);
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, busy]);

  const push = (msg) => setMessages((m) => [...m, { id: nextId('m'), ...msg }]);

  const handleSend = async (text, attachments) => {
    const content = text.trim();
    push({ role: 'user', blocks: content ? [{ type: 'text', text: content }] : [], attachments });
    setBusy(true);
    try {
      const res = await runAgent(content, { inventory: inv.data, attachments });
      if (res.actions) setActions((a) => ({ ...a, ...res.actions }));
      push({ role: 'agent', blocks: res.blocks });
    } catch (e) {
      push({ role: 'agent', blocks: [{ type: 'text', text: `Agent gagal merespons: ${e.message}. Coba kirim ulang.` }] });
    } finally {
      setBusy(false);
    }
  };

  const handleResolve = (id, status) => {
    const action = actions[id];
    setActions((a) => ({ ...a, [id]: { ...a[id], status } }));
    push({
      role: 'agent',
      blocks: [{
        type: 'text',
        text: status === 'approved'
          ? `Baik, "${action.title}" sedang dijalankan. Saya kabari setelah selesai.`
          : `Oke, "${action.title}" saya lewati.`,
      }],
    });
  };

  return (
    <>
      <PageHeader title="Agentic MRP Assistant" />

      {(inv.error || pos.error) && (
        <p className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {(inv.error ?? pos.error).message} — pastikan backend berjalan di http://localhost:8000.
        </p>
      )}

      {/* Quick status bar */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <AgentBadge busy={busy} />
        <span className="mx-1 hidden h-6 w-px bg-slate-200 sm:block" aria-hidden="true" />
        <MiniStat label="Stok Critical" value={count('CRITICAL')} to="/inventory" tone="border-red-200 bg-red-50 text-red-700" />
        <MiniStat label="Stok Warning" value={count('WARNING')} to="/inventory" tone="border-amber-200 bg-amber-50 text-amber-800" />
        <MiniStat label="PO Terbuka" value={openPo} to="/purchase-orders" tone="border-indigo-200 bg-indigo-50 text-indigo-700" />

      </div>

      {/* Split view */}
      <div className="relative flex h-[calc(100vh-17rem)] min-h-[34rem] overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <section className="flex min-w-0 flex-1 flex-col" aria-label="Percakapan dengan Agent">
          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-6" role="log" aria-live="polite">
            {messages.map((m) => (
              <Message key={m.id} msg={m} actions={actions} onResolve={handleResolve} />
            ))}
            {busy && <Typing />}
            <div ref={endRef} />
          </div>
          <Composer onSend={handleSend} busy={busy} />
        </section>

      </div>
    </>
  );
}