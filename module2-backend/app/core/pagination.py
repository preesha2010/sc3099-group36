from typing import Generic, List, Sequence, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """List envelope required by API-SPECIFICATION.md Pagination."""

    items: List[T]
    total: int
    limit: int
    offset: int


def clamp_page(limit: int, offset: int, *, default: int = 50, max_limit: int = 100) -> tuple[int, int]:
    if limit is None:
        limit = default
    limit = min(max(int(limit), 1), max_limit)
    offset = max(int(offset or 0), 0)
    return limit, offset


def page_of(items: Sequence[T], total: int, limit: int, offset: int) -> dict:
    return {"items": list(items), "total": total, "limit": limit, "offset": offset}
