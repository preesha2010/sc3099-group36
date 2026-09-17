from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.exceptions import not_implemented
from app.modules.devices.schemas import DeviceRegister, DeviceUpdate
from app.modules.users.model import User


def register_device(db: Session, payload: DeviceRegister, current_user: User, request: Request) -> dict[str, Any]:
    # TODO: Persist device (API spec + test_list_my_devices fixture POST /devices/register).
    not_implemented("POST /devices/register")


def my_devices(db: Session, current_user: User) -> Any:
    # TODO: Return JSON list of current user's devices (API spec + test_list_my_devices).
    not_implemented("GET /devices/my-devices")


def update_device(
    db: Session, device_id: str, payload: DeviceUpdate, current_user: User, request: Request
) -> dict[str, Any]:
    # TODO: Owner name / admin trust updates (API spec PATCH /devices/{id}).
    not_implemented("PATCH /devices/{device_id}")


def remove_device(db: Session, device_id: str, current_user: User, request: Request) -> None:
    # TODO: Owner or admin remove device (API spec DELETE /devices/{id} → 204).
    not_implemented("DELETE /devices/{device_id}")
