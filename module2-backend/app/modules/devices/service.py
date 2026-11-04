from typing import Any

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.repository import append_audit
from app.core.exceptions import bad_request, forbidden, not_found
from app.core.pagination import page_of
from app.core.utils import utcnow_naive
from app.db.enums import AuditAction, UserRole
from app.modules.devices import repository as devices_repo
from app.modules.devices.model import Device
from app.modules.devices.schemas import DeviceRegister, DeviceUpdate
from app.modules.users.model import User


def _to_device_dict(device: Device) -> dict[str, Any]:
    return {
        "id": device.id,
        "device_fingerprint": device.device_fingerprint,
        "device_name": device.device_name,
        "platform": device.platform,
        "browser": device.browser,
        "is_trusted": device.is_trusted,
        "trust_score": device.trust_score,
        "is_active": device.is_active,
        "first_seen_at": device.first_seen_at,
        "last_seen_at": device.last_seen_at,
        "total_checkins": device.total_checkins,
    }


def register_device(db: Session, payload: DeviceRegister, current_user: User, request: Request) -> dict[str, Any]:
    existing = devices_repo.get_by_fingerprint(db, payload.device_fingerprint)
    if existing is not None:
        if existing.user_id != current_user.id:
            raise bad_request("Device fingerprint already registered")
        existing.device_name = payload.device_name if payload.device_name is not None else existing.device_name
        existing.platform = payload.platform if payload.platform is not None else existing.platform
        existing.browser = payload.browser if payload.browser is not None else existing.browser
        if payload.public_key:
            existing.public_key = payload.public_key
        devices_repo.save(db, existing)
        db.commit()
        db.refresh(existing)
        return _to_device_dict(existing)

    device = Device(
        user_id=current_user.id,
        device_fingerprint=payload.device_fingerprint,
        device_name=payload.device_name,
        platform=payload.platform,
        browser=payload.browser,
        os_version=payload.os_version,
        app_version=payload.app_version,
        public_key=payload.public_key or "unspecified",
        public_key_created_at=utcnow_naive(),
        is_trusted=False,
        trust_score="low",
        is_active=True,
    )
    try:
        devices_repo.create(db, device)
        append_audit(
            db,
            AuditAction.DEVICE_REGISTERED.value,
            user_id=current_user.id,
            resource_type="device",
            resource_id=device.id,
            request=request,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise bad_request("Device fingerprint already registered")
    db.refresh(device)
    return _to_device_dict(device)


def my_devices(db: Session, current_user: User) -> Any:
    rows = devices_repo.list_for_user(db, current_user.id, active_only=False)
    return [_to_device_dict(row) for row in rows]


def list_all_devices(db: Session, *, limit: int, offset: int) -> dict[str, Any]:
    items, total, limit, offset = devices_repo.list_all(db, limit=limit, offset=offset)
    return page_of([_to_device_dict(row) for row in items], total, limit, offset)


def update_device(
    db: Session, device_id: str, payload: DeviceUpdate, current_user: User, request: Request
) -> dict[str, Any]:
    device = devices_repo.get_by_id(db, device_id)
    if device is None:
        raise not_found("Device not found")
    is_admin = current_user.role == UserRole.ADMIN.value
    is_owner = device.user_id == current_user.id
    if not is_admin and not is_owner:
        raise forbidden()
    data = payload.model_dump(exclude_unset=True)
    if "is_trusted" in data and not is_admin:
        raise forbidden()
    if "device_name" in data:
        device.device_name = data["device_name"]
    if "is_active" in data:
        device.is_active = data["is_active"]
        if data["is_active"] is False:
            device.revoked_at = utcnow_naive()
    if is_admin and "is_trusted" in data:
        device.is_trusted = data["is_trusted"]
        if data["is_trusted"]:
            device.trust_score = "high"
    devices_repo.save(db, device)
    db.commit()
    db.refresh(device)
    return _to_device_dict(device)


def remove_device(db: Session, device_id: str, current_user: User, request: Request) -> None:
    device = devices_repo.get_by_id(db, device_id)
    if device is None:
        raise not_found("Device not found")
    is_admin = current_user.role == UserRole.ADMIN.value
    if not is_admin and device.user_id != current_user.id:
        raise forbidden()
    device.is_active = False
    device.revoked_at = utcnow_naive()
    devices_repo.save(db, device)
    db.commit()
