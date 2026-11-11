"""Cotejo de la demanda frente a la boleta, campo por campo. Sin IA.

cotejar(campos) -> [{"campo", "demanda", "boleta", "resultado": COINCIDE|DIFIERE|FALTA, "detalle"}]

`campos` es el dict del caso: {"demanda.monto_capital": {"valor": "123.45", ...}, ...}.
Se aceptan también valores planos ({"demanda.x": "..."}).
"""
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal

from .honorarios import parse_monto

COINCIDE, DIFIERE, FALTA = "COINCIDE", "DIFIERE", "FALTA"

# (campo, tipo de comparación)
CAMPOS_COTEJO = [
    ("ejecutante", "entidad"),
    ("ejecutado_nombre", "nombre"),
    ("ejecutado_documento", "cuit"),
    ("ejecutado_domicilio", "domicilio"),
    ("concepto", "texto"),
    ("periodos", "periodos"),
    ("boleta_numero", "numero"),
    ("boleta_fecha", "fecha"),
    ("monto_capital", "monto"),
    ("monto_total", "monto"),
]

_RELLENO_NOMBRE = {"de", "del", "la", "las", "los", "el", "y"}
# En una razón social, las siglas societarias (S.A.P.E.M., S.R.L.) se leen letra por letra.
_RELLENO_ENTIDAD = _RELLENO_NOMBRE | {"s", "a", "p", "e", "m", "r", "l", "sa", "sapem", "srl"}
_RELLENO_DOMICILIO = {"n", "nro", "no", "numero", "de", "del", "la", "las", "los", "el", "y", "calle", "av",
                      "avenida", "b", "barrio", "bo", "s", "piso", "dpto", "depto", "departamento"}


def sin_tildes(s) -> str:
    t = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def palabras(s, relleno=frozenset()) -> list:
    t = sin_tildes(s).lower()
    return [w for w in re.findall(r"[a-z0-9ñ]+", t) if w not in relleno]


def solo_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def valor_de(campos, nombre):
    """Valor elegido de un campo, o None si no hay / está vacío."""
    c = (campos or {}).get(nombre)
    v = c.get("valor") if isinstance(c, dict) else c
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    if isinstance(v, (list, tuple, set)) and not v:
        return None
    return v


def parse_fecha(s):
    """'2026-03-05' o '05/03/2026' -> date; si no se puede, None."""
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    t = str(s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", t)
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", t)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        pass
    return None


def parse_periodo(s):
    """'2025-01', '01/2025', '2025/01' -> '2025-01'; si no, None."""
    t = str(s or "").strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})$", t)
    if m:
        a, mes = int(m[1]), int(m[2])
    else:
        m = re.match(r"^(\d{1,2})[-/](\d{4})$", t)
        if not m:
            return None
        mes, a = int(m[1]), int(m[2])
    return f"{a:04d}-{mes:02d}" if 1 <= mes <= 12 else None


def parse_periodos(v) -> list:
    """Lista (o texto separado por comas/;) a lista ordenada de 'AAAA-MM' sin repetir."""
    if v is None:
        return []
    items = v if isinstance(v, (list, tuple, set)) else re.split(r"[;,]", str(v))
    out = {parse_periodo(i) or str(i).strip() for i in items if str(i).strip()}
    return sorted(out)


def _fila(campo, d, b, resultado, detalle):
    return {"campo": campo, "demanda": d, "boleta": b, "resultado": resultado, "detalle": detalle}


def _cmp_nombre(d, b, relleno=_RELLENO_NOMBRE):
    pd_, pb = set(palabras(d, relleno)), set(palabras(b, relleno))
    if pd_ == pb:
        return COINCIDE, "Mismas palabras (sin tildes, mayúsculas ni orden)."
    solo_d, solo_b = sorted(pd_ - pb), sorted(pb - pd_)
    return DIFIERE, f"Solo en demanda: {', '.join(solo_d) or '-'}. Solo en boleta: {', '.join(solo_b) or '-'}."


def _cmp_entidad(d, b):
    """Ejecutante: coincide si las palabras de una denominación están contenidas en la otra
    (la demanda puede decir 'SAT' completo o abreviado)."""
    pd_, pb = set(palabras(d, _RELLENO_ENTIDAD)), set(palabras(b, _RELLENO_ENTIDAD))
    if pd_ == pb or pd_ <= pb or pb <= pd_:
        return COINCIDE, "Denominación coincidente (una contiene a la otra)."
    return DIFIERE, f"Solo en demanda: {', '.join(sorted(pd_ - pb)) or '-'}. Solo en boleta: {', '.join(sorted(pb - pd_)) or '-'}."


def _cmp_cuit(d, b):
    dd, db = solo_digitos(d), solo_digitos(b)
    if dd == db:
        return COINCIDE, "Mismos dígitos."
    return DIFIERE, f"Demanda {dd or '-'} frente a boleta {db or '-'}."


def _cmp_domicilio(d, b):
    td, tb = palabras(d, _RELLENO_DOMICILIO), palabras(b, _RELLENO_DOMICILIO)
    nd, nb = {w for w in td if w.isdigit()}, {w for w in tb if w.isdigit()}
    wd, wb = {w for w in td if not w.isdigit()}, {w for w in tb if not w.isdigit()}
    menor = min(len(wd), len(wb))
    comunes = len(wd & wb)
    ratio = (comunes / menor) if menor else (1.0 if not (wd or wb) else 0.0)
    if nd == nb and ratio >= 0.8:
        return COINCIDE, f"Coincidencia de palabras {comunes}/{menor}; mismos números."
    return DIFIERE, (f"Coincidencia de palabras {comunes}/{menor}. Números solo en demanda: "
                     f"{', '.join(sorted(nd - nb)) or '-'}; solo en boleta: {', '.join(sorted(nb - nd)) or '-'}. "
                     f"Palabras solo en demanda: {', '.join(sorted(wd - wb)) or '-'}; solo en boleta: {', '.join(sorted(wb - wd)) or '-'}.")


def _cmp_texto(d, b):
    nd, nb = " ".join(str(d).split()).casefold(), " ".join(str(b).split()).casefold()
    return (COINCIDE, "Textos iguales.") if nd == nb else (DIFIERE, "Los textos no son iguales.")


def _cmp_numero(d, b):
    return (COINCIDE, "Mismo número.") if str(d).strip() == str(b).strip() else (DIFIERE, f"Demanda {str(d).strip()} frente a boleta {str(b).strip()}.")


def _cmp_fecha(d, b):
    fd, fb = parse_fecha(d), parse_fecha(b)
    if fd is None or fb is None:
        return DIFIERE, "No se pudo leer alguna de las fechas."
    return (COINCIDE, "Misma fecha.") if fd == fb else (DIFIERE, f"Demanda {fd.isoformat()} frente a boleta {fb.isoformat()}.")


def _cmp_monto(d, b):
    md, mb = parse_monto(d), parse_monto(b)
    if md == mb:
        return COINCIDE, "Mismo monto."
    dif = md - mb
    quien = "la demanda reclama más" if dif > 0 else "la boleta indica más"
    return DIFIERE, f"Diferencia de {abs(dif):.2f} ({quien})."


def _cmp_periodos(d, b):
    sd, sb = set(parse_periodos(d)), set(parse_periodos(b))
    if sd == sb:
        return COINCIDE, "Mismo conjunto de períodos."
    return DIFIERE, f"Solo en demanda: {', '.join(sorted(sd - sb)) or '-'}. Solo en boleta: {', '.join(sorted(sb - sd)) or '-'}."


_COMPARADORES = {
    "entidad": _cmp_entidad, "nombre": _cmp_nombre, "cuit": _cmp_cuit, "domicilio": _cmp_domicilio,
    "texto": _cmp_texto, "numero": _cmp_numero, "fecha": _cmp_fecha, "monto": _cmp_monto,
    "periodos": _cmp_periodos,
}


def cotejar(campos) -> list:
    filas = []
    for campo, tipo in CAMPOS_COTEJO:
        d = valor_de(campos, f"demanda.{campo}")
        b = valor_de(campos, f"boleta.{campo}")
        if d is None or b is None:
            falta = [lado for lado, v in (("demanda", d), ("boleta", b)) if v is None]
            filas.append(_fila(campo, d, b, FALTA, "Falta el dato en: " + " y ".join(falta) + "."))
            continue
        res, det = _COMPARADORES[tipo](d, b)
        filas.append(_fila(campo, d, b, res, det))
    return filas
