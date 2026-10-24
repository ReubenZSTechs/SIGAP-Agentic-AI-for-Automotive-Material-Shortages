import axios from 'axios';
import { t } from '../i18n';
import { currentLang } from '../store/settingsStore';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '/api/v1',
  timeout: 15000,
});

// Bahasa pilihan pengguna -> backend menerjemahkan pesan error (Accept-Language).
api.interceptors.request.use((config) => {
  config.headers['Accept-Language'] = currentLang();
  return config;
});

// Response: kembalikan body langsung. Error: seragamkan jadi { status, message }.
api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    let message;
    if (!err.response) {
      message = t('Tidak dapat terhubung ke server');
    } else {
      const d = err.response.data?.detail;
      message = Array.isArray(d) // 422 Pydantic
        ? d.map((e) => `${e.loc?.slice(1).join('.')}: ${e.msg}`).join('; ')
        : d ?? err.message ?? t('Terjadi kesalahan'); // AppError {detail}
    }
    return Promise.reject({ status: err.response?.status, message, data: err.response?.data });
  },
);

export default api;
