def format_from_cover_type(cover_type: str | None) -> str | None:
    """Map Lithuanian cover-type labels to canonical format tokens."""
    if not cover_type:
        return None
    lower = cover_type.lower()
    if "kiet" in lower:
        return "hardcover"
    if "minkšt" in lower:
        return "paperback"
    return lower  # no canonical mapping — preserve raw label rather than dropping
