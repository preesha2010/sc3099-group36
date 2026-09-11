from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.exceptions import not_implemented
from app.modules.devices.schemas import DeviceRegister, DeviceUpdate
from app.modules.users.model import User


def register_device(db: Session, payload: DeviceRegister, current_user: User, request: Request) -> dict[str, Any]:
    not_implemented("POST /devices/register")


def my_devices(db: Session, current_user: User) -> Any:
    not_implemented("GET /devices/my-devices")


def update_device(
    db: Session, device_id: str, payload: DeviceUpdate, current_user: User, request: Request
) -> dict[str, Any]:
    not_implemented("PATCH /devices/{device_id}")


def remove_device(db: Session, device_id: str, current_user: User, request: Request) -> None:
    not_implemented("DELETE /devices/{device_id}")
