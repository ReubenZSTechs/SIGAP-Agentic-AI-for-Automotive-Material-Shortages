import { BrowserRouter } from 'react-router-dom';
import AppRoutes from './routes';
import { useSettings } from './store/settingsStore';

export default function App() {
  // key={lang}: saat bahasa diganti, semua halaman digambar ulang dengan teks baru.
  const lang = useSettings((s) => s.lang);
  return <BrowserRouter><AppRoutes key={lang} /></BrowserRouter>;
}
