from typing import Optional

from pydantic import BaseModel

from app.core.schemas import OptionalSanitizedStr


class DeviceRegister(BaseModel):
    device_fingerprint: str
    device_name: OptionalSanitizedStr = None
    platform: Optional[str] = None
    browser: Optional[str] = None
    public_key: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None


class DeviceUpdate(BaseModel):
    device_name: OptionalSanitizedStr = None
    is_trusted: Optional[bool] = None
    is_active: Optional[bool] = None
