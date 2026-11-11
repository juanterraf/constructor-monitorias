"""Detección: tipo de cada página, organismo y candidatos de cada campo. Sin IA: regex y contexto."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal

from . import organismos as org

CAMPOS_DEMANDA = [
    "ejecutante", "letrado_nombre", "letrado_matricula", "ejecutado_nombre", "ejecutado_documento",
    "ejecutado_domicilio", "concepto", "periodos", "boleta_numero", "boleta_fecha",
    "monto_capital", "monto_total", "expediente_numero", "caratula",
]
CAMPOS_BOLETA = [
    "ejecutante", "ejecutado_nombre", "ejecutado_documento", "ejecutado_domicilio", "concepto",
    "periodos", "boleta_numero", "boleta_fecha", "monto_capital", "monto_total", "monto_intereses",
]
MAX_CANDIDATOS = 8

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
         "diciembre": 12}
_MES_RE = "|".join(MESES)


# ---------------------------------------------------------------- utilidades de texto

_TRAD = str.maketrans({" ": " ", "º": "°", "*": "°", "”": "°", "’": "°",
                       "‘": "'", "“": '"', "–": "-", "—": "-", "�": " "})


def _plano(t: str) -> str:
    """Minúsculas, sin tildes y con 'N°' unificado. Conserva el largo: los índices valen para el original."""
    salida = []
    for c in t:
        if c.isalpha():
            r = unicodedata.normalize("NFD", c)[0].lower()
            salida.append(r if len(r) == 1 else c)
        else:
            salida.append(c)
    p = "".join(salida).translate(_TRAD)
    # «N*», «N”», «N"» delante de un número: N°
    p = re.sub(r"(?<![a-z])n[\"°](?=\s?\d)", "n°", p)
    return p


def _lim(s: str, largo: int = 160) -> str:
    s = " ".join(s.split()).strip(" \t.,;:-=_|")
    return s[:largo]


def _cita(t: str, ini: int, fin: int, extra: int = 25, tope: int = 110) -> str:
    fin = min(fin, ini + tope)
    return " ".join(t[max(0, ini - extra): min(len(t), fin + extra)].split())


def cuit_valido(digitos: str) -> bool:
    d = re.sub(r"\D", "", digitos)
    if len(d) != 11 or d[:2] not in {"20", "23", "24", "25", "26", "27", "30", "33", "34"}:
        return False
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    r = 11 - sum(int(a) * b for a, b in zip(d[:10], pesos)) % 11
    dv = {11: 0, 10: 9}.get(r, r)
    return dv == int(d[10])


def parse_monto(token: str) -> str | None:
    """'$ 1.234,56' -> '1234.56'; '7,234.56' -> '7234.56'; '7.234.56' -> '7234.56'."""
    tok = re.sub(r"[^\d.,]", "", token).strip(".,")
    if not tok:
        return None
    m = re.search(r"[.,](\d{1,2})$", tok)
    if m:
        entera, dec = tok[:m.start()], m.group(1).ljust(2, "0")
    else:
        entera, dec = tok, "00"
    entera = re.sub(r"[.,]", "", entera).lstrip("0") or "0"
    if not entera.isdigit():
        return None
    return f"{entera}.{dec}"


_NUM = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"


def _fecha_iso(d: int, m: int, a: int) -> str | None:
    try:
        return date(a, m, d).isoformat()
    except ValueError:
        return None


def fechas_en(plano: str) -> list[tuple[str, int, int]]:
    """Fechas numéricas y en letras: [(AAAA-MM-DD, ini, fin)]."""
    res = []
    for m in re.finditer(r"(?<![\d/])(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?!\d)", plano):
        iso = _fecha_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            res.append((iso, m.start(), m.end()))
    for m in re.finditer(rf"(?<!\d)(\d{{1,2}})\s*(?:°\s*)?(?:de\s+)?({_MES_RE})\s*(?:de|del)?\s*(\d{{4}})(?!\d)", plano):
        iso = _fecha_iso(int(m.group(1)), MESES[m.group(2)], int(m.group(3)))
        if iso:
            res.append((iso, m.start(), m.end()))
    return sorted(res, key=lambda x: x[1])


def _expandir(m1: int, a1: int, m2: int, a2: int) -> list[str]:
    if not (1 <= m1 <= 12 and 1 <= m2 <= 12) or (a2, m2) < (a1, m1) or (a2 - a1) > 15:
        return []
    out, a, m = [], a1, m1
    while (a, m) <= (a2, m2):
        out.append(f"{a:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, a = 1, a + 1
    return out


def _emision_ym(plano: str) -> str | None:
    """'AAAA-MM' de «a los 06 días del mes de noviembre de 2025», o None."""
    m = re.search(rf"a\s+los\s+(\d{{1,2}})\s+d[i1]as\s+del\s+mes\s+de\s+({_MES_RE})\s*(?:de|del)?\s*(\d{{4}})", plano)
    return f"{int(m.group(3)):04d}-{MESES[m.group(2)]:02d}" if m else None


def periodos_en(plano: str) -> list[tuple[list[str], str, int, int, float]]:
    """[(períodos, regla, ini, fin, confianza base)]; los rangos ya vienen expandidos."""
    res: list[tuple[list[str], str, int, int, float]] = []
    ocupado: list[tuple[int, int]] = []

    def libre(s, e):
        return not any(s < e2 and e > s2 for s2, e2 in ocupado)

    def agregar(lista, regla, s, e, conf):
        if lista:
            res.append((lista, regla, s, e, conf))
            ocupado.append((s, e))

    # Tabla de la SAT: «Período 8° Mes/2022»
    tabla = [(m.start(), m.end(), int(m.group(1)), int(m.group(2))) for m in re.finditer(
        r"per[i1]odo\s*(\d{1,2})\S{0,2}\s*mes[\s/|lI!]{0,3}(20\d\d)", plano)]
    if len(tabla) >= 2:
        lista = [f"{a}-{m:02d}" for _, _, m, a in tabla if 1 <= m <= 12]
        agregar(lista, "periodos-tabla", tabla[0][0], tabla[-1][1], 0.9)
    else:
        # Tabla de la SAT leída por OCR: «01° Mes/2021», con la marca de orden deformada («11*», «06"»).
        # Los posteriores a la emisión de la boleta son errores de lectura (2031 por 2021): se descartan.
        emision = _emision_ym(plano)
        filas = [(m.start(), m.end(), int(m.group(1)), int(m.group(2))) for m in re.finditer(
            r"(?<![\d/])(\d{1,2})[°º*\"´'‘’]?\s*mes\s*/\s*(\d{4})(?!\d)", plano)]
        lista = sorted({f"{a:04d}-{m:02d}" for _, _, m, a in filas
                        if 1 <= m <= 12 and not (emision and f"{a:04d}-{m:02d}" > emision)})
        if lista:
            agregar(lista, "periodos-tabla-mes", filas[0][0], filas[-1][1], 0.85)
    # MM/AAAA a MM/AAAA
    for m in re.finditer(r"(?<![\d/])(\d{1,2})\s*/\s*(\d{4})\s*(?:a|al|hasta(?:\s+el)?|-)\s*(\d{1,2})\s*/\s*(\d{4})(?!\d)", plano):
        if libre(m.start(), m.end()):
            agregar(_expandir(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))),
                    "periodos-rango", m.start(), m.end(), 0.85)
    # «04 a 12/2021»
    for m in re.finditer(r"(?<![\d/])(\d{1,2})\s*(?:a|al|-)\s*(\d{1,2})\s*/\s*(\d{4})(?!\d)", plano):
        if libre(m.start(), m.end()):
            agregar(_expandir(int(m.group(1)), int(m.group(3)), int(m.group(2)), int(m.group(3))),
                    "periodos-rango", m.start(), m.end(), 0.8)
    # «enero de 2025 a marzo de 2025» y «enero a marzo de 2025»
    for m in re.finditer(rf"({_MES_RE})(?:\s*(?:de|del)\s*(\d{{4}}))?\s*(?:a|al|hasta|-)\s*({_MES_RE})\s*(?:de|del)\s*(\d{{4}})", plano):
        if libre(m.start(), m.end()):
            a2 = int(m.group(4))
            a1 = int(m.group(2)) if m.group(2) else a2
            agregar(_expandir(MESES[m.group(1)], a1, MESES[m.group(3)], a2), "periodos-rango-letras",
                    m.start(), m.end(), 0.8)
    # Cuotas municipales: «2019/005 C.I.S.I.»
    cuotas = [(m.start(), m.end(), f"{m.group(1)}-{int(m.group(2)):02d}") for m in re.finditer(
        r"(?m)^\s*(20\d\d)/0?(\d{2})\s?\d?\s+\S", plano) if 1 <= int(m.group(2)) <= 12]
    if len(cuotas) >= 2 and libre(cuotas[0][0], cuotas[-1][1]):
        agregar(sorted({c[2] for c in cuotas}), "periodos-cuotas", cuotas[0][0], cuotas[-1][1], 0.7)
    # Un mes suelto: «01/2025», «enero de 2025» (sin confundir con fechas completas)
    sueltos = []
    for m in re.finditer(r"(?<![\d/])(0?[1-9]|1[0-2])\s*/\s*(20\d\d|19\d\d)(?![\d/])", plano):
        if libre(m.start(), m.end()):
            sueltos.append((m.start(), m.end(), f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"))
    for m in re.finditer(rf"({_MES_RE})\s*(?:de|del)\s*(20\d\d|19\d\d)", plano):
        previo = plano[max(0, m.start() - 8): m.start()]
        # «a los 06 días del mes de noviembre de 2025» es la fecha de emisión, no un período
        if re.search(r"\d\s*(?:de\s*)?$", previo) or re.search(r"mes\s+de\s*$", previo) or not libre(m.start(), m.end()):
            continue
        sueltos.append((m.start(), m.end(), f"{int(m.group(2)):04d}-{MESES[m.group(1)]:02d}"))
    if sueltos:
        agregar(sorted({x[2] for x in sueltos}), "periodos-sueltos", min(x[0] for x in sueltos),
                max(x[1] for x in sueltos), 0.5)
    # Años fiscales: «períodos fiscales 2019, 2020 y 2022»
    for m in re.finditer(r"(?:periodos?|anos?|ejercicios?)\s+(?:fiscal(?:es)?\s+)?((?:(?:19|20)\d\d\s*(?:,|y|e)?\s*)+)", plano):
        anios = sorted(set(re.findall(r"(?:19|20)\d\d", m.group(1))))
        if anios and libre(m.start(), m.end()):
            agregar(anios, "periodos-anios", m.start(), m.end(), 0.4)
    return res


# ---------------------------------------------------------------- clasificación de páginas

_DEMANDA = ["senor juez", "senora juez", "sr. juez", "sr/a. juez", "a v.s", "respetuosamente",
            "proveer de conformidad", "sera justicia", "petitorio", "personeria", "promuevo demanda",
            "promueve demanda", "inicio juicio", "inicio demanda", "vengo a", "demanda de ejecucion",
            "intimacion de pago", "citacion de remate", "trance y remate", "formal demanda",
            "reserva de ampliar", "diferimiento", "se tenga presente", "me tenga por presentado",
            "costas", "mandamiento"]
_BOLETA_ENCABEZADO = ["boleta de deuda", "certificado de deuda", "cargo tributario", "liquidacion de deuda",
                      "division control de cobros", "direccion de ingresos municipales",
                      "titulo ejecutivo", "emision de titulos"]
_BOLETA_ESTRUCTURA = [r"adeuda a", r"total general de la deuda", r"totales generales", r"son pesos",
                      r"la mencionada deuda", r"certifico que el propietario", r"deudor\s*:",
                      r"contribuyente\s*:", r"deuda actualizada", r"per[i1]odo\s*\d{1,2}\S{0,2}\s*mes",
                      r"(?m)^\s*20\d\d/\d{3}\s", r"fact\.?\s*n", r"padron (?:municipal|catastral)",
                      r"por los conceptos que se detallan"]
_PODER = ["poder general", "poder especial", "escritura", "escribana", "escribano", "actuacion notarial",
          "comparece", "confiere", "registro notarial", "doy fe", "mandato", "poderdante"]


def _contar(plano: str, lista: list[str]) -> int:
    return sum(1 for k in lista if k in plano)


def _tipo_de(plano: str, util: int) -> tuple[str, int]:
    """Tipo y puntaje. 'sin_marcas' cuando no hay nada firme (se resuelve por continuidad)."""
    if util < 25:
        return "otro", 0
    d = _contar(plano, _DEMANDA)
    cabeza = plano[:350]
    enc = sum(1 for k in _BOLETA_ENCABEZADO if k in cabeza)
    est = sum(1 for k in _BOLETA_ESTRUCTURA if re.search(k, plano))
    b = est + (3 * enc)
    pod = _contar(plano, _PODER)
    if "resuelvo" in plano and ("vistos" in plano or "considerando" in plano):
        return "otro", 0
    if pod >= 4 and d < 4:
        return "poder", pod
    if b >= 4 and b >= d:
        return "boleta", b
    if d >= 3:
        return "demanda", d
    if pod >= 3:
        return "poder", pod
    if b >= 3:
        return "boleta", b
    if re.search(r"formulario para el ingreso de causas|constancia de inscripcion|antecedentes de dominio", plano):
        return "otro", 0
    return "sin_marcas", max(d, b)


def clasificar_paginas(paginas: list[dict]) -> list[dict]:
    """Completa paginas[i]['tipo'] con demanda | boleta | poder | otro."""
    previo = "otro"
    for pag in paginas:
        t = pag.get("texto") or ""
        plano = _plano(t)
        util = sum(1 for c in t if c.isalnum())
        tipo, _ = _tipo_de(plano, util)
        if tipo == "sin_marcas":
            # Hoja de continuación: hereda el tipo de la anterior si el texto es del mismo estilo.
            if previo == "demanda" and re.search(r"solicit|v\.s|costas|intereses|sentencia|tenga presente|proveer|autoriz", plano):
                tipo = "demanda"
            elif previo == "boleta" and re.search(r"fact\.?\s*n|vencimiento|per[i1]odo|total", plano):
                tipo = "boleta"
            else:
                tipo = "otro"
        pag["tipo"] = tipo
        previo = tipo
    return paginas


# ---------------------------------------------------------------- candidatos

class _Ctx:
    """Texto de una página, su versión plana y el acumulador de candidatos."""

    def __init__(self, pag: dict, acum: dict, prefijo: str):
        self.pag = pag
        self.t = pag.get("texto") or ""
        self.p = re.sub(r"\bin\s+re\s*\"[^\"°]{0,300}?[\"°]", lambda m: " " * len(m.group()), _plano(self.t),
                        flags=re.S)  # jurisprudencia citada: no cuenta
        self.acum = acum
        self.pref = prefijo
        self.origen = "ocr" if pag.get("origen") == "ocr" else "texto"
        self.k_ocr = (pag.get("confianza_ocr") or 0.7) if self.origen == "ocr" else 1.0

    def add(self, campo: str, valor, ini: int, fin: int, regla: str, conf: float):
        if valor in (None, "", []):
            return
        conf = max(0.01, min(0.98, conf)) * self.k_ocr
        self.acum.setdefault(f"{self.pref}.{campo}", []).append({
            "valor": valor, "pagina": self.pag["n"], "cita": _cita(self.t, ini, fin),
            "origen": self.origen, "confianza": round(conf, 3), "regla": regla,
        })


_CORTE_NOMBRE = (r"\s*[,;]?\s*(?:D\.?\s?N\.?\s?I\b|L\.?\s?[CE]\.?\s*:|C\.?\s?U\.?\s?I\.?\s?[TL]\b|CUIT|CUIL|DNI|con\s+domicilio|"
                 r"domiciliad|y/o|PADR|MATR|en su car|\bs/|-{2,}|={2,}|\bquien)")


def _nombre_limpio(s: str) -> str | None:
    s = re.split(_CORTE_NOMBRE, s, maxsplit=1, flags=re.I)[0]
    s = _lim(s, 120)
    s = re.sub(r"^(?:sr/?a?\.?|se[ñn]or(?:a)?|la sociedad|el|la)\s+", "", s, flags=re.I).strip(" .,-")
    if re.search(r"\b(?:[A-Za-z]\.){2,}[A-Za-z]$", s):  # S.R.L., S.A.: conserva el punto final
        s += "."
    if len(s) < 3 or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3}", s):
        return None
    return s


def _es_entidad(nombre: str) -> bool:
    p = _plano(nombre)
    return any(k in p for k in org.PALABRAS_ENTIDAD)


def _regla_caratula(c: _Ctx):
    pat = re.compile(r"(?:(?:juicio|autos|caratulad[oa]s?)\s*:|caratulad[oa]s?\s+(?=[“\"«]))\s*[“\"«]?\s*"
                     r"(.{8,260}?\s+c/\s*.{3,160}?\s+s/\s*[^”\"»]{2,60}?)\s*(?:[”\"»]|\.\s*\n|\.\s*$|\n\s*\n)",
                     re.I | re.S)
    for m in pat.finditer(c.t):
        texto = _lim(m.group(1), 300)
        c.add("caratula", texto, m.start(1), m.end(1), "caratula", 0.88)
        partes = re.split(r"\s+c/\s*", texto, maxsplit=1, flags=re.I)
        if len(partes) == 2:
            izq, resto = partes
            demandado = re.split(r"\s+s/\s*", resto, maxsplit=1, flags=re.I)[0]
            canon, _ = org.canon_ejecutante(_plano(izq), izq)
            if canon:
                c.add("ejecutante", canon, m.start(1), m.end(1), "caratula-actor", 0.9)
            n = _lim(demandado, 120)
            if n and not _es_entidad(n):
                c.add("ejecutado_nombre", n, m.start(1), m.end(1), "caratula-demandado", 0.88)
        return
    # Sin comillas ni «Juicio:»: «X c/ Y s/ Z» suelto
    m = re.search(r"([A-ZÁÉÍÓÚÑ][^\n]{3,100}?)\s+[Cc]/\s*([^\n]{3,120}?)\s+[Ss]/\s*[A-Za-zÁÉÍÓÚÑáéíóúñ ]{3,40}", c.t)
    if m and "in re" not in c.p[max(0, m.start() - 40): m.start() + 3] and not c.p[m.start():m.end()].strip() == "" \
            and not re.search(r"\s{15,}", c.p[m.start():m.end()]):
        c.add("caratula", _lim(m.group(0), 300), m.start(), m.end(), "caratula-suelta", 0.5)


def _regla_ejecutante(c: _Ctx):
    """Ejecutante por menciones directas (la carátula ya aporta el suyo en la demanda)."""
    p = c.p
    if c.pref == "boleta":
        casos = [(r"adeuda a (?:la )?(aguas del tucum[^,\.]{0,80}|municipalidad de [^,\.]{3,50})", 0.85),
                 (r"direccion general de rentas", 0.8), (r"cargo tributario", 0.55),
                 (r"division control de cobros judiciales", 0.7)]
    else:
        casos = [(r"apoderad[oa][^.]{0,120}?(aguas del tucum|municipalidad de [^,\.]{3,50}|direccion general de rentas)", 0.7),
                 (r"direccion general de rentas", 0.6)]
    for pat, conf in casos:
        m = re.search(pat, p)
        if m:
            canon, _ = org.canon_ejecutante(m.group(0), c.t[m.start():m.end()])
            if canon is None and re.search(r"rentas|cargo tributario|cobros judiciales", m.group(0)):
                canon = "DGR"
            if canon:
                c.add("ejecutante", canon, m.start(), m.end(), "ejecutante-mencion", conf)
                return
    # Municipalidad de X en cualquier parte de la página
    m = re.search(r"municipalidad de ([a-z\.\s]{3,40}?)(?=\s*(?:-|,|\.|\n|c/|cuit|adeuda|$))", p)
    if m:
        canon, _ = org.canon_ejecutante(m.group(0), c.t[m.start():m.end()])
        if canon:
            c.add("ejecutante", canon, m.start(), m.end(), "ejecutante-mencion-debil",
                  0.6 if c.pref == "boleta" else 0.4)
            return
    for nombre in (org.SAT, org.DGR):
        for pat in org.MARCADORES[nombre][:2]:
            m = re.search(pat, p)
            if m:
                c.add("ejecutante", org.NOMBRES_CANONICOS[nombre], m.start(), m.end(), "ejecutante-mencion-debil", 0.4)
                return


def _regla_letrado(c: _Ctx):
    t, p = c.t, c.p
    # «NOMBRE APELLIDO, abogado/a ...»
    for m in re.finditer(r"(?:^|\n)\s*([A-ZÁÉÍÓÚÑ][^\n,;]{4,70}?)\s*,\s*(?:abogad[oa]|letrad[oa]|procurador)", t):
        n = _lim(m.group(1), 80)
        if not re.search(r"\d", n) and not _es_entidad(n):
            c.add("letrado_nombre", n, m.start(1), m.end(), "letrado-abogado", 0.88)
            break
    # Encabezado: «NOMBRE\nAbogado M.P. 1234»
    for m in re.finditer(r"(?:^|\n)\s*([A-ZÁÉÍÓÚÑ][^\n,;\d]{4,60}?)\s*\n\s*(?:Abogad[oa]|ABOGAD[OA])\s*(?:M\.?\s?P|Mat)", t):
        c.add("letrado_nombre", _lim(m.group(1), 80), m.start(1), m.end(), "letrado-encabezado", 0.7)
        break
    # «Dr./Dra. NOMBRE» (autorizados o patrocinante)
    for m in re.finditer(r"\b(?:Dra?\.|DRA?\.)\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ\.' ]{4,60}?)(?=,|\s+[Mm]at|\s+M\.?\s?P|\s+T°|\s+y/o|\.\s|\n)", t):
        n = _lim(m.group(1), 80)
        if not _es_entidad(n):
            c.add("letrado_nombre", n, m.start(), m.end(), "letrado-dr", 0.5)
    # Matrícula
    pats = [
        (r"matricula\s*(?:profesional|prof\.?)?\s*(?:n°?\s*)?[:\.]?\s*(\d{1,2}[.,]?\d{3}|\d{3,5})(?!\d)", "matricula-n", 0.88),
        (r"\bm\.?\s?p\.?\s*(?:n°?\s*)?[:\.]?\s*(\d[\d.]{2,6})(?!\d)", "matricula-mp", 0.85),
        (r"\bmat\.?\s*(?:prof\.?)?\s*(?:n°?\s*)?[:\.]?\s*(\d[\d.]{2,6})(?!\d)", "matricula-mat", 0.8),
    ]
    for pat, regla, base in pats:
        for m in re.finditer(pat, p):
            num = re.sub(r"\D", "", m.group(1))
            previo = p[max(0, m.start() - 90): m.start()]
            conf = base if re.search(r"abogad|letrad|apoderad", previo) or m.start() < 900 else base - 0.3
            if re.search(r"autoriz|dr\.|dra\.", previo[-70:]):
                conf = min(conf, 0.5)
            c.add("letrado_matricula", num, m.start(), m.end(), regla, conf)
    for m in re.finditer(r"\bt\s*°?\s*(\d{1,3})\s*[/,\s]\s*(?:y\s*)?f\s*°?\s*(\d{1,4})(?!\d)", p):
        c.add("letrado_matricula", f"T°{m.group(1)} F°{m.group(2)}", m.start(), m.end(), "tomo-folio", 0.75)


_ANCLA_POS = ("contra", "c/", "demandad", "deudor", "titular", "contribuyente", "sr/a", "usuario", "ejecutado", "propietario")
_ANCLA_NEG = ("casillero", "apoderad", "mandante", "poderdante", "ejecutante", "aguas del tucum", "municipalidad de",
              "abogad", "matricula", "escribana", "comparece", "letrad", "domicilio procesal", "fiscal municipal",
              "direccion general de rentas", "sat sapem", "documento nacional")


def _cercano(previo: str, claves) -> int:
    """Distancia al fin del texto previo de la última clave que aparece (enorme si no hay)."""
    mejor = 10 ** 6
    for k in claves:
        i = previo.rfind(k)
        if i >= 0:
            mejor = min(mejor, len(previo) - i)
    return mejor


def _base_contexto(c: _Ctx, pos: int, es_cabecera: bool = False) -> float:
    previo = c.p[max(0, pos - 170): pos]
    dp, dn = _cercano(previo, _ANCLA_POS), _cercano(previo, _ANCLA_NEG)
    if es_cabecera:
        return 0.8
    if dp < dn:
        return 0.82
    if dn < dp:
        return 0.12
    return 0.45


_ETIQ_CUIT = r"c\.?\s?u\.?\s?[i1l]{1,2}\.?\s?[tl]\.?"
_PREFIJOS_PERSONA = ("20", "23", "24", "27")


def _regla_documento(c: _Ctx):
    p = c.p
    vistos = set()
    antes = len(c.acum.get(f"{c.pref}.ejecutado_documento", []))

    def ejecutante_conocido(digitos, ini, fin) -> bool:
        """El CUIT de un ejecutante conocido es candidato a ejecutante, nunca a documento del ejecutado."""
        o = org.CUIT_EJECUTANTES.get(digitos)
        if not o:
            return False
        c.add("ejecutante", org.NOMBRES_CANONICOS.get(o, o), ini, fin, "cuit-ejecutante", 0.8)
        return True

    # CUIT / CUIL con guiones, o con la etiqueta delante
    for m in re.finditer(r"(?<!\d)(20|23|24|25|26|27|30|33|34)\s?-?\s?(\d{8})\s?-?\s?(\d)(?!\d)", p):
        digitos = "".join(m.groups())
        etiqueta = re.search(_ETIQ_CUIT + r"(?:/c\.?u\.?i\.?l\.?)?\s*(?:n°?)?\s*[:\-]?\s*$", p[max(0, m.start() - 30): m.start()])
        if not etiqueta and "-" not in m.group(0):
            continue
        if (digitos, c.pag["n"]) in vistos:
            continue
        vistos.add((digitos, c.pag["n"]))
        if ejecutante_conocido(digitos, m.start(), m.end()):
            continue
        valido = cuit_valido(digitos)
        cab = c.pref == "boleta" and m.start() < 400 and bool(re.search(r"cuit/cuil\s*:\s*$", p[max(0, m.start() - 12): m.start()]))
        base = _base_contexto(c, m.start(), cab)
        conf = base * (1.0 if valido else 0.85)  # dígito verificador inválido: baja poco; la regla lo deja marcado
        if valido and base >= 0.45:
            conf += 0.08
        c.add("ejecutado_documento", digitos, m.start(), m.end(), "cuit-valido" if valido else "cuit-dv-invalido", conf)
    # CUIT contiguo con etiqueta (DGR: «CUIT/CUIL: 30711279977»)
    for m in re.finditer(_ETIQ_CUIT + r"(?:/cuil)?\s*(?:n°?)?\s*[:\-]?\s*(\d{11})(?!\d)", p):
        d = m.group(1)
        if (d, c.pag["n"]) in vistos:
            continue
        vistos.add((d, c.pag["n"]))
        if ejecutante_conocido(d, m.start(), m.end()):
            continue
        valido = cuit_valido(d)
        base = _base_contexto(c, m.start(), c.pref == "boleta" and m.start() < 400)
        c.add("ejecutado_documento", d, m.start(), m.end(), "cuit-valido" if valido else "cuit-dv-invalido",
              base * (1.0 if valido else 0.85))
    # Varios CUIT en la página: para una persona humana se prefieren los prefijos 20, 23, 24 y 27
    nuevos = c.acum.get(f"{c.pref}.ejecutado_documento", [])[antes:]
    if any(x["valor"][:2] in _PREFIJOS_PERSONA for x in nuevos) and any(x["valor"][:2] not in _PREFIJOS_PERSONA for x in nuevos):
        for x in nuevos:
            if x["valor"][:2] not in _PREFIJOS_PERSONA:
                x["confianza"] = round(x["confianza"] * 0.6, 3)
    # DNI
    if "poder" in p[:400] and "escritura" in p[:600]:
        return
    for m in re.finditer(r"(?:\bd\.?\s?n\.?\s?i\.?|\bl\.?\s?[ce]\.?(?=\s*:)|documento(?: nacional de identidad)?)\s*(?:n°?)?\s*[:\.]?\s*(\d{1,2}\s?[.,]?\s?\d{3}\s?[.,]?\s?\d{3})(?!\d)", p):
        d = re.sub(r"\D", "", m.group(1))
        if not 7 <= len(d) <= 8 or (d, c.pag["n"]) in vistos:
            continue
        vistos.add((d, c.pag["n"]))
        previo = p[max(0, m.start() - 170): m.start()]
        dp, dn = _cercano(previo, _ANCLA_POS), _cercano(previo, _ANCLA_NEG)
        base = 0.78 if dp < dn else (0.15 if dn < dp else 0.45)
        c.add("ejecutado_documento", d, m.start(), m.end(), "dni", base)


def _regla_nombre_ejecutado(c: _Ctx):
    t = c.t
    if c.pref == "demanda":
        pats = [(r"(?:en\s+)?contra\s+de\s+(.{3,200}?)(?=\s*,?\s*(?:D\.?N\.?I|CUI[TL]|C\.U\.I|con domicilio|domicili|y/o|PADR|\bquien|\n\s*\n))", "contra", 0.85, re.I | re.S),
                (r"demandad[oa]\s*:\s*([^\n]{3,120})", "demandado-etiqueta", 0.8, re.I)]
    else:
        pats = [(r"(?:deudor|contribuyente|titular|usuario|raz[oó]n social)\s*:\s*([^\n]{3,120})", "etiqueta-titular", 0.82, re.I),
                (r"\bsr/?a?\.?\s+([^\n]{3,60}(?:\n[^\n]{1,40})?)(?=\s*(?:DNI|CU[I1l]{1,2}[LT]|CUIT|D\.N\.I|[-=]{3,}))", "sra-boleta", 0.8, re.I),
                (r"(?:^|\n)\s*([A-ZÁÉÍÓÚÑ0-9][^\n,]{2,70}?)\s*,?\s*CU[I1l]{1,2}[TL]\s*(?:N°|N\*)?\s*\d", "nombre-antes-cuit", 0.62, 0)]
    for pat, regla, conf, flags in pats:
        for m in re.finditer(pat, t, flags):
            n = _nombre_limpio(m.group(1))
            if n and not _es_entidad(n) and not re.match(r"^(?:\d|n°)", n.lower()):
                c.add("ejecutado_nombre", n, m.start(1), m.end(1), regla, conf)
                break


def _es_basura_domicilio(v: str) -> bool:
    """El texto escaneado a veces mezcla columnas: un «domicilio» con importes o facturas no lo es."""
    return bool(re.search(r"fact\b|vencim|\d[.,]\d{2}\s+\d|\$", v, re.I))


def _regla_domicilio(c: _Ctx):
    t, p = c.t, c.p

    def pos_ancla(pos: int) -> float:
        previo = p[max(0, pos - 260): pos]
        dp = _cercano(previo, ("contra", "c/", "demandad", "inmueble", "deudor", "titular", "contribuyente"))
        dn = _cercano(previo, ("abogad", "matricula", "casillero", "apoderad", "mandante", "fiscal municipal"))
        if c.pref == "boleta":
            return 0.75 if dn > 120 else 0.45
        return 0.78 if dp < dn else (0.18 if dn < dp else 0.4)

    def cerrar(s: str) -> str:
        s = re.split(r"\s*(?:matricula|padron|adeuda|donde|recibi|constituy|,?\s*libr[aá]ndose|-{3,}|={3,}|\bpor la suma)", s, maxsplit=1, flags=re.I)[0]
        return _lim(s, 160)

    reglas = [
        (r"domicilio\s+(?:especial/real/social|real|fiscal|de suministro|legal|especial|de envio)\s+en\s+(.{4,200}?)(?=\s*(?:matricula|padron|-{2,}|adeuda|\.\s|;|y/o|\n\s*\n|$))", "domicilio-en"),
        (r"inmueble\s+(?:servido\s+)?(?:ubicado|sito|situado)\s+en\s+(.{4,200}?)(?=\s*(?:,?\s*y/o|,?\s*cuyo|\.\s|;|donde|recibi|matricula|padron|\n\s*\n|$))", "inmueble-en"),
        (r"con domicilio\s+(?:real\s+|fiscal\s+)?en\s+(?:calle\s+)?(.{4,160}?)(?=\s*(?:de esta ciudad|,?\s*de la ciudad|,?\s*donde|\.\s|;|\n\s*\n|$))", "con-domicilio-en"),
    ]
    for pat, regla in reglas:
        for m in re.finditer(pat, p, re.S):
            ini, fin = m.start(1), m.end(1)
            valor = cerrar(t[ini:fin])
            if len(valor) < 5 or not re.search(r"[a-z]{3}", valor.lower()) or _es_basura_domicilio(valor):
                continue
            conf = pos_ancla(m.start())
            if regla == "domicilio-en" and c.pref == "boleta":
                conf = max(conf, 0.75)
            if regla == "inmueble-en":
                conf = max(conf, 0.7)
            c.add("ejecutado_domicilio", valor, ini, fin, regla, conf)
    # Etiquetas de la boleta: «DOMICILIO: X» seguido de «LOCALIDAD: Y»
    for m in re.finditer(r"(?:^|\n)\s*(?:domicilio|direccion|ubicacion(?: del inmueble)?)\s*:\s*([^\n]{3,120})(?:\n\s*localidad\s*:\s*([^\n]{2,60}?)(?=\s+codigo|\s*\n|$))?", t, re.I):
        valor = _lim(m.group(1), 120)
        if m.group(2):
            valor = _lim(f"{valor}, {_lim(m.group(2), 50)}", 170)
        c.add("ejecutado_domicilio", valor, m.start(1), m.end(), "domicilio-etiqueta", 0.78)


def _regla_concepto(c: _Ctx):
    t, p = c.t, c.p
    m = re.search(org.PAT_CONCEPTO_SAT, p)
    if m and re.search(r"aguas del tucum|adeuda a aguas|\bsat\b", p):
        c.add("concepto", org.CONCEPTO_SAT, m.start(), m.end(), "concepto-sat", 0.75)
        return
    m = re.search(r"en concepto de\s+(.{5,140}?\))(?=\s*\.)", p, re.S) or \
        re.search(r"en concepto de\s+(.{5,120}?)(?=\.\s|;|\n\s*\n|$)", p, re.S)
    if m:
        c.add("concepto", _lim(t[m.start(1):m.end(1)], 140), m.start(1), m.end(1), "en-concepto-de", 0.75)
    m = re.search(r"por\s+(?:el(?:/los)?|los|la|las)(?:/s)?\s+(?:impuestos?|tasas?|contribuci\w+)(?:/s)?\s+(.{5,120}?)(?=,\s*correspondiente|\.\s|;|\n\s*\n|$)", p, re.S)
    if m:
        c.add("concepto", _lim(t[m.start(1):m.end(1)], 140), m.start(1), m.end(1), "por-el-impuesto", 0.75)
    for m in re.finditer(r"(?:^|\n)\s*(concepto(?: de la deuda)?|tributo|impuesto)\s*:\s*([^\n]{4,120})", p):
        v = t[m.start(2):m.end(2)]
        if not re.match(r"\s*deuda\s+al", v, re.I):
            c.add("concepto", _lim(v, 120), m.start(2), m.end(2), "concepto-etiqueta", 0.6)
    if c.pref == "boleta":
        for m in re.finditer(r"(?:^|\n)\s*((?:impuesto|tasa|contribuci\w+|derecho|canon)\b[^\n]{3,100})", p):
            v = _lim(t[m.start(1):m.end(1)], 120).rstrip(" -")
            c.add("concepto", v, m.start(1), m.end(1), "linea-tributo", 0.5)
            break
        m = re.search(r"\b(c\.?\s?i\.?\s?s\.?\s?i\.?|t\.?\s?g\.?\s?i\.?|ingresos brutos)\b", p)
        if m:
            c.add("concepto", _lim(t[m.start():m.end()], 40), m.start(), m.end(), "sigla-tributo", 0.4)


def _regla_periodos(c: _Ctx):
    todo = periodos_en(c.p)
    firmes = [x for x in todo if x[1] not in ("periodos-sueltos", "periodos-anios")]
    if firmes:  # varios rangos de una misma página: un solo candidato con la unión
        union = sorted({p for x in firmes for p in x[0]})
        mejor = max(firmes, key=lambda x: x[4])
        c.add("periodos", union, min(x[2] for x in firmes), max(x[3] for x in firmes), mejor[1], mejor[4])
    for lista, regla, ini, fin, conf in todo:
        if regla == "periodos-anios" or (regla == "periodos-sueltos" and not firmes):
            c.add("periodos", lista, ini, fin, regla, conf)


def _regla_boleta_numero(c: _Ctx):
    p, t = c.p, c.t
    anc = r"(?:boletas?\s+de\s+deuda|certificado\s+de\s+deuda|cargo(?:s)?\s+tributario(?:s)?|liquidacion\s+de\s+deuda|cuenta\s+judicial)"
    tok = r"(?:[a-z]{2,4}/)?\d{1,8}/(?:19|20)\d\d(?![\d/])"
    vistos = set()
    for m in re.finditer(anc + r"[^\d\n]{0,40}?(?:\n[^\d\n]{0,12})?\s*(?:n°\s*)?((?:" + tok + r"\s*(?:,|y|e)?\s*)+)", p):
        for n in re.finditer(tok, m.group(1)):
            v = n.group(0).upper()
            if v in vistos:
                continue
            vistos.add(v)
            ini = m.start(1) + n.start()
            c.add("boleta_numero", v, ini, ini + len(v), "boleta-numero-ancla", 0.85)
    if c.pref == "boleta":
        # «N 12345/2025» en las primeras líneas (el OCR pierde el «°» y el título)
        lineas = [(m.start(), m.group()) for m in re.finditer(r"[^\n]+", p) if m.group().strip()][:5]
        for off, ln in lineas:
            for m in re.finditer(r"(?<![a-z])n\s*[°º*?o]?\s*(\d{3,}/(?:19|20)\d\d)(?!\d)", ln):
                v = m.group(1)
                if v not in vistos:
                    vistos.add(v)
                    c.add("boleta_numero", v, off + m.start(1), off + m.end(1), "boleta-numero-cabecera", 0.7)
    m = re.search(r"n°\s*de\s*boleta\s*de\s*deuda\s*:?\s*[^\w]{0,3}([a-z]{2,4}/\S{1,10}/\S{2,5})", p)
    if m:
        raw = t[m.start(1):m.end(1)].upper()
        fix = raw.translate(str.maketrans({"S": "5", "O": "0", "I": "1", "L": "1"}))
        parte = fix.split("/")
        ok = len(parte) == 3 and parte[1].isdigit() and parte[2].isdigit() and len(parte[2]) == 4
        v = fix if ok else raw
        if v not in vistos:
            c.add("boleta_numero", v, m.start(1), m.end(1), "boleta-numero-etiqueta", 0.8 if ok else 0.4)


def _regla_boleta_fecha(c: _Ctx):
    p = c.p
    sueltas = []
    hallada = False
    if c.pref == "boleta":
        # «a los 21 días del mes de OCTUBRE de 2024» (boleta de la SAT)
        for m in re.finditer(rf"a\s+los\s+(\d{{1,2}})\s+d[i1]as\s+del\s+mes\s+de\s+({_MES_RE})\s*(?:de|del)?\s*(\d{{4}})", p):
            anio = int(m.group(3))
            if anio:
                iso = _fecha_iso(int(m.group(1)), MESES[m.group(2)], anio)
                if iso:
                    c.add("boleta_fecha", iso, m.start(), m.end(), "dias-del-mes", 0.8)
                    hallada = True
    for iso, s, e in fechas_en(p):
        izq = p[max(0, s - 45): s]
        if c.pref == "demanda":
            ventana = p[max(0, s - 110): s]
            if re.search(r"(?:boleta|certificado|cargo)[^\n]{0,80}?(?:de fecha|emitid[ao]\s+(?:el|en)|con fecha|del)\s*$", ventana):
                c.add("boleta_fecha", iso, s, e, "boleta-fecha-demanda", 0.6)
            continue
        if re.search(r"tucuman\s*,\s*(?:[a-z]+\s*,?\s*)?$", izq):
            c.add("boleta_fecha", iso, s, e, "lugar-fecha", 0.8)
            hallada = True
        elif re.search(r"(emitid[oa]|emision|expedid[oa]|extendid[oa]|certificad[oa])\W+(?:el|en|con fecha|de fecha)?\W*$", izq):
            c.add("boleta_fecha", iso, s, e, "fecha-emision", 0.75)
            hallada = True
        elif re.search(r"deuda\s+(?:actualizada\s+)?al\s*$", izq):
            c.add("boleta_fecha", iso, s, e, "deuda-al", 0.45)
        elif "vencimiento" in izq[-25:] or re.search(r"acta|fecha de|resolucion|decreto|ley\b", izq[-30:]):
            continue
        elif len(sueltas) < 2:
            sueltas.append((iso, s, e))
    if not hallada:
        for iso, s, e in sueltas:
            c.add("boleta_fecha", iso, s, e, "fecha-suelta", 0.25)


def _montos_tras(p: str, pos: int, maximo: int = 3, ventana: int = 90, solo_decimales: bool = True) -> list[tuple[str, int, int]]:
    """Montos seguidos a partir de pos, en la misma línea."""
    linea = p[pos: pos + ventana].split("\n")[0]
    res = []
    for m in re.finditer(r"\$?\s*(" + _NUM + r")(?![\d]|\s*%)", linea):
        if solo_decimales and not re.search(r"[.,]\d{2}$", m.group(1)):
            continue
        v = parse_monto(m.group(1))
        if v:
            res.append((v, pos + m.start(1), pos + m.end(1)))
        if len(res) >= maximo:
            break
    return res


def _regla_montos(c: _Ctx):
    p = c.p
    pref = c.pref
    # Fila de totales: capital, [intereses,] total
    for m in re.finditer(r"totales(?:\s+generales)?\s*:?", p):
        ms = _montos_tras(p, m.end())
        if len(ms) >= 2:
            c.add("monto_capital", ms[0][0], m.start(), ms[0][2], "totales-capital", 0.75)
            c.add("monto_total", ms[-1][0], m.start(), ms[-1][2], "totales-total", 0.8)
    if pref == "boleta":
        for m in re.finditer(r"(?m)^\s*total\s*:?\s*\$\s*(" + _NUM + r")\s*$", p):
            v = parse_monto(m.group(1))
            if v:
                c.add("monto_total", v, m.start(), m.end(), "total-linea", 0.75)
    for m in re.finditer(r"total\s+general\s+de\s+la\s+deuda\s*:?", p):
        ms = _montos_tras(p, m.end(), 1)
        if ms:
            c.add("monto_total", ms[0][0], m.start(), ms[0][2], "total-general-deuda", 0.9)
    # «la suma de $ X» (boleta) / «por la suma de pesos ... ($ X)» (demanda)
    for m in re.finditer(r"(?:suma|monto|importe)\s+(?:total\s+)?de\s*:?\s*(?:pesos\s*:?)?[^$\d]{0,170}?\$\s*(" + _NUM + r")", p):
        v = parse_monto(m.group(1))
        if not v:
            continue
        previo = p[max(0, m.start() - 40): m.start()]
        if re.search(r"honorario|tasa de justicia|bono|aporte|valuacion", previo + p[m.start(): m.start() + 20]):
            continue
        if pref == "boleta":
            c.add("monto_total", v, m.start(), m.end(1), "suma-adeuda", 0.85)
            c.add("monto_capital", v, m.start(), m.end(1), "suma-nominal-historico", 0.55)
        else:
            c.add("monto_total", v, m.start(), m.end(1), "suma-reclamada", 0.85)
            c.add("monto_capital", v, m.start(), m.end(1), "reclamado-como-capital", 0.5)
    for m in re.finditer(r"(?:capital|importe original|monto original|deuda original|nominal)(?:\s+(?:reclamado|adeudado|historico))?\s*(?:de|por|:)?\s*\$\s*(" + _NUM + r")", p):
        v = parse_monto(m.group(1))
        if v:
            c.add("monto_capital", v, m.start(), m.end(1), "etiqueta-capital", 0.78)
    if pref == "boleta":
        for m in re.finditer(r"(?<![a-z])intereses?\s*:?\s*\$\s*(" + _NUM + r")", p):
            v = parse_monto(m.group(1))
            if v:
                c.add("monto_intereses", v, m.start(), m.end(1), "etiqueta-intereses", 0.8)
    for m in re.finditer(r"(?:importe\s+total|monto\s+total|total\s+adeudado|deuda\s+total|total\s+reclamado)\s*(?:de|por|:)?\s*\$?\s*(" + _NUM + r")", p):
        v = parse_monto(m.group(1))
        if v:
            c.add("monto_total", v, m.start(), m.end(1), "etiqueta-total", 0.75)


def _regla_expediente(c: _Ctx):
    p = c.p
    for m in re.finditer(r"(?:expte\.?|expediente)\s*(?:n°?)?\s*[:\.]?\s*(\d{1,6}\s*/\s*\d{2,4})(?!\d|/)", p):
        if "administrativ" in p[max(0, m.start() - 30): m.end() + 20]:
            continue
        c.add("expediente_numero", re.sub(r"\s", "", m.group(1)), m.start(), m.end(), "expediente-n", 0.8)


# ---------------------------------------------------------------- organismo

def _detectar_organismo(paginas: list[dict], carat: list[dict]) -> dict:
    puntos = {org.SAT: 0.0, org.DGR: 0.0, org.MUNICIPALIDAD: 0.0}
    mejor_cita = {k: (None, "") for k in puntos}
    utiles = [p for p in paginas if p.get("tipo") in ("demanda", "boleta")] or paginas
    por_carat = False
    for cand in carat:
        izq = re.split(r"\s+c/\s*", cand["valor"], maxsplit=1, flags=re.I)[0]
        canon, o = org.canon_ejecutante(_plano(izq), izq)
        if o:
            puntos[o] += 5
            por_carat = True
            mejor_cita[o] = (cand["pagina"], cand["cita"])
    for pag in utiles:
        t = pag.get("texto") or ""
        t = re.sub(r"\bin\s+re\s*[“\"][^”\"]{0,300}?[”\"]", " ", t, flags=re.S | re.I)  # jurisprudencia citada
        p = _plano(t)
        es_boleta = pag.get("tipo") == "boleta"
        for o, pats in org.MARCADORES.items():
            for pat in pats:
                m = re.search(pat, p)
                if m:
                    puntos[o] += 3 if es_boleta else 2
                    if mejor_cita[o][0] is None:
                        mejor_cita[o] = (pag["n"], _cita(t, m.start(), m.end()))
                    break
    ordenados = sorted(puntos.items(), key=lambda kv: -kv[1])
    (o1, s1), (_, s2) = ordenados[0], ordenados[1]
    if s1 < 2:
        return {"valor": None, "pagina": None, "cita": "no consta", "confianza": 0.0}
    conf = 0.95 if (por_carat and s1 >= 2 * s2) else (0.8 if s1 >= 2 * s2 else 0.5)
    pag, cita = mejor_cita[o1]
    return {"valor": o1, "pagina": pag, "cita": cita, "confianza": conf}


# ---------------------------------------------------------------- orquestación

_REGLAS = [_regla_caratula, _regla_ejecutante, _regla_nombre_ejecutado, _regla_documento, _regla_domicilio,
           _regla_concepto, _regla_periodos, _regla_boleta_numero, _regla_boleta_fecha, _regla_montos]
_SOLO_DEMANDA = [_regla_letrado, _regla_expediente]


def _clave_valor(v):
    return tuple(v) if isinstance(v, list) else v


def _consolidar(acum: dict, claves: list[str]) -> dict:
    campos = {}
    for clave in claves:
        mejores: dict = {}
        for cd in acum.get(clave, []):
            k = (_clave_valor(cd["valor"]), cd["pagina"])
            if k not in mejores or cd["confianza"] > mejores[k]["confianza"]:
                mejores[k] = cd
        lista = list(mejores.values())
        por_valor: dict = {}
        for cd in lista:  # un mismo valor en varias páginas refuerza al mejor
            por_valor.setdefault(_clave_valor(cd["valor"]), []).append(cd)
        for grupo in por_valor.values():
            if len(grupo) > 1:
                top = max(grupo, key=lambda x: x["confianza"])
                top["confianza"] = round(min(0.98, top["confianza"] + 0.05 * (len(grupo) - 1)), 3)
        lista.sort(key=lambda x: (-x["confianza"], x["pagina"]))
        lista = lista[:MAX_CANDIDATOS]
        campos[clave] = {"valor": lista[0]["valor"] if lista else None, "confirmado": False, "candidatos": lista}
    return campos


def _suma_boletas(acum: dict):
    """Con varias boletas, un candidato con la suma de sus totales (lo que suele reclamar la demanda)."""
    tot = [c for c in acum.get("boleta.monto_total", []) if c["regla"] in ("total-general-deuda", "suma-adeuda")]
    por_pagina: dict = {}
    for c in tot:
        if c["pagina"] not in por_pagina or c["confianza"] > por_pagina[c["pagina"]]["confianza"]:
            por_pagina[c["pagina"]] = c
    if len(por_pagina) >= 2:
        suma = sum(Decimal(c["valor"]) for c in por_pagina.values())
        primera = min(por_pagina.values(), key=lambda x: x["pagina"])
        acum["boleta.monto_total"].append({
            "valor": f"{suma:.2f}", "pagina": primera["pagina"],
            "cita": f"suma de {len(por_pagina)} boletas (págs. " + ", ".join(str(n) for n in sorted(por_pagina)) + ")",
            "origen": primera["origen"],
            "confianza": round(0.6 * min(c["confianza"] for c in por_pagina.values()), 3), "regla": "suma-de-boletas"})


def detectar(paginas: list[dict]) -> dict:
    """{"organismo": {...}, "campos": {...}} con candidatos por campo, ordenados por confianza."""
    if any(not p.get("tipo") for p in paginas):
        clasificar_paginas(paginas)
    acum: dict = {}
    for pag in paginas:
        tipo = pag.get("tipo")
        if tipo not in ("demanda", "boleta"):
            continue
        c = _Ctx(pag, acum, tipo)
        for regla in _REGLAS + (_SOLO_DEMANDA if tipo == "demanda" else []):
            try:
                regla(c)
            except Exception:  # una regla rota no tumba el resto
                continue
    _suma_boletas(acum)
    organismo = _detectar_organismo(paginas, acum.get("demanda.caratula", []))
    claves = [f"demanda.{x}" for x in CAMPOS_DEMANDA] + [f"boleta.{x}" for x in CAMPOS_BOLETA]
    return {"organismo": organismo, "campos": _consolidar(acum, claves)}
