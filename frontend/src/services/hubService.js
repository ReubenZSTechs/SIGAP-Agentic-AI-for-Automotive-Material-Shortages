import api from './api';

// Agent Hub API (backend: app/api/v1/endpoints/hub.py). Semua aksi tulis membawa nama approver (MVP tanpa login).
const BASE = (import.meta.env.VITE_API_URL ?? '/api/v1').replace(/\/$/, '');
const ENDPOINT = { approve: 'approve', reject: 'reject', revision: 'request-revision' };
const who = (approver) => ({ approver });

export const hubService = {
  // status & agent
  status: () => api.get('/hub/status'),
  setPaused: (paused, approver) => api.post(`/hub/agent/${paused ? 'pause' : 'resume'}`, who(approver)),
  dispatch: () => api.post('/hub/dispatch'),

  // persetujuan
  listApprovals: () => api.get('/hub/approvals'),
  getApproval: (id) => api.get(`/hub/approvals/${id}`),
  decide: (id, mode, body) => (mode === 'choose'
    ? api.post(`/hub/approvals/${id}/choose`, { approver: body.approver, choice: body.choice })
    : api.post(`/hub/approvals/${id}/${ENDPOINT[mode]}`, body)),

  // percakapan (id thread = id supplier)
  listThreads: () => api.get('/hub/threads'),
  getThread: (id) => api.get(`/hub/threads/${id}`),
  sendMessage: (id, text, approver) => api.post(`/hub/threads/${id}/messages`, { text, approver }),
  takeover: (id, approver) => api.post(`/hub/threads/${id}/takeover`, who(approver)),
  release: (id, approver) => api.post(`/hub/threads/${id}/release`, who(approver)),
  sandboxReply: (id, text) => api.post(`/hub/threads/${id}/sandbox-reply`, { text }),
  sendDraft: (outboxId, text, approver) => api.post(`/hub/outbox/${outboxId}/send`, { text, approver }),
  discardDraft: (outboxId, approver) => api.post(`/hub/outbox/${outboxId}/discard`, who(approver)),
  retryMessage: (messageId, approver) => api.post(`/hub/messages/${messageId}/retry`, who(approver)),

  // misi
  missionOptions: () => api.get('/hub/mission-options'),
  poOptions: (poId) => api.get(`/hub/mission-options/po/${poId}`),
  listMissions: () => api.get('/hub/missions'),
  getMission: (id) => api.get(`/hub/missions/${id}`),
  createMission: (body) => api.post('/hub/missions', body),
  remindMission: (id, supplierIds, approver) => api.post(`/hub/missions/${id}/remind`, { supplier_ids: supplierIds ?? null, approver }),
  escalateTarget: (id, supplierId, approver) => api.post(`/hub/missions/${id}/escalate`, { supplier_id: supplierId, approver }),
  closeMission: (id, approver) => api.post(`/hub/missions/${id}/close`, who(approver)),
  cancelMission: (id, approver) => api.post(`/hub/missions/${id}/cancel`, who(approver)),
  poContext: (poId) => api.get(`/hub/po/${poId}/context`),

  // dokumen
  listDocuments: () => api.get('/hub/documents'),
  getDocument: (id) => api.get(`/hub/documents/${id}`),
  documentFileUrl: (id) => `${BASE}/hub/documents/${id}/file`,
  updateDocument: (id, body) => api.patch(`/hub/documents/${id}`, body),
  archiveDocument: (id, approver, confirmMismatch) => api.post(`/hub/documents/${id}/archive`, { approver, confirm_mismatch: confirmMismatch }),
  requestDocumentAgain: (id, approver, reason) => api.post(`/hub/documents/${id}/request-again`, { approver, reason }),
  sandboxAttachment: (body) => api.post('/hub/sandbox/attachment', body),

  // pengaturan
  getPolicies: () => api.get('/hub/policies'),
  savePolicies: (body, approver) => api.put('/hub/policies', { ...body, approver }),
  getTemplates: () => api.get('/hub/templates'),
  saveTemplate: ({ id, name, scenario, body }) => (id
    ? api.put(`/hub/templates/${id}`, { name, scenario, body })
    : api.post('/hub/templates', { name, scenario, body })),
  listSuppliers: () => api.get('/hub/suppliers'),
  getSupplier: (id) => api.get(`/hub/suppliers/${id}`),
  inviteSupplier: (id, approver) => api.post(`/hub/suppliers/${id}/invite`, who(approver)),
  linkSandbox: (id, approver) => api.post(`/hub/suppliers/${id}/link-sandbox`, who(approver)),
  audit: (limit = 100) => api.get('/hub/audit', { params: { limit } }),
};
