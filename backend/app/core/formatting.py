"""Brazilian (pt-BR) number and date formatting.

The frontend has its own Intl-based formatter; this module is used for
exports (Excel/PDF) and log messages so both sides render the same way.
"""
from datetime import date
from decimal import Decimal

MISSING = "—"


def _group(int_part: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return ".".join(out)


def fmt_number(value: float | Decimal | None, decimals: int = 2) -> str:
    if value is None:
        return MISSING
    q = f"{abs(Decimal(str(value))):.{decimals}f}"
    int_part, _, frac = q.partition(".")
    sign = "-" if Decimal(str(value)) < 0 and Decimal(q) != 0 else ""
    return sign + _group(int_part) + ("," + frac if decimals else "")


def fmt_brl(value: float | Decimal | None, decimals: int = 2) -> str:
    if value is None:
        return MISSING
    s = fmt_number(value, decimals)
    if s.startswith("-"):
        return "-R$ " + s[1:]
    return "R$ " + s


def fmt_pct(fraction: float | Decimal | None, decimals: int = 2) -> str:
    """Format a fraction (0.0962) as a percentage ('9,62%')."""
    if fraction is None:
        return MISSING
    return fmt_number(Decimal(str(fraction)) * 100, decimals) + "%"


def fmt_date(d: date | None) -> str:
    return MISSING if d is None else d.strftime("%d/%m/%Y")


def parse_br_number(text: str) -> Decimal | None:
    """Parse '38.832.448,68', 'R$ 95,52', '7,57%' -> Decimal. Returns None for '-' / '—' / ''."""
    t = text.strip().replace("R$", "").replace("%", "").replace("\u00a0", "").strip()
    if t in {"", "-", "—", "–"}:
        return None
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-() ")
    t = t.replace(".", "").replace(",", ".")
    d = Decimal(t)
    return -d if neg else d
