import api from './api';

export const planningService = {
  listRuns: () => api.get('/planning/runs'),
  getRun: (id) => api.get(`/planning/runs/${id}`),
  createRun: (body) => api.post('/planning/runs', body), // {date_from, date_to}
  getLines: (id, params) => api.get(`/planning/runs/${id}/lines`, { params }),
  getSourcing: (id, params) => api.get(`/planning/runs/${id}/sourcing`, { params }),
  autoSelect: (id, strategy) => api.post(`/planning/runs/${id}/sourcing/auto-select`, { strategy }),
  selectSupplier: (lineId, body) => api.put(`/planning/lines/${lineId}/selection`, body),
  clearSelection: (lineId) => api.delete(`/planning/lines/${lineId}/selection`),
  generatePOs: (id) => api.post(`/planning/runs/${id}/purchase-orders`),
};
