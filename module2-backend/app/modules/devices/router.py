from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.modules.devices import service
from app.modules.devices.schemas import DeviceRegister, DeviceUpdate
from app.modules.users.model import User

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_device(
    payload: DeviceRegister,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.register_device(db, payload, current_user, request)


@router.get("/my-devices")
def my_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.my_devices(db, current_user)


@router.patch("/{device_id}")
def update_device(
    device_id: str,
    payload: DeviceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.update_device(db, device_id, payload, current_user, request)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_device(
    device_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service.remove_device(db, device_id, current_user, request)
