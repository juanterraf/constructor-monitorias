"""Cuerpo de la sentencia monitoria y .docx con la plantilla oficial del PJT. Sin IA.

armar_cuerpo(caso, config) -> [{"texto", "estilo": "titulo|parrafo|resuelvo"}]
generar_docx(caso, config, ruta_salida) -> ruta

Los textos viven en plantillas/cuerpo-<organismo>.txt (el juzgado los edita sin tocar código):
  una línea = un párrafo · "# " título · "% " considerando numerado · "> " punto del resuelvo numerado
  {marcador} se completa con el caso; si falta, queda "[COMPLETAR: ...]"
  "[diferir]" / "[regular]" al inicio de la línea: entra solo con esa opción de honorarios
  **texto** en negrita · las líneas que empiezan con // no salen.

Claves de `config` (config.local.json), además de las de chequeos.py:
  lugar                  lugar de la sentencia (por defecto "Concepción", como el modelo del juzgado)
  tasa_interes           texto de la tasa; si falta, queda para completar
  honorarios             "diferir" (por defecto) o "regular"; minimo_cat para regular
  presupuesto_pct        % del capital que se presupuesta para intereses y costas (criterio del juez)
  martillero             texto del martillero autorizado al embargo
  cuenta_judicial        por defecto "Banco Macro S.A., sucursal Concepción" (modelo del juzgado)
  ahora                  AAAA-MM-DDTHH:MM:SS (para pruebas) de la fecha de impresión
"""
import re
import zipfile
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.sax.saxutils import escape, unescape

from .chequeos import campo, centro_notificacion, organismo_de
from .cotejo import parse_fecha, parse_periodos, solo_digitos
from .honorarios import calcular, fmt_ars, parse_monto
from .letras import monto_en_letras
from .config import para_motor

BASE = Path(__file__).resolve().parent.parent
PLANTILLAS = BASE / "plantillas"
PLANTILLA_DOCX = PLANTILLAS / "Plantilla-Sentencia-Monitoria-PJT.docx"
ARCHIVO_CUERPO = {"SAT": "cuerpo-sat.txt", "MUNICIPALIDAD": "cuerpo-municipalidad.txt", "DGR": "cuerpo-dgr.txt"}
EJECUTANTE_POR_DEFECTO = {"SAT": "SOCIEDAD AGUAS DEL TUCUMÁN S.A.P.E.M.", "MUNICIPALIDAD": None, "DGR": "DIRECCIÓN GENERAL DE RENTAS"}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
ETIQUETAS = {
    "caratula": "carátula", "expediente": "número de expediente", "lugar": "lugar", "ejecutante": "ejecutante",
    "letrado": "nombre del letrado", "matricula_texto": "matrícula del letrado", "ejecutado": "nombre del ejecutado",
    "documento_texto": "documento del ejecutado", "domicilio": "domicilio del ejecutado", "concepto": "concepto",
    "periodos_texto": "períodos", "boleta_numero": "número de boleta", "boleta_fecha_larga": "fecha de emisión de la boleta",
    "monto": "monto reclamado", "monto_letras": "monto reclamado en letras", "capital": "capital",
    "presupuesto": "monto presupuestado para intereses, honorarios, gastos y costas",
    "presupuesto_letras": "monto presupuestado en letras", "tasa_interes": "tasa de interés",
    "martillero": "martillero público autorizado al embargo", "fecha_sentencia_larga": "fecha de la sentencia",
    "centro_notificacion": "centro judicial del domicilio del ejecutado", "honorarios_final": "honorarios",
    "honorarios_base": "base de honorarios", "honorarios_calculado": "honorarios calculados",
}


# ---------- formato ----------

def fecha_larga(valor):
    f = parse_fecha(valor)
    return f"{f.day} de {MESES[f.month - 1]} de {f.year}" if f else None


def fecha_corta(valor):
    f = parse_fecha(valor)
    return f.strftime("%d/%m/%Y") if f else None


def _romano(n):
    out = ""
    for v, s in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out, n = out + s, n - v
    return out


def _documento_texto(v):
    d = solo_digitos(v)
    if len(d) == 11:
        return f"CUIT/CUIL N° {d[:2]}-{d[2:10]}-{d[10]}"
    if d:
        return f"DNI N° {int(d):,}".replace(",", ".")
    return None


def _periodos_texto(v):
    per = parse_periodos(v)
    return ", ".join(f"{p[5:]}/{p[:4]}" for p in per) if per else None


def honorarios_del_caso(caso, config):
    """Resultado de honorarios (Ley 5.480) para el caso, o None si se difieren."""
    config = para_motor(config)
    if str(config.get("honorarios") or "diferir").lower() != "regular":
        return None
    h = caso.get("honorarios") or {}
    if "final" in h:
        return h
    base = (campo(caso, "demanda.monto_total") or campo(caso, "boleta.monto_total")
            or campo(caso, "demanda.monto_capital") or campo(caso, "boleta.monto_capital"))
    return calcular(base, reduccion=bool(config.get("reduccion", True)), pct_art14=float(config.get("pct_art14") or 16),
                    multiplicador=float(config.get("multiplicador") or 1.55), minimo_cat=config.get("minimo_cat"))


# ---------- valores de los marcadores ----------

def _valores(caso, config):
    config = config or {}
    g = lambda n: campo(caso, n, config)
    org = organismo_de(caso)
    pref = lambda n: g(f"demanda.{n}") or g(f"boleta.{n}")
    v = {}
    v["caratula"] = g("demanda.caratula")
    v["expediente"] = g("demanda.expediente_numero")
    v["lugar"] = config.get("lugar") or "Concepción"
    v["ejecutante"] = pref("ejecutante") or EJECUTANTE_POR_DEFECTO.get(org)
    v["letrado"] = g("demanda.letrado_nombre")
    mat = g("demanda.letrado_matricula")
    v["matricula_texto"] = f"matrícula o T°/F° del C.A.T. {mat}" if mat else None
    v["ejecutado"] = pref("ejecutado_nombre")
    v["documento_texto"] = _documento_texto(pref("ejecutado_documento"))
    v["domicilio"] = pref("ejecutado_domicilio")
    v["concepto"] = pref("concepto")
    v["periodos_texto"] = _periodos_texto(pref("periodos"))
    v["boleta_numero"] = pref("boleta_numero")
    v["boleta_fecha_larga"] = fecha_larga(pref("boleta_fecha"))
    fd = fecha_larga(g("demanda.fecha"))
    v["fecha_demanda_frase"] = f"En fecha {fecha_corta(g('demanda.fecha'))}" if fd else "[COMPLETAR: fecha de presentación de la demanda]"
    cap_raw, tot_raw = pref("monto_capital"), pref("monto_total")
    cap = parse_monto(cap_raw) if cap_raw is not None else None
    rec = parse_monto(tot_raw) if tot_raw is not None else cap
    v["capital"] = fmt_ars(cap) if cap is not None else None
    v["monto"] = fmt_ars(rec) if rec is not None else None
    v["monto_letras"] = monto_en_letras(rec).upper() if rec is not None else None
    pct = config.get("presupuesto_pct")
    if pct is not None and rec is not None:
        pres = (rec * Decimal(str(pct)) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        v["presupuesto"], v["presupuesto_letras"] = fmt_ars(pres), monto_en_letras(pres).upper()
    v["tasa_interes"] = config.get("tasa_interes")
    v["martillero"] = config.get("martillero")
    v["cuenta_judicial"] = config.get("cuenta_judicial") or "Banco Macro S.A., sucursal Concepción"
    v["fecha_sentencia_larga"] = fecha_larga(g("juzgado.fecha_sentencia"))
    v["centro_notificacion"] = centro_notificacion(v["domicilio"])
    h = honorarios_del_caso(caso, config)
    if h:
        v["honorarios_final"], v["honorarios_base"] = fmt_ars(h["final"]), fmt_ars(h["base"])
        v["honorarios_calculado"] = fmt_ars(h["calculado"])
        if h.get("aplica_minimo"):
            v["honorarios_minimo_frase"] = f"; por resultar inferior al mínimo de la consulta escrita del C.A.T., se fija en {fmt_ars(h['minimo'])}"
        elif parse_monto(h.get("minimo", 0)) > 0:
            v["honorarios_minimo_frase"] = ""
        else:
            v["honorarios_minimo_frase"] = " [COMPLETAR: verificar el mínimo de la consulta escrita del C.A.T.]"
    return v


def _completar(texto, valores):
    def sub(m):
        nombre = m.group(1)
        val = valores.get(nombre)
        if val is None or val == "":
            return "" if nombre == "honorarios_minimo_frase" else f"[COMPLETAR: {ETIQUETAS.get(nombre, nombre.replace('_', ' '))}]"
        return str(val)
    return re.sub(r"\{([a-z_]+)\}", sub, texto)


_TAG = re.compile(r"^\[(diferir|regular)\]\s+")


def armar_cuerpo(caso, config) -> list:
    config = para_motor(config)
    org = organismo_de(caso)
    if org is None:
        raise ValueError("Falta el organismo (SAT, MUNICIPALIDAD o DGR): no se puede elegir el texto.")
    modo = str((config or {}).get("honorarios") or "diferir").lower()
    modo = "regular" if modo == "regular" else "diferir"
    valores = _valores(caso, config)
    texto = (PLANTILLAS / ARCHIVO_CUERPO[org]).read_text(encoding="utf-8")
    out, n_cons, n_res, seccion = [], 0, 0, None
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("//"):
            continue
        m = _TAG.match(linea)
        if m:
            if m.group(1) != modo:
                continue
            linea = linea[m.end():]
        if linea.startswith("# "):
            out.append({"texto": _completar(linea[2:], valores), "estilo": "titulo"})
            seccion, n_cons, n_res = linea[2:].strip(), 0, 0
        elif linea.startswith("% "):
            n_cons += 1
            out.append({"texto": f"{_romano(n_cons)}. " + _completar(linea[2:], valores), "estilo": "parrafo"})
        elif linea.startswith("> "):
            n_res += 1
            out.append({"texto": f"{_romano(n_res)}. " + _completar(linea[2:], valores), "estilo": "resuelvo"})
        else:
            out.append({"texto": _completar(linea, valores), "estilo": "parrafo"})
    return out


def pendientes(parrafos) -> list:
    """Todos los [COMPLETAR: ...] que quedaron en el cuerpo."""
    return [m for p in parrafos for m in re.findall(r"\[COMPLETAR: [^\]]*\]", p["texto"])]


# ---------- .docx ----------

_RPR_BASE = '<w:rFonts w:ascii="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman" w:hAnsi="Times New Roman"/>'


def _runs(texto, negrita_total=False, sz=24):
    partes = re.split(r"(\*\*.+?\*\*)", texto)
    runs = []
    for parte in partes:
        if not parte:
            continue
        neg = negrita_total
        if parte.startswith("**") and parte.endswith("**") and len(parte) > 4:
            parte, neg = parte[2:-2], True
        b = "<w:b/><w:bCs/>" if neg else ""
        runs.append(f'<w:r><w:rPr>{_RPR_BASE}{b}<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/></w:rPr>'
                    f'<w:t xml:space="preserve">{escape(parte)}</w:t></w:r>')
    return "".join(runs)


def _parrafo_xml(p, primero_titulo):
    estilo = p["estilo"]
    if estilo == "titulo":
        jc = "center" if primero_titulo else "left"
        ppr = f'<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120" w:line="360" w:lineRule="auto"/><w:jc w:val="{jc}"/></w:pPr>'
        return f"<w:p>{ppr}{_runs(p['texto'], negrita_total=True)}</w:p>"
    ppr = '<w:pPr><w:spacing w:before="0" w:after="120" w:line="360" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr>'
    return f"<w:p>{ppr}{_runs(p['texto'])}</w:p>"


def cuerpo_ooxml(parrafos) -> str:
    out, vio_titulo = [], False
    for p in parrafos:
        out.append(_parrafo_xml(p, primero_titulo=(p["estilo"] == "titulo" and not vio_titulo)))
        vio_titulo = vio_titulo or p["estilo"] == "titulo"
    return "".join(out)


_PARRAFO = re.compile(r"<w:p[ >].*?</w:p>", re.S)
_TEXTO = re.compile(r"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.S)
_MARCADOR = re.compile(r"\{[@A-Za-z_]+\}")


def _marcadores(caso, config, parrafos):
    g = lambda n: campo(caso, n, config)
    cen = (g("juzgado.centro") or "")
    ahora = (config or {}).get("ahora")
    try:
        ahora = datetime.fromisoformat(ahora) if ahora else datetime.now()
    except ValueError:
        ahora = datetime.now()
    falta = lambda txt: f"[COMPLETAR: {txt}]"
    return {
        "{caratula}": g("demanda.caratula") or falta("carátula"),
        "{expediente}": g("demanda.expediente_numero") or falta("número de expediente"),
        "{nroSentencia}": g("juzgado.nro_sentencia") or falta("número de sentencia"),
        "{fechaSentencia}": fecha_corta(g("juzgado.fecha_sentencia")) or falta("fecha de la sentencia"),
        "{unidadJudicial}": g("juzgado.unidad") or falta("unidad judicial"),
        "{centroJudicial}": str(cen).upper() if cen else falta("centro judicial"),
        "{fechaImpresion}": ahora.strftime("%d/%m/%Y - %H:%M:%S"),
    }


def _reemplazar_documento(xml, marcadores, cuerpo_xml):
    def por_parrafo(m):
        p = m.group(0)
        textos = _TEXTO.findall(p)
        if not textos:
            return p
        unido = "".join(unescape(t[1]) for t in textos)
        if unido.strip() == "{@cuerpo}":
            return cuerpo_xml
        if "{" not in unido:
            return p
        # 1) marcadores enteros dentro de un mismo run
        def sub_run(mt):
            t = unescape(mt.group(2))
            for k, val in marcadores.items():
                t = t.replace(k, val)
            return mt.group(1) + escape(t) + mt.group(3)
        p2 = _TEXTO.sub(sub_run, p)
        # 2) marcadores partidos en varios runs: se juntan en el primero
        textos2 = _TEXTO.findall(p2)
        unido2 = "".join(unescape(t[1]) for t in textos2)
        if _MARCADOR.search(unido2) and any(k in unido2 for k in marcadores):
            for k, val in marcadores.items():
                unido2 = unido2.replace(k, val)
            primero = [True]

            def juntar(mt):
                if primero[0]:
                    primero[0] = False
                    return mt.group(1) + escape(unido2) + mt.group(3)
                return mt.group(1) + mt.group(3)
            p2 = _TEXTO.sub(juntar, p2)
        return p2
    return _PARRAFO.sub(por_parrafo, xml)


def generar_docx(caso, config, ruta_salida) -> str:
    config = para_motor(config)
    parrafos = armar_cuerpo(caso, config)
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    marcadores = _marcadores(caso, config, parrafos)
    with zipfile.ZipFile(PLANTILLA_DOCX) as zin, zipfile.ZipFile(ruta_salida, "w") as zout:
        for item in zin.infolist():
            datos = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = _reemplazar_documento(datos.decode("utf-8"), marcadores, cuerpo_ooxml(parrafos))
                datos = xml.encode("utf-8")
            zout.writestr(item, datos, compress_type=item.compress_type)
    return str(ruta_salida)
