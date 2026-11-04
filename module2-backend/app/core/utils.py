import html
import ipaddress
import math
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request

# Inclusive bounding box covering mainland Singapore and nearby coastal waters.
SG_LAT_MIN, SG_LAT_MAX = 1.15, 1.48
SG_LNG_MIN, SG_LNG_MAX = 103.60, 104.12

# Representative Singapore allocations (NTU/NUS/Singtel/StarHub/M1/etc.).
# Unknown public IPs are treated as outside Singapore.
_SG_NETWORKS = [
    ipaddress.ip_network(cidr)
    for cidr in (
        "27.104.0.0/15",
        "42.60.0.0/15",
        "58.182.0.0/16",
        "101.78.0.0/16",
        "103.12.0.0/16",
        "103.224.0.0/16",
        "116.14.0.0/15",
        "119.74.0.0/16",
        "121.6.0.0/16",
        "137.132.0.0/16",  # NUS
        "155.69.0.0/16",   # NTU
        "165.21.0.0/16",
        "180.179.0.0/16",
        "202.156.0.0/16",
        "202.166.0.0/16",
        "203.116.0.0/16",
        "203.117.0.0/16",
        "218.186.0.0/16",
        "219.75.0.0/16",
    )
]

_TAG_RE = re.compile(r"<[^>]*>")


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def sanitize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = _TAG_RE.sub("", value)
    return html.escape(stripped, quote=False).strip()


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_in_singapore(lat: float, lng: float) -> bool:
    return SG_LAT_MIN <= lat <= SG_LAT_MAX and SG_LNG_MIN <= lng <= SG_LNG_MAX


def _parse_ip(raw: str) -> Optional[str]:
    token = raw.strip().strip("[]")
    if ":" in token and token.count(":") == 1:
        host, _port = token.rsplit(":", 1)
        if host.count(".") == 3:
            token = host
    try:
        return str(ipaddress.ip_address(token))
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0]
        parsed = _parse_ip(first)
        if parsed:
            return parsed
    if request.client and request.client.host:
        parsed = _parse_ip(request.client.host)
        if parsed:
            return parsed
    return "127.0.0.1"


def is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
    )


def is_singapore_ip(ip: str) -> bool:
    if is_private_ip(ip):
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return any(addr in net for net in _SG_NETWORKS)


def singapore_checkin_allowed(ip: str, lat: Optional[float], lng: Optional[float]) -> bool:
    if not is_singapore_ip(ip):
        return False
    if lat is not None and lng is not None and not is_in_singapore(lat, lng):
        return False
    return True
