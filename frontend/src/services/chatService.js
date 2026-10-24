import api from './api';
import { currentLang } from '../store/settingsStore';
import { t } from '../i18n';

const BASE = (import.meta.env.VITE_API_URL ?? '/api/v1').replace(/\/$/, '');
const THREAD_KEY = 'mrp-chat-thread';

/** Parses one SSE frame ("event: x\ndata: {...}") into an object, or null. */
function parseFrame(frame) {
  const data = frame
    .split('\n')
    .filter((l) => l.startsWith('data:'))
    .map((l) => l.slice(5).trimStart())
    .join('\n');
  if (!data) return null;
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

/** Error message from a non-2xx response ({detail} like the rest of the API). */
async function errorMessage(res) {
  try {
    const body = await res.json();
    return body.detail ?? `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

export const chatService = {
  /**
   * Streams one chat turn. Calls `onEvent` for every `progress`, then `final` or `error` event.
   * Resolves with the last event. Abort with `signal`.
   * Pass either `message` (new turn) or `resume` to answer what the agent is waiting for:
   * a confirmation card ({ actionId, decision: 'approve' | 'reject' }) or a chat form
   * ({ actionId: formId, decision: 'submit', values } / { actionId: formId, decision: 'reject' }).
   */
  async stream({ message, resume, threadId, onEvent, signal }) {
    const answer = resume && { action_id: resume.actionId, decision: resume.decision };
    if (resume?.values) answer.values = resume.values;
    // language: bahasa UI yang dipilih -> Agent menjawab dalam bahasa ini (bukan deteksi otomatis)
    const body = resume
      ? { thread_id: threadId, resume: answer, language: currentLang() }
      : { thread_id: threadId, message, language: currentLang() };
    const res = await fetch(`${BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'Accept-Language': currentLang() },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok) throw { status: res.status, message: await errorMessage(res) };

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let last = null;
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const frames = buffer.split('\n\n');
      buffer = done ? '' : frames.pop();
      for (const frame of frames) {
        const event = parseFrame(frame);
        if (event) {
          last = event;
          onEvent?.(event);
        }
      }
      if (done) break;
    }
    if (!last || (last.type !== 'final' && last.type !== 'error')) {
      throw { message: t('Koneksi ke Agent terputus sebelum jawaban selesai') };
    }
    return last;
  },

  history: (threadId) => api.get(`/chat/${threadId}/history`),
  health: () => api.get('/chat/health'),

  /** Conversation id kept in localStorage so history survives reloads. */
  threadId({ reset = false } = {}) {
    let id = null;
    try {
      id = reset ? null : localStorage.getItem(THREAD_KEY);
    } catch {
      /* storage unavailable */
    }
    if (!id) {
      id = (crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_-]/g, '');
      try {
        localStorage.setItem(THREAD_KEY, id);
      } catch {
        /* storage unavailable */
      }
    }
    return id;
  },
};
