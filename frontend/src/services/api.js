import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '/api/v1',
  timeout: 15000,
});

// Response: kembalikan body langsung. Error: seragamkan jadi { status, message }.
api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    let message;
    if (!err.response) {
      message = 'Tidak dapat terhubung ke server';
    } else {
      const d = err.response.data?.detail;
      message = Array.isArray(d) // 422 Pydantic
        ? d.map((e) => `${e.loc?.slice(1).join('.')}: ${e.msg}`).join('; ')
        : d ?? err.message ?? 'Terjadi kesalahan'; // AppError {detail}
    }
    return Promise.reject({ status: err.response?.status, message, data: err.response?.data });
  },
);

export default api;
