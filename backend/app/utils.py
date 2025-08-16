def hex_to_rgba(hex_str: str, alpha: float) -> str:
    hex_str = hex_str.lstrip("#")
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.2f})"
