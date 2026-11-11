"""Patrones propios de cada organismo: SAT, Municipalidad y DGR.

Todo trabaja sobre texto «plano»: minúsculas y sin tildes (ver detectar._plano).
"""
from __future__ import annotations

import re
import unicodedata

SAT = "SAT"
MUNICIPALIDAD = "MUNICIPALIDAD"
DGR = "DGR"

# Marcadores que, en una página de demanda o de boleta, delatan al organismo.
MARCADORES = {
    SAT: [r"aguas del tucum", r"\bsat\s*sapem\b", r"adeuda a aguas"],
    DGR: [r"direccion general de rentas", r"\bd\.?\s?g\.?\s?r\.?\b", r"cargo tributario",
          r"division control de cobros", r"titulos ejecutivos"],
    MUNICIPALIDAD: [r"municipalidad de [a-z]", r"direccion de ingresos municipales",
                    r"\bd\.i\.m\b", r"fiscal municipal"],
}

# Concepto fijo cuando el organismo y el texto lo dejan claro.
CONCEPTO_SAT = "Servicio de agua potable y desagües cloacales"
PAT_CONCEPTO_SAT = r"agua potable|desag[uü]es cloacales|efluentes cloacales"

# Abreviaturas de municipios para completar nombres.
ABREV_MUNICIPIO = {
    "s.m. de tucuman": "San Miguel de Tucumán",
    "s. m. de tucuman": "San Miguel de Tucumán",
    "sm de tucuman": "San Miguel de Tucumán",
    "s.m.t.": "San Miguel de Tucumán",
}

NOMBRES_CANONICOS = {SAT: "SAT", DGR: "DGR"}

# CUIT de los ejecutantes (solo dígitos) -> organismo. Figuran en sus demandas y boletas;
# nunca son el documento del ejecutado.
CUIT_EJECUTANTES = {"30708617888": SAT}  # 30-70861788-8

# Palabras que delatan que un «nombre» es en realidad el ejecutante o una repartición.
PALABRAS_ENTIDAD = (
    "aguas del tucum", "municipalidad", "direccion general", "rentas", "d.g.r",
    "direccion de ingresos", "sat sapem", "gobierno de la provincia",
)


def canon_ejecutante(texto_plano: str, texto_orig: str = "") -> tuple[str | None, str | None]:
    """(nombre canónico, organismo) a partir de un texto que nombra al ejecutante."""
    p = texto_plano
    if re.search(r"aguas del tucum|adeuda a aguas|\bsat\b", p):
        return "SAT", SAT
    m = re.search(r"municipalidad de ([a-z0-9\.\s]{3,50}?)(?=\s*(?:c/|,|\.|\(|cuit|con domicilio|adeuda|\bs/|-|$))", p)
    if m:
        nombre = (texto_orig or p)[m.start(1):m.end(1)] if texto_orig and len(texto_orig) == len(p) else m.group(1)
        nombre = " ".join(nombre.split()).strip(" .,-")
        clave = nombre.lower()
        for ab, full in ABREV_MUNICIPIO.items():
            if clave == ab or clave.startswith(ab):
                nombre = full
        if nombre.isupper():
            nombre = _titulo(nombre)
        return f"Municipalidad de {nombre}", MUNICIPALIDAD
    if re.search(r"rentas|\bd\.?\s?g\.?\s?r\.?\b|provincia de tucuman", p):
        return "DGR", DGR
    return None, None


def _titulo(s: str) -> str:
    part = {"de", "del", "la", "las", "los", "y"}
    pal = s.lower().split()
    return " ".join(w if (i and w in part) else w.capitalize() for i, w in enumerate(pal))


def organismo_y_municipio(texto: str) -> tuple[str | None, str | None]:
    """(organismo, municipio) de una denominación de ejecutante en texto libre; (None, None) si no se reconoce.
    El municipio solo se informa para MUNICIPALIDAD (en minúsculas y sin tildes)."""
    p = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn").lower()
    canon, o = canon_ejecutante(p, p)
    if o != MUNICIPALIDAD:
        return o, None
    return o, re.sub(r"^municipalidad de\s+", "", (canon or "").lower()).strip()
