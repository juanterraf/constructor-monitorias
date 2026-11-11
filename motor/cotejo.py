"""Cotejo de la demanda frente a la boleta, campo por campo. Sin IA.

cotejar(campos) -> [{"campo", "demanda", "boleta", "resultado": COINCIDE|DIFIERE|FALTA|SOLO BOLETA, "detalle"}]

`campos` es el dict del caso: {"demanda.monto_capital": {"valor": "123.45", ...}, ...}.
Se aceptan también valores planos ({"demanda.x": "..."}).
"""
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal

from . import organismos
from .honorarios import parse_monto

COINCIDE, DIFIERE, FALTA = "COINCIDE", "DIFIERE", "FALTA"
# La demanda no trae el dato y la boleta sí: no bloquea. FALTA queda para cuando falta en la boleta (el título).
SOLO_BOLETA = "SOLO BOLETA"
_PREFIJOS_CUIT = {"20", "23", "24", "25", "26", "27", "30", "33", "34"}

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


def cuit_valido(digitos) -> bool:
    """CUIT/CUIL de 11 dígitos: prefijo habitual y dígito verificador (módulo 11)."""
    d = solo_digitos(digitos)
    if len(d) != 11 or d[:2] not in _PREFIJOS_CUIT:
        return False
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    r = 11 - sum(int(a) * b for a, b in zip(d[:10], pesos)) % 11
    return {11: 0, 10: 9}.get(r, r) == int(d[10])


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
    """Ejecutante: se compara por organismo canónico (SAT, DGR o MUNICIPALIDAD y su municipio), no por texto.
    Si alguna denominación no se reconoce, coincide si las palabras de una contienen a las de la otra."""
    (od, md), (ob, mb) = organismos.organismo_y_municipio(d), organismos.organismo_y_municipio(b)
    if od and ob:
        if od != ob:
            return DIFIERE, f"Organismo en demanda: {od}; en boleta: {ob}."
        if od == organismos.MUNICIPALIDAD:
            wd, wb = set(palabras(md, _RELLENO_NOMBRE)), set(palabras(mb, _RELLENO_NOMBRE))
            if not (wd <= wb or wb <= wd):
                return DIFIERE, f"Municipio en demanda: {md}; en boleta: {mb}."
            return COINCIDE, f"Mismo organismo ({od}) y mismo municipio."
        return COINCIDE, f"Mismo organismo ({od})."
    pd_, pb = set(palabras(d, _RELLENO_ENTIDAD)), set(palabras(b, _RELLENO_ENTIDAD))
    if pd_ == pb or pd_ <= pb or pb <= pd_:
        return COINCIDE, "Denominación coincidente (una contiene a la otra)."
    return DIFIERE, f"Solo en demanda: {', '.join(sorted(pd_ - pb)) or '-'}. Solo en boleta: {', '.join(sorted(pb - pd_)) or '-'}."


def _cmp_cuit(d, b):
    dd, db = solo_digitos(d), solo_digitos(b)
    aviso = " ".join(f"El {lado} {x} no pasa el dígito verificador (puede figurar así en el padrón)."
                     for lado, x in (("de la demanda", dd), ("de la boleta", db)) if len(x) == 11 and not cuit_valido(x))
    if dd == db:
        return COINCIDE, ("Mismos dígitos. " + aviso).strip()
    # Un DNI frente a un CUIT o CUIL: coincide si es igual a los 8 dígitos centrales
    for dni, cuit, lado in ((dd, db, "boleta"), (db, dd, "demanda")):
        if 7 <= len(dni) <= 8 and len(cuit) == 11 and dni.zfill(8) == cuit[2:10]:
            return COINCIDE, (f"El DNI es igual a los 8 dígitos centrales del CUIT/CUIL de la {lado}. " + aviso).strip()
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
        if d is None and b is not None:
            filas.append(_fila(campo, d, b, SOLO_BOLETA, "La demanda no trae el dato; consta en la boleta."))
            continue
        if b is None:
            falta = [lado for lado, v in (("demanda", d), ("boleta", b)) if v is None]
            filas.append(_fila(campo, d, b, FALTA, "Falta el dato en: " + " y ".join(falta) + "."))
            continue
        res, det = _COMPARADORES[tipo](d, b)
        if campo == "monto_capital" and res == DIFIERE:
            tot = valor_de(campos, "boleta.monto_total")
            if tot is not None and parse_monto(d) == parse_monto(tot):
                res, det = COINCIDE, "La demanda reclama como capital el total de la boleta (capital más intereses)."
        filas.append(_fila(campo, d, b, res, det))
    return filas
