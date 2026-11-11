"""Montos en letras, en pesos y centavos. Sin dependencias."""
from decimal import Decimal, ROUND_HALF_UP

_UN = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
       "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho",
       "diecinueve", "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro",
       "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
_DEC = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}
_CEN = {1: "ciento", 2: "doscientos", 3: "trescientos", 4: "cuatrocientos", 5: "quinientos",
        6: "seiscientos", 7: "setecientos", 8: "ochocientos", 9: "novecientos"}


def _apocope(t):
    if t.endswith("veintiuno"):
        return t[:-9] + "veintiún"
    if t.endswith("uno"):
        return t[:-1]
    return t


def _hasta999(n):
    if n == 100:
        return "cien"
    c, r = divmod(n, 100)
    partes = [_CEN[c]] if c else []
    if r:
        if r < 30:
            partes.append(_UN[r])
        else:
            d, u = divmod(r, 10)
            partes.append(_DEC[d] + (f" y {_UN[u]}" if u else ""))
    return " ".join(partes)


def _entero(n):
    if n == 0:
        return "cero"
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1000)
    partes = []
    if millones:
        partes.append("un millón" if millones == 1 else _apocope(_entero(millones)) + " millones")
    if miles:
        partes.append("mil" if miles == 1 else _apocope(_hasta999(miles)) + " mil")
    if unidades:
        partes.append(_hasta999(unidades))
    return " ".join(partes)


def monto_en_letras(valor: Decimal) -> str:
    """Decimal('1234567.89') -> 'un millón doscientos treinta y cuatro mil quinientos sesenta y siete
    pesos con ochenta y nueve centavos'."""
    d = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if d < 0:
        raise ValueError("monto negativo")
    enteros, centavos = divmod(int(d * 100), 100)
    if enteros == 1:
        pesos = "un peso"
    elif enteros and enteros % 1_000_000 == 0:
        pesos = _entero(enteros) + " de pesos"
    else:
        pesos = _apocope(_entero(enteros)) + " pesos"
    cents = "un centavo" if centavos == 1 else f"{_apocope(_entero(centavos))} centavos"
    return f"{pesos} con {cents}"
