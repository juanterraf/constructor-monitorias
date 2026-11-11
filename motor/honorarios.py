r"""Honorarios, Ley 5.480. Port exacto de C:\dev\monitorias\src\lib\honorarios\calc.ts.

Fórmula: base x (50 % si hay reducción, art. 38) x (% art. 14) x multiplicador (1,55),
con un mínimo opcional (consulta escrita del C.A.T.). Sin IA, con Decimal.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

CENTAVO = Decimal("0.01")


def parse_monto(s) -> Decimal:
    """Texto o número a Decimal. Acepta "458.320,50", "$ 1.000.000" y "12345.67". Vacío da 0."""
    if isinstance(s, Decimal):
        return s
    if isinstance(s, (int, float)):
        return Decimal(str(s))
    t = re.sub(r"[^\d.,]", "", str(s if s is not None else ""))
    if not t:
        return Decimal(0)
    if "." in t and "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif "." in t:
        partes = t.split(".")
        if len(partes) > 2 or len(partes[-1]) == 3:
            t = "".join(partes)
    try:
        return Decimal(t)
    except Exception:
        return Decimal(0)


def fmt_ars(n) -> str:
    """1234567.8 -> '$1.234.567,80' (formato es-AR)."""
    d = Decimal(str(n or 0)).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return "$" + f"{d:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def calcular(base, reduccion=True, pct_art14=16, multiplicador=1.55, minimo_cat=None) -> dict:
    """Devuelve {base, calculado, minimo, final, aplica_minimo} (Decimal, a centavos)."""
    b = parse_monto(base)
    pct = Decimal(str(16 if pct_art14 is None else pct_art14))
    mult = Decimal(str(1.55 if multiplicador is None else multiplicador))
    calculado = b * (Decimal("0.5") if reduccion else Decimal(1)) * (pct / 100) * mult
    minimo = parse_monto(minimo_cat if minimo_cat is not None else 0)
    final = max(calculado, minimo or Decimal(0))
    q = lambda x: x.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return {
        "base": q(b),
        "calculado": q(calculado),
        "minimo": q(minimo),
        "final": q(final),
        "aplica_minimo": minimo > 0 and calculado < minimo,
    }
