from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.models import Schedule
from app.models.enums import ScheduleStatus
from app.schemas.schedule import (ScheduleCreate, ScheduleMaterialsOut, ScheduleOut,
                                  ScheduleStatusUpdate, ScheduleUpdate)
from app.services import schedule_service as svc

router = APIRouter()


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(body: ScheduleCreate, db: Session = Depends(get_db)):
    """Buat jadwal (batch). 422 bila produk bukan Produk Final atau BOM tidak lengkap / mengandung siklus."""
    return svc.create_schedule(db, body.product_id, body.production_date, body.target_qty,
                               body.production_line_id)


@router.get("", response_model=list[ScheduleOut])
def list_schedules(date_from: date | None = None, date_to: date | None = None,
                   status: ScheduleStatus | None = None, production_line_id: int | None = None,
                   db: Session = Depends(get_db)):
    # produk & line dimuat sekaligus (bukan 2 query per jadwal; tiap round trip ~140-200 ms di SAP BTP)
    stmt = select(Schedule).order_by(Schedule.production_date, Schedule.id).options(
        selectinload(Schedule.product), selectinload(Schedule.line))
    if date_from is not None:
        stmt = stmt.where(Schedule.production_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Schedule.production_date <= date_to)
    if status is not None:
        stmt = stmt.where(Schedule.status == status)
    if production_line_id is not None:
        stmt = stmt.where(Schedule.production_line_id == production_line_id)
    return list(db.scalars(stmt))


@router.patch("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: int, body: ScheduleUpdate, db: Session = Depends(get_db)):
    """Edit/reschedule — hanya jadwal PLANNED (409 bila tidak). Status lewat /status."""
    s = svc.get_schedule(db, schedule_id)
    return svc.update_schedule(db, s, body.model_dump(exclude_unset=True))


@router.patch("/{schedule_id}/status", response_model=ScheduleOut)
def change_schedule_status(schedule_id: int, body: ScheduleStatusUpdate, db: Session = Depends(get_db)):
    """PLANNED→IN_PROGRESS (potong stok), IN_PROGRESS→COMPLETED, PLANNED→CANCELLED.
    409: transisi tidak valid atau stok fisik kurang (body memuat `shortages`)."""
    s = svc.get_schedule(db, schedule_id)
    return svc.change_status(db, s, ScheduleStatus(body.status))


@router.get("/{schedule_id}/materials", response_model=ScheduleMaterialsOut)
def schedule_materials(schedule_id: int, db: Session = Depends(get_db)):
    """Alokasi material batch. Status stok bersifat GLOBAL per material, bukan per batch."""
    return svc.materials_view(db, svc.get_schedule(db, schedule_id))


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT, deprecated=True)
def cancel_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """Alias PATCH /{id}/status CANCELLED (dipertahankan untuk kompatibilitas)."""
    svc.change_status(db, svc.get_schedule(db, schedule_id), ScheduleStatus.CANCELLED)
