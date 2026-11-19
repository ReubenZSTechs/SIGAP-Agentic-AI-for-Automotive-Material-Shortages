import api from './api';

export const productionLineService = {
  list: (params) => api.get('/production-lines', { params }),
};
