import { useMemo } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';
import { scheduleService } from '../../services/scheduleService';
import { toast } from '../../store/toastStore';
import { t } from '../../i18n';
import { currentLang } from '../../store/settingsStore';

const inStale = (d, runs) => runs.some((r) => d >= r.date_from && d <= r.date_to);

// Kalender = tampilan lain dari data `schedules` yang sama. Drag-and-drop HANYA untuk reschedule tanggal
// jadwal PLANNED; perubahan status hanya lewat side-panel.
export default function ScheduleCalendar({ schedules, staleRuns, showCancelled, lineId, onSelect, onChanged }) {
  const events = useMemo(() => schedules
    .filter((s) => (showCancelled || s.status !== 'CANCELLED') && (!lineId || s.production_line_id === lineId))
    .map((s) => ({
      id: String(s.id),
      title: `${s.batch_code} · ${s.product_name} ×${s.target_qty} · ${s.line_code}`,
      start: s.production_date,
      allDay: true, // tanggal saja -> tidak ada isu zona waktu
      startEditable: s.editable, // hanya PLANNED yang bisa diseret
      classNames: [`ev-${s.status}`, inStale(s.production_date, staleRuns) && 'ev-stale'].filter(Boolean),
    })), [schedules, staleRuns, showCancelled, lineId]);

  const onDrop = async (info) => { // update optimistis: event sudah pindah di layar
    try {
      await scheduleService.update(Number(info.event.id), { production_date: info.event.startStr.slice(0, 10) });
      toast.info('Jadwal dipindah. Planning run perlu dijalankan ulang.');
      onChanged(); // reload jadwal + run -> banner basi
    } catch (e) {
      info.revert(); // rollback bila backend menolak (mis. 409)
      toast.error(e.message);
    }
  };

  return (
    <FullCalendar
      plugins={[dayGridPlugin, interactionPlugin]} // tanpa timeGrid: jadwal hanya punya tanggal
      initialView="dayGridMonth"
      headerToolbar={{ left: 'prev,next today', center: 'title', right: 'dayGridDay,dayGridWeek,dayGridMonth' }}
      buttonText={{ today: t('Hari ini'), day: t('Harian'), week: t('Mingguan'), month: t('Bulanan') }}
      locale={currentLang() === 'en' ? 'en' : 'id'} firstDay={1} height="auto" dayMaxEvents={4}
      events={events}
      eventDurationEditable={false}
      eventDrop={onDrop}
      eventClick={(info) => onSelect(Number(info.event.id))}
    />
  );
}
