"""Shared request/response shapes used across modules."""

from typing import Annotated, Optional

from pydantic import BaseModel, BeforeValidator, Field

from app.core.utils import sanitize_text


def _sanitize(value: Optional[str]) -> Optional[str]:
    return sanitize_text(value)


# User-authored text: strip HTML then escape. Request fields only.
SanitizedStr = Annotated[str, BeforeValidator(_sanitize)]
OptionalSanitizedStr = Annotated[Optional[str], BeforeValidator(_sanitize)]


class PaginationQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
