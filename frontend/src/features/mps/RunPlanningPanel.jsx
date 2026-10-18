import Icon from '../../components/common/Icon';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/common/Button';
import Card from '../../components/common/Card';
import Input from '../../components/common/Input';
import { planningService } from '../../services/planningService';
import { toast } from '../../store/toastStore';
import { todayISO } from '../../utils/formatters';

// Default rentang = jadwal PLANNED paling awal s.d. paling akhir (bisa diubah user).
export default function RunPlanningPanel({ schedules, prefill }) {
  const navigate = useNavigate();
  const [from, setFrom] = useState(todayISO());
  const [to, setTo] = useState(todayISO());
  const [running, setRunning] = useState(false);
  const touched = useRef(false);

  useEffect(() => {
    if (touched.current) return;
    const dates = (schedules ?? []).filter((s) => s.status === 'PLANNED').map((s) => s.production_date).sort();
    if (dates.length) { setFrom(dates[0]); setTo(dates[dates.length - 1]); }
  }, [schedules]);

  useEffect(() => { // dari banner "Jalankan Ulang": isi rentang run yang basi
    if (prefill) { touched.current = true; setFrom(prefill.date_from); setTo(prefill.date_to); }
  }, [prefill]);

  const run = async () => {
    if (!from || !to) return toast.error('Isi rentang tanggal');
    if (from > to) return toast.error('Tanggal awal tidak boleh setelah tanggal akhir');
    setRunning(true);
    try {
      const res = await planningService.createRun({ date_from: from, date_to: to });
      toast.success(`Planning run #${res.id} dibuat`);
      navigate(`/planning/${res.id}`);
    } catch (e) { toast.error(e.message); } finally { setRunning(false); } // 400 tanpa jadwal / 422 BOM tak lengkap
  };

  return (
    <Card title="Jalankan Stock Planning">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm font-medium text-slate-700">Dari
          <Input type="date" className="mt-1" value={from}
                 onChange={(e) => { touched.current = true; setFrom(e.target.value); }} />
        </label>
        <label className="text-sm font-medium text-slate-700">Sampai
          <Input type="date" className="mt-1" value={to}
                 onChange={(e) => { touched.current = true; setTo(e.target.value); }} />
        </label>
        <Button loading={running} onClick={run}><Icon name="play" /> Jalankan Planning</Button>
      </div>
    </Card>
  );
}
