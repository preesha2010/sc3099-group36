from urllib.parse import urlparse


def is_shared_saiv_database(database_url: str) -> bool:
    """True only for PostgreSQL databases named `saiv` (the shared student DB)."""
    if not database_url:
        return False
    parsed = urlparse(database_url)
    scheme = (parsed.scheme or "").lower()
    if scheme.startswith("sqlite"):
        return False
    name = (parsed.path or "").lstrip("/").split("/")[0].split("?")[0]
    return name.lower() == "saiv"
