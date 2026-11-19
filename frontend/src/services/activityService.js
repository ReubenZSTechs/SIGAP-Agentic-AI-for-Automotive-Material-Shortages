import api from './api';

// Riwayat Aktivitas (backend: app/api/v1/endpoints/activity.py): keputusan manajer & tindakan agent.
export const activityService = {
  list: (params) => api.get('/activity', { params, paramsSerializer: { indexes: null } }),
  facets: () => api.get('/activity/facets'),
  get: (id) => api.get(`/activity/${id}`),
};
