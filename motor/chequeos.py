"""Chequeos deterministas del título y del proceso (checklist A-J del juzgado y artefacto.txt). Sin IA.

chequear(caso, config) -> [{"id", "titulo", "resultado": OK|OBSERVAR|FALTA|MANUAL, "detalle"}]

Lo que pide criterio jurídico (prescripción, habilidad del título) sale como MANUAL, con los datos útiles.

Claves de `config` que se leen (todas opcionales; viven en config.local.json):
  unidad, centro            unidad judicial y centro judicial del encabezado
  lugar                     lugar de la sentencia (por defecto "Concepción")
  tasa_interes              texto de la tasa (si falta, el chequeo F1 es MANUAL)
  honorarios                "diferir" (por defecto) o "regular"
  minimo_cat                mínimo de la consulta escrita del C.A.T. (para regular)
  hoy                       fecha AAAA-MM-DD (para pruebas); por defecto, la de la computadora
Campos opcionales del caso que se usan si están: demanda.fecha (presentación de la demanda),
juzgado.unidad, juzgado.centro, juzgado.nro_sentencia, juzgado.fecha_sentencia.
"""
import re
from datetime import date

from .cotejo import (DIFIERE, FALTA as C_FALTA, cotejar, palabras, parse_fecha, parse_periodos,
                     solo_digitos, valor_de)
from .honorarios import parse_monto
from .config import para_motor

OK, OBSERVAR, FALTA, MANUAL = "OK", "OBSERVAR", "FALTA", "MANUAL"

ORGANISMOS = {
    # organismo: (vía, palabras que debe tener la denominación del ejecutante)
    "SAT": ("Procesal: solo juicio ejecutivo monitorio", {"aguas"}),
    "MUNICIPALIDAD": ("Ley 5.121: opción entre ejecución fiscal y cobro ejecutivo monitorio (más Ley 5.529)", {"municipalidad"}),
    "DGR": ("Ley 5.121: opción entre ejecución fiscal y cobro ejecutivo monitorio", {"rentas"}),
}
# Residuos de plantilla de otro organismo: palabra clave -> organismo al que pertenece
_RESIDUOS = {"aguas": "SAT", "municipalidad": "MUNICIPALIDAD", "rentas": "DGR"}


def hoy(config):
    return parse_fecha((config or {}).get("hoy")) or date.today()


def campo(caso, nombre, config=None):
    """Valor de un campo del caso; para juzgado.unidad y juzgado.centro cae a la configuración."""
    v = valor_de(caso.get("campos"), nombre)
    if v is None and config:
        corto = {"juzgado.unidad": "unidad", "juzgado.centro": "centro"}.get(nombre)
        if corto and config.get(corto):
            return config[corto]
    return v


def organismo_de(caso):
    o = caso.get("organismo")
    v = o.get("valor") if isinstance(o, dict) else o
    return v if v in ORGANISMOS else None


def cuit_valido(digitos) -> bool:
    """CUIT/CUIL de 11 dígitos: prefijo habitual y dígito verificador (módulo 11)."""
    d = solo_digitos(digitos)
    if len(d) != 11 or d[:2] not in {"20", "23", "24", "25", "26", "27", "30", "33", "34"}:
        return False
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    r = 11 - sum(int(a) * b for a, b in zip(d[:10], pesos)) % 11
    verif = {11: 0, 10: 9}.get(r, r)
    return verif == int(d[10])


def centro_notificacion(domicilio):
    """Centro judicial del domicilio real del ejecutado, o None si no se puede decir."""
    t = " ".join(palabras(domicilio or ""))
    if "concepcion" in t:
        return "Concepción"
    if "monteros" in t:
        return "Monteros"
    if "banda del rio sali" in t:
        return "Banda del Río Salí"
    if "san miguel de tucuman" in t or re.search(r"\bs m de tucuman\b", t) or re.search(r"\bsmt\b", t):
        return "Capital"
    return None


def _c(id_, titulo, resultado, detalle):
    return {"id": id_, "titulo": titulo, "resultado": resultado, "detalle": detalle}


def chequear(caso, config) -> list:
    config = para_motor(config)
    campos = caso.get("campos") or {}
    g = lambda n: campo(caso, n, config)
    org = organismo_de(caso)
    fecha_hoy = hoy(config)
    r = []

    # A. Identificación y competencia
    exp, car = g("demanda.expediente_numero"), g("demanda.caratula")
    faltan = [n for n, v in (("número de expediente", exp), ("carátula", car)) if not v]
    r.append(_c("A1", "Expediente y carátula", FALTA if faltan else OK,
                ("Falta: " + ", ".join(faltan) + ".") if faltan else "Constan número de expediente y carátula."))

    dom = g("demanda.ejecutado_domicilio") or g("boleta.ejecutado_domicilio")
    centro = centro_notificacion(dom)
    sede = ("Regla del juzgado: sede en Concepción (OGA 1), competencia territorial en toda la Provincia; "
            "cuenta judicial en Concepción. La diferencia entre sede y domicilio del ejecutado NO es una incoherencia.")
    if not dom:
        r.append(_c("A2", "Sede y centro de notificación", FALTA, "Falta el domicilio del ejecutado. " + sede))
    elif centro:
        r.append(_c("A2", "Sede y centro de notificación", OK,
                    f"Cédula a Oficiales Notificadores del Centro Judicial {centro} (domicilio real del ejecutado; "
                    f"arts. 200 y 202 CPCCT). " + sede))
    else:
        r.append(_c("A2", "Sede y centro de notificación", MANUAL,
                    "No se pudo deducir el centro judicial del domicilio; definirlo a mano para la cédula. " + sede))

    j_faltan = [n for n, v in (("unidad judicial", g("juzgado.unidad")), ("centro judicial", g("juzgado.centro")),
                               ("fecha de la sentencia", g("juzgado.fecha_sentencia"))) if not v]
    if j_faltan:
        r.append(_c("A3", "Datos del juzgado para el encabezado", FALTA, "Falta: " + ", ".join(j_faltan) + "."))
    elif not g("juzgado.nro_sentencia"):
        r.append(_c("A3", "Datos del juzgado para el encabezado", OBSERVAR,
                    "Falta el número de sentencia; queda como [COMPLETAR] (se asigna al firmar)."))
    else:
        r.append(_c("A3", "Datos del juzgado para el encabezado", OK, "Unidad, centro, número y fecha de sentencia cargados."))

    # B. Título ejecutivo
    num, fe = g("boleta.boleta_numero"), g("boleta.boleta_fecha")
    f_emi = parse_fecha(fe)
    if not num or not fe:
        r.append(_c("B1", "El título tiene número y fecha", FALTA,
                    "Falta " + " y ".join(n for n, v in (("el número", num), ("la fecha de emisión", fe)) if not v) + " de la boleta."))
    elif f_emi is None:
        r.append(_c("B1", "El título tiene número y fecha", OBSERVAR, f"La fecha de emisión ({fe}) no se pudo leer."))
    else:
        r.append(_c("B1", "El título tiene número y fecha", OK, f"Boleta N° {num}, emitida el {f_emi.isoformat()}."))

    f_dem = parse_fecha(g("demanda.fecha"))
    if f_emi is None:
        r.append(_c("B2", "La emisión es anterior a la demanda", FALTA if not fe else OBSERVAR, "Sin fecha de emisión legible."))
    elif f_dem is not None:
        if f_emi < f_dem:
            r.append(_c("B2", "La emisión es anterior a la demanda", OK, f"Emisión {f_emi.isoformat()}, demanda {f_dem.isoformat()}."))
        else:
            r.append(_c("B2", "La emisión es anterior a la demanda", OBSERVAR,
                        f"La emisión ({f_emi.isoformat()}) no es anterior a la demanda ({f_dem.isoformat()})."))
    elif f_emi > fecha_hoy:
        r.append(_c("B2", "La emisión es anterior a la demanda", OBSERVAR,
                    f"La emisión ({f_emi.isoformat()}) es posterior a hoy; no se cargó la fecha de la demanda."))
    else:
        r.append(_c("B2", "La emisión es anterior a la demanda", OK,
                    f"Emisión {f_emi.isoformat()}, no posterior a hoy (no se cargó la fecha de la demanda)."))

    docs = [(lado, g(f"{lado}.ejecutado_documento")) for lado in ("demanda", "boleta")]
    if not any(v for _, v in docs):
        r.append(_c("B3", "CUIT/CUIL/DNI del ejecutado válido", FALTA, "No hay documento del ejecutado."))
    else:
        malos = []
        for lado, v in docs:
            if not v:
                continue
            d = solo_digitos(v)
            if len(d) == 11:
                if not cuit_valido(d):
                    malos.append(f"{lado}: {d} (CUIT/CUIL con dígito verificador inválido)")
            elif not 7 <= len(d) <= 8:
                malos.append(f"{lado}: {d} (no es CUIT/CUIL de 11 dígitos ni DNI de 7 u 8)")
        r.append(_c("B3", "CUIT/CUIL/DNI del ejecutado válido", OBSERVAR if malos else OK,
                    "; ".join(malos) if malos else "Documento con formato y dígito verificador correctos (CUIT, CUIL o DNI, indistinto)."))

    cap = g("boleta.monto_capital") or g("demanda.monto_capital")
    tot = g("demanda.monto_total") or g("boleta.monto_total")
    if cap is None or tot is None:
        r.append(_c("B4", "El total es mayor o igual que el capital", FALTA, "Falta el capital o el total."))
    else:
        mc, mt = parse_monto(cap), parse_monto(tot)
        r.append(_c("B4", "El total es mayor o igual que el capital", OK if mt >= mc else OBSERVAR,
                    f"Total {mt:.2f}, capital {mc:.2f}." + ("" if mt >= mc else " El total es menor que el capital.")))

    per = parse_periodos(g("boleta.periodos") or g("demanda.periodos"))
    if not per:
        r.append(_c("B5", "No hay períodos futuros", FALTA, "No constan períodos."))
    else:
        tope = fecha_hoy.strftime("%Y-%m")
        fut = [p for p in per if p > tope]
        post = [p for p in per if f_emi and p > f_emi.strftime("%Y-%m")]
        if fut:
            r.append(_c("B5", "No hay períodos futuros", OBSERVAR, f"Períodos posteriores a hoy ({tope}): {', '.join(fut)}."))
        elif post:
            r.append(_c("B5", "No hay períodos futuros", OBSERVAR, f"Períodos posteriores a la emisión de la boleta: {', '.join(post)}."))
        else:
            r.append(_c("B5", "No hay períodos futuros", OK,
                        f"{len(per)} período(s), de {per[0]} a {per[-1]}; ninguno posterior a hoy ni a la emisión."))

    if per:
        años = (fecha_hoy.year - int(per[0][:4])) + (fecha_hoy.month - int(per[0][5:])) / 12
        r.append(_c("B6", "Prescripción", MANUAL,
                    f"Decide el juez. Período más antiguo {per[0]}, más moderno {per[-1]}; hoy {fecha_hoy.isoformat()} "
                    f"(unos {años:.1f} años desde el más antiguo). Organismo: {org or 'sin definir'}."))
    else:
        r.append(_c("B6", "Prescripción", MANUAL, "Decide el juez. Sin períodos cargados no hay datos para orientar."))

    puntos = [("nombre/razón social y domicilio del deudor", g("boleta.ejecutado_nombre") and g("boleta.ejecutado_domicilio")),
              ("períodos adeudados", per), ("concepto", g("boleta.concepto")), ("importe", cap),
              ("número y fecha de emisión", num and fe)]
    faltan_b = [n for n, v in puntos if not v]
    r.append(_c("B7", "Habilidad del título (art. 574 CPCCT, control de oficio)", MANUAL,
                "Decide el juez. Constan en la boleta: " + ", ".join(n for n, v in puntos if v) + "."
                + (f" No constan: {', '.join(faltan_b)}." if faltan_b else "")
                + " Verificar a mano la firma del funcionario competente y el lugar de emisión (no se detectan)."))

    # C. Vía y partes
    if org is None:
        r.append(_c("C1", "La vía corresponde al organismo", FALTA, "No se determinó el organismo (SAT, Municipalidad o DGR)."))
    else:
        r.append(_c("C1", "La vía corresponde al organismo", OK,
                    f"{org}: {ORGANISMOS[org][0]}. El constructor redacta la vía del cobro ejecutivo monitorio."))

    eje = g("demanda.ejecutante") or g("boleta.ejecutante")
    if not eje:
        r.append(_c("C2", "Ejecutante coherente con el organismo", FALTA, "Falta el ejecutante."))
    elif org is None:
        r.append(_c("C2", "Ejecutante coherente con el organismo", OBSERVAR, "Sin organismo no se puede contrastar."))
    else:
        pal = set(palabras(eje))
        residuos = [_RESIDUOS[k] for k in _RESIDUOS if k in pal and _RESIDUOS[k] != org]
        if ORGANISMOS[org][1] & pal and not residuos:
            r.append(_c("C2", "Ejecutante coherente con el organismo", OK, f"La denominación del ejecutante es la de {org}."))
        else:
            r.append(_c("C2", "Ejecutante coherente con el organismo", OBSERVAR,
                        f"La denominación del ejecutante ({eje}) no se corresponde con {org}"
                        + (f" y parece de {', '.join(residuos)}" if residuos else "") + "."))

    # D. Representación
    nom, mat = g("demanda.letrado_nombre"), g("demanda.letrado_matricula")
    if nom and mat:
        r.append(_c("D1", "El letrado tiene matrícula", OK, "Constan nombre y matrícula."))
    else:
        r.append(_c("D1", "El letrado tiene matrícula", FALTA,
                    "Falta: " + ", ".join(n for n, v in (("nombre del letrado", nom), ("matrícula o T°/F° del C.A.T.", mat)) if not v) + "."))

    # E. Cotejo
    cot = caso.get("cotejo") or cotejar(campos)
    dif = [f["campo"] for f in cot if f["resultado"] == DIFIERE]
    falt = [f["campo"] for f in cot if f["resultado"] == C_FALTA]
    if dif:
        r.append(_c("E1", "Demanda y boleta coinciden", OBSERVAR,
                    "Difieren: " + ", ".join(dif) + (f". Faltan: {', '.join(falt)}." if falt else ".")))
    elif falt:
        r.append(_c("E1", "Demanda y boleta coinciden", FALTA, "Faltan: " + ", ".join(falt) + "."))
    else:
        r.append(_c("E1", "Demanda y boleta coinciden", OK, f"{len(cot)} campos cotejados, todos coinciden."))

    # F. Intereses
    tasa = config.get("tasa_interes")
    if tasa:
        r.append(_c("F1", "Tasa de interés definida", OK,
                    f"Tasa: {tasa}. Es idéntica en considerando y resuelvo (la plantilla usa un solo dato)."))
    else:
        r.append(_c("F1", "Tasa de interés definida", MANUAL,
                    "Decide el juez. Los modelos reales usan tasa activa promedio del BNRA; el modelo propio del juzgado, "
                    "tasa pasiva del BCRA (art. 768 inc. c CCCN). Cargar `tasa_interes` en la configuración."))

    # G. Honorarios
    if str(config.get("honorarios") or "diferir").lower() == "regular":
        if config.get("minimo_cat"):
            r.append(_c("G1", "Honorarios", OK, f"Se regulan (Ley 5.480) con mínimo C.A.T. {config['minimo_cat']}."))
        else:
            r.append(_c("G1", "Honorarios", MANUAL,
                        "Se regulan (Ley 5.480), pero falta el mínimo de la consulta escrita del C.A.T. (`minimo_cat`)."))
    else:
        r.append(_c("G1", "Honorarios", OK, "Se difiere la regulación (leyes 5.233 y 6.059), como en los modelos reales."))

    # H. Confirmación
    sin_conf = sorted(n for n, c in campos.items()
                      if isinstance(c, dict) and c.get("valor") is not None and not c.get("confirmado"))
    if sin_conf:
        r.append(_c("H1", "Todos los datos confirmados por una persona", FALTA,
                    f"{len(sin_conf)} campo(s) sin confirmar: " + ", ".join(sin_conf[:8]) + ("…" if len(sin_conf) > 8 else "") + "."))
    else:
        r.append(_c("H1", "Todos los datos confirmados por una persona", OK, "Todos los campos con valor están confirmados."))
    return r
