from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.core.utils import utcnow_naive
from app.modules.devices.model import Device


def get_by_id(db: Session, device_id: str) -> Optional[Device]:
    return db.query(Device).filter(Device.id == device_id).first()


def get_by_fingerprint(db: Session, fingerprint: str) -> Optional[Device]:
    return db.query(Device).filter(Device.device_fingerprint == fingerprint).first()


def list_for_user(db: Session, user_id: str, *, active_only: bool = False) -> Sequence[Device]:
    query = db.query(Device).filter(Device.user_id == user_id)
    if active_only:
        query = query.filter(Device.is_active.is_(True))
    return query.order_by(Device.last_seen_at.desc()).all()


def create(db: Session, device: Device) -> Device:
    db.add(device)
    db.flush()
    return device


def save(db: Session, device: Device) -> Device:
    device.last_seen_at = utcnow_naive()
    db.add(device)
    db.flush()
    return device
