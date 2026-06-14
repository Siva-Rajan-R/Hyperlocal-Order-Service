def format_ui_id(prefix: str, start_from: int, postgres_ui_id: int) -> str:
    """
    Combines the user-configured prefix and start_from with the postgres auto-increment.
    e.g. format_ui_id("PUR", 1, 5) -> "PUR-0005"
    e.g. format_ui_id("PUR", 100, 5) -> "PUR-0104"
    """
    p = f"{prefix}-" if prefix else ""
    sequence_num = (postgres_ui_id - 1) + start_from
    s = str(sequence_num).zfill(4)
    return f"{p}{s}"
