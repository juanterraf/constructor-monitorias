#!/usr/bin/env python3
"""Servidor local del constructor de sentencias monitorias.

Solo biblioteca estándar. Escucha únicamente en 127.0.0.1. Sin IA, sin internet.
Las funciones de motor/ se importan dentro de cada pedido: si falta una,
la ruta responde 503 con un mensaje claro y el resto sigue andando.
Por consola solo salen ids, estados y tiempos: nunca datos de los expedientes.
"""
import base64
import binascii
import importlib
import io
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

VERSION = "1.0"
HOST = "127.0.0.1"
PUERTO = 8765
BASE = Path(__file__).resolve().parent
WEB = BASE / "web"
CASOS = BASE / "casos"
CONFIG = BASE / "config.local.json"
MAX_CUERPO = 400 * 1024 * 1024
TRABAJADORES = 3
HOSTS_OK = ("127.0.0.1", "localhost")

if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

CONFIG_BASE = {
    "unidad_judicial": "",
    "centro_judicial": "",
    "ciudad": "San Miguel de Tucumán",
    "proximo_nro_sentencia": 1,
    "tasa_interes": "",
    "cuenta_judicial": "",
    "martillero": "",
    "presupuesto_pct": None,
    "honorarios": {
        "modo": "regular",
        "pct_art14": 16,
        "multiplicador": 1.55,
        "reduccion": True,
        "minimo_cat": None,
    },
}

_cerrojo = threading.RLock()
_pool = None


# ---------------------------------------------------------------- errores
class ApiError(Exception):
    def __init__(self, estado, mensaje, extra=None):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje
        self.extra = extra or {}


class MotorFaltante(Exception):
    pass


def motor(modulo, funcion):
    """Trae una función de motor/ recién cuando se la necesita."""
    try:
        mod = importlib.import_module("motor." + modulo)
        return getattr(mod, funcion)
    except (ImportError, AttributeError) as e:
        raise MotorFaltante(
            "Falta motor/%s.py (%s) o no se pudo cargar: %s" % (modulo, funcion, e)
        )


def log(*partes):
    print(time.strftime("%H:%M:%S"), *partes, flush=True)


# ---------------------------------------------------------------- configuración
def leer_config():
    cfg = json.loads(json.dumps(CONFIG_BASE))
    try:
        if CONFIG.exists():
            guardada = json.loads(CONFIG.read_text(encoding="utf-8"))
            for k, v in guardada.items():
                if k == "honorarios" and isinstance(v, dict):
                    cfg["honorarios"].update(v)
                elif k in cfg:
                    cfg[k] = v
    except (OSError, ValueError):
        pass
    return cfg


def _escribir_config(cfg):
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG)


def _numero(v, nombre, entero=False, nulo=False):
    if v is None or v == "":
        if nulo:
            return None
        raise ApiError(400, "%s tiene que ser un número." % nombre)
    try:
        n = Decimal(str(v).replace(",", "."))
    except InvalidOperation:
        raise ApiError(400, "%s tiene que ser un número." % nombre)
    if n < 0:
        raise ApiError(400, "%s no puede ser negativo." % nombre)
    return int(n) if entero else float(n)


def guardar_config(nueva):
    if not isinstance(nueva, dict):
        raise ApiError(400, "La configuración tiene que ser un objeto.")
    with _cerrojo:
        cfg = leer_config()
        for k in ("unidad_judicial", "centro_judicial", "ciudad", "tasa_interes", "cuenta_judicial", "martillero"):
            if k in nueva:
                cfg[k] = str(nueva[k] or "").strip()
        if "proximo_nro_sentencia" in nueva:
            cfg["proximo_nro_sentencia"] = _numero(
                nueva["proximo_nro_sentencia"], "El próximo número", entero=True
            )
        if "presupuesto_pct" in nueva:
            cfg["presupuesto_pct"] = _numero(nueva["presupuesto_pct"], "El porcentaje del presupuesto", nulo=True)
        h = nueva.get("honorarios")
        if isinstance(h, dict):
            if "pct_art14" in h:
                cfg["honorarios"]["pct_art14"] = _numero(h["pct_art14"], "El porcentaje del art. 14")
            if "multiplicador" in h:
                cfg["honorarios"]["multiplicador"] = _numero(h["multiplicador"], "El multiplicador")
            if "reduccion" in h:
                cfg["honorarios"]["reduccion"] = bool(h["reduccion"])
            if h.get("modo") in ("regular", "diferir"):
                cfg["honorarios"]["modo"] = h["modo"]
            if "minimo_cat" in h:
                cfg["honorarios"]["minimo_cat"] = _numero(h["minimo_cat"], "El mínimo del C.A.T.", nulo=True)
        _escribir_config(cfg)
        return cfg


# ---------------------------------------------------------------- casos en disco
_ID = re.compile(r"^c-\d{4,}$")


def carpeta(id_):
    if not _ID.match(id_ or ""):
        raise ApiError(404, "No existe ese caso.")
    return CASOS / id_


def cargar(id_):
    ruta = carpeta(id_) / "caso.json"
    with _cerrojo:
        if not ruta.exists():
            raise ApiError(404, "No existe ese caso.")
        return json.loads(ruta.read_text(encoding="utf-8"))


def guardar(caso):
    d = carpeta(caso["id"])
    with _cerrojo:
        if not d.exists():
            raise ApiError(404, "El caso se borró.")
        tmp = d / "caso.json.tmp"
        tmp.write_text(json.dumps(caso, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, d / "caso.json")


def ahora():
    return datetime.now().isoformat(timespec="seconds")


def nuevo_caso(archivos):
    """archivos: lista de (nombre, bytes). Crea la carpeta, guarda los originales."""
    with _cerrojo:
        CASOS.mkdir(exist_ok=True)
        mayor = 0
        for p in CASOS.iterdir():
            m = re.match(r"^c-(\d+)$", p.name)
            if m:
                mayor = max(mayor, int(m.group(1)))
        id_ = "c-%04d" % (mayor + 1)
        d = CASOS / id_
        (d / "originales").mkdir(parents=True)
        (d / "paginas").mkdir()
        nombres = []
        for nombre, datos in archivos:
            limpio = re.sub(r"[^\w.\- ]", "_", Path(nombre).name) or "archivo.pdf"
            if not limpio.lower().endswith(".pdf"):
                limpio += ".pdf"
            base, n = limpio, 1
            while limpio in nombres:
                n += 1
                limpio = "%s-%d.pdf" % (base[:-4], n)
            (d / "originales" / limpio).write_bytes(datos)
            nombres.append(limpio)
        caso = {
            "id": id_,
            "creado": ahora(),
            "estado": "procesando",
            "archivos": nombres,
            "paginas": [],
            "organismo": {"valor": None},
            "campos": {},
            "cotejo": [],
            "chequeos": [],
            "honorarios": {},
            "sentencia": {"archivo": None, "generada": None},
        }
        guardar(caso)
        return caso


def decodificar_archivos(cuerpo):
    lista = cuerpo.get("archivos") if isinstance(cuerpo, dict) else None
    if not isinstance(lista, list) or not lista:
        raise ApiError(400, "Falta la lista de archivos.")
    salida = []
    for a in lista:
        if not isinstance(a, dict) or not isinstance(a.get("base64"), str):
            raise ApiError(400, "Cada archivo lleva nombre y base64.")
        try:
            datos = base64.b64decode(a["base64"], validate=False)
        except (binascii.Error, ValueError):
            raise ApiError(400, "Un archivo no se pudo decodificar.")
        if not datos.lstrip()[:5] == b"%PDF-":
            raise ApiError(400, "«%s» no es un PDF." % str(a.get("nombre", "archivo"))[:80])
        salida.append((str(a.get("nombre") or "expediente.pdf"), datos))
    return salida


# ---------------------------------------------------------------- derivados del caso
def valor(caso, clave):
    c = caso.get("campos", {}).get(clave)
    return c.get("valor") if isinstance(c, dict) else None


def caratula(caso):
    v = valor(caso, "demanda.caratula")
    return v if v else "(sin carátula)"


def pendientes(caso):
    return [k for k, c in caso.get("campos", {}).items() if not c.get("confirmado")]


def resumen_cotejo(caso):
    r = {"COINCIDE": 0, "DIFIERE": 0, "FALTA": 0}
    for f in caso.get("cotejo") or []:
        if f.get("resultado") in r:
            r[f["resultado"]] += 1
    return r


def resumen(caso):
    campos = caso.get("campos", {})
    org = caso.get("organismo") or {}
    return {
        "id": caso["id"],
        "caratula": caratula(caso),
        "organismo": org.get("valor") if isinstance(org, dict) else None,
        "estado": caso.get("estado"),
        "error": caso.get("error"),
        "paginas": len(caso.get("paginas", [])),
        "confirmados": sum(1 for c in campos.values() if c.get("confirmado")),
        "total": len(campos),
        "cotejo": resumen_cotejo(caso),
        "generada": (caso.get("sentencia") or {}).get("generada"),
    }


def motivos_bloqueo(caso):
    m = []
    pend = pendientes(caso)
    if pend:
        m.append("Falta confirmar %d campo%s: %s." % (
            len(pend), "" if len(pend) == 1 else "s", ", ".join(pend)))
    for f in caso.get("cotejo") or []:
        if f.get("resultado") in ("DIFIERE", "FALTA"):
            m.append("Cotejo %s: %s." % (f["resultado"], f.get("campo", "?")))
    for c in caso.get("chequeos") or []:
        if c.get("resultado") == "FALTA":
            m.append("Chequeo con falta: %s." % (c.get("titulo") or c.get("id")))
    return m


def calcular_honorarios(caso, cfg):
    base = valor(caso, "demanda.monto_total") or valor(caso, "demanda.monto_capital")
    try:
        base = Decimal(str(base))
    except (InvalidOperation, TypeError):
        return {"error": "No hay un monto para calcular los honorarios."}
    h = cfg.get("honorarios", {})
    try:
        calcular = motor("honorarios", "calcular")
        return calcular(
            base,
            reduccion=h.get("reduccion", True),
            pct_art14=h.get("pct_art14", 16),
            multiplicador=h.get("multiplicador", 1.55),
            minimo_cat=h.get("minimo_cat"),
        )
    except MotorFaltante as e:
        return {"error": str(e)}
    except Exception as e:  # el cálculo no tumba el chequeo
        return {"error": "No se pudo calcular (%s)." % type(e).__name__}


def juzgado_al_dia(caso, cfg):
    """Los datos del juzgado vacíos se toman de la configuración vigente: si se configuró después de subir
    el expediente, no hay que volver a cargarlo. La configuración ya es una decisión de una persona."""
    for campo, clave in (("juzgado.unidad", "unidad_judicial"), ("juzgado.centro", "centro_judicial")):
        c = caso["campos"].setdefault(campo, {"valor": None, "confirmado": False, "candidatos": []})
        if c.get("valor") in (None, "") and cfg.get(clave):
            c["valor"], c["confirmado"] = cfg[clave], True


def evaluar(caso, cfg):
    """Cotejo, chequeos y honorarios. Deja el estado al día."""
    juzgado_al_dia(caso, cfg)
    caso["cotejo"] = motor("cotejo", "cotejar")(caso["campos"])
    caso["chequeos"] = motor("chequeos", "chequear")(caso, cfg)
    caso["honorarios"] = calcular_honorarios(caso, cfg)
    if not caso["campos"] or pendientes(caso):
        caso["estado"] = "detectado"
    elif motivos_bloqueo(caso):
        caso["estado"] = "observado"
    else:
        caso["estado"] = "chequeado"


# ---------------------------------------------------------------- procesamiento
def _normalizar_campos(campos, cfg):
    salida = {}
    for k, c in (campos or {}).items():
        c = dict(c) if isinstance(c, dict) else {"valor": c}
        c.setdefault("candidatos", [])
        if "valor" not in c:
            cands = sorted(c["candidatos"], key=lambda x: x.get("confianza") or 0, reverse=True)
            c["valor"] = cands[0].get("valor") if cands else None
        c["confirmado"] = False
        salida[k] = c
    # lo del juzgado sale de la configuración y la persona lo confirma
    prev = {
        "juzgado.unidad": cfg.get("unidad_judicial") or None,
        "juzgado.centro": cfg.get("centro_judicial") or None,
        "juzgado.nro_sentencia": str(cfg.get("proximo_nro_sentencia") or "") or None,
        "juzgado.fecha_sentencia": date.today().isoformat(),
    }
    for k, v in prev.items():
        if k not in salida:
            salida[k] = {"valor": v, "confirmado": False, "candidatos": []}
    # el número se asigna al generar si la persona no lo toca
    salida["juzgado.nro_sentencia"].setdefault("auto", salida["juzgado.nro_sentencia"]["valor"] is not None)
    return salida


def _leer_paginas(caso, d):
    leer_pdf = motor("leer", "leer_pdf")
    try:
        ocr_ok = bool(motor("ocr", "ocr_disponible")()[0])
    except MotorFaltante:
        ocr_ok = False
    paginas, n = [], 0
    for nombre in caso["archivos"]:
        tmp = d / "_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            pags = leer_pdf(str(d / "originales" / nombre), str(tmp), ocr=ocr_ok)
            for p in pags:
                n += 1
                p = dict(p)
                p["archivo"] = nombre
                img = p.get("imagen")
                if img:
                    src = Path(img)
                    if not src.is_absolute():
                        src = tmp / img
                    if src.exists():
                        dest = d / "paginas" / ("p%03d.png" % n)
                        shutil.move(str(src), str(dest))
                        p["imagen"] = "paginas/" + dest.name
                    else:
                        p["imagen"] = None
                p["n"] = n
                paginas.append(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return paginas


def procesar(id_):
    t0 = time.time()
    try:
        caso = cargar(id_)
        d = carpeta(id_)
        cfg = leer_config()
        paginas = _leer_paginas(caso, d)
        paginas = motor("detectar", "clasificar_paginas")(paginas) or paginas
        det = motor("detectar", "detectar")(paginas) or {}
        caso["paginas"] = paginas
        caso["organismo"] = det.get("organismo") or {"valor": None}
        caso["campos"] = _normalizar_campos(det.get("campos"), cfg)
        caso["estado"] = "detectado"
        caso.pop("error", None)
        caso.pop("error_tipo", None)
        guardar(caso)
    except MotorFaltante as e:
        _marcar_error(id_, str(e), "motor")
    except ApiError:
        pass
    except Exception as e:
        _marcar_error(id_, "No se pudo leer el expediente (%s)." % type(e).__name__, "lectura")
    estado = "?"
    try:
        estado = cargar(id_)["estado"]
    except ApiError:
        estado = "borrado"
    log("[%s] %s en %.1fs" % (id_, estado, time.time() - t0))


def _marcar_error(id_, mensaje, tipo):
    try:
        caso = cargar(id_)
        caso["estado"] = "error"
        caso["error"] = mensaje
        caso["error_tipo"] = tipo
        guardar(caso)
    except ApiError:
        pass


def pool():
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=TRABAJADORES)
    return _pool


# ---------------------------------------------------------------- generación
def asignar_numero(caso):
    """Si el número sigue siendo el automático, toma el próximo de la configuración."""
    c = caso["campos"].get("juzgado.nro_sentencia")
    if not c or not c.get("auto"):
        return
    with _cerrojo:
        cfg = leer_config()
        c["valor"] = str(cfg["proximo_nro_sentencia"])
        cfg["proximo_nro_sentencia"] = int(cfg["proximo_nro_sentencia"]) + 1
        _escribir_config(cfg)
    c["auto"] = False


def generar(id_):
    caso = cargar(id_)
    cfg = leer_config()
    evaluar(caso, cfg)
    m = motivos_bloqueo(caso)
    if m:
        guardar(caso)
        raise ApiError(409, "Todavía no se puede generar.", {"motivos": m})
    generar_docx = motor("redactar", "generar_docx")
    asignar_numero(caso)
    ruta = carpeta(id_) / "sentencia.docx"
    generar_docx(caso, cfg, str(ruta))
    caso["sentencia"] = {"archivo": "sentencia.docx", "generada": ahora()}
    caso["estado"] = "generado"
    guardar(caso)
    return caso


def generar_lote():
    casos = []
    with _cerrojo:
        if CASOS.exists():
            for p in sorted(CASOS.iterdir()):
                if _ID.match(p.name) and (p / "caso.json").exists():
                    casos.append(p.name)
    memoria = io.BytesIO()
    hechas, omitidas = [], {}
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        for id_ in casos:
            try:
                caso = cargar(id_)
                if caso.get("estado") in ("error", "procesando"):
                    omitidas[id_] = ["No está procesado."]
                    continue
                ruta = carpeta(id_) / "sentencia.docx"
                if not (caso.get("estado") == "generado" and ruta.exists()):
                    caso = generar(id_)
                z.write(ruta, "sentencia-%s.docx" % id_)
                hechas.append(id_)
            except ApiError as e:
                omitidas[id_] = e.extra.get("motivos") or [e.mensaje]
            except MotorFaltante:
                raise
            except Exception as e:
                omitidas[id_] = ["Falló la generación (%s)." % type(e).__name__]
        if omitidas:
            lineas = ["Casos que no se generaron:", ""]
            for id_, ms in omitidas.items():
                lineas.append(id_)
                lineas.extend("  - " + x for x in ms)
            z.writestr("OMITIDAS.txt", "\n".join(lineas))
    if not hechas:
        raise ApiError(409, "No hay casos listos para generar.", {"omitidas": omitidas})
    return memoria.getvalue(), hechas, omitidas


# ---------------------------------------------------------------- rutas
class Binario:
    def __init__(self, datos, tipo, nombre=None, extra=None):
        self.datos, self.tipo, self.nombre, self.extra = datos, tipo, nombre, extra or {}


def r_estado(h, m, cuerpo):
    try:
        ok, motivo = motor("ocr", "ocr_disponible")()
    except MotorFaltante as e:
        ok, motivo = False, str(e)
    return 200, {"version": VERSION, "ocr": {"disponible": bool(ok), "motivo": motivo},
                 "config": leer_config()}


def r_config(h, m, cuerpo):
    return 200, guardar_config(cuerpo)


def r_crear(h, m, cuerpo):
    archivos = decodificar_archivos(cuerpo)
    caso = nuevo_caso(archivos)
    procesar(caso["id"])
    caso = cargar(caso["id"])
    if caso.get("error_tipo") == "motor":
        raise ApiError(503, caso["error"], {"id": caso["id"]})
    return 201, caso


def r_lote(h, m, cuerpo):
    archivos = decodificar_archivos(cuerpo)
    ids = []
    for a in archivos:
        c = nuevo_caso([a])
        ids.append(c["id"])
        pool().submit(procesar, c["id"])
    return 202, {"ids": ids}


def r_listar(h, m, cuerpo):
    salida = []
    with _cerrojo:
        ids = sorted(p.name for p in CASOS.iterdir() if _ID.match(p.name)) if CASOS.exists() else []
    for id_ in ids:
        try:
            salida.append(resumen(cargar(id_)))
        except (ApiError, ValueError):
            continue
    return 200, {"casos": salida}


def r_caso(h, m, cuerpo):
    return 200, cargar(m.group(1))


def r_campos(h, m, cuerpo):
    if not isinstance(cuerpo, dict):
        raise ApiError(400, "Se espera un objeto con los campos.")
    caso = cargar(m.group(1))
    if caso.get("estado") in ("procesando", "error"):
        raise ApiError(409, "El caso no está listo.")
    campos = caso["campos"]
    for clave, v in cuerpo.items():
        if not isinstance(v, dict) or not re.match(r"^(demanda|boleta|juzgado)\.\w+$", clave):
            raise ApiError(400, "Campo inválido: %s" % clave)
        c = campos.setdefault(clave, {"valor": None, "confirmado": False, "candidatos": []})
        if "valor" in v:
            nuevo = v["valor"]
            if isinstance(nuevo, str):
                nuevo = nuevo.strip() or None
            if nuevo != c.get("valor"):
                c["valor"] = nuevo
                c["confirmado"] = False
                c.pop("auto", None)
        if "confirmado" in v:
            c["confirmado"] = bool(v["confirmado"])
    if caso["estado"] in ("generado", "chequeado", "observado", "confirmado", "detectado"):
        caso["estado"] = "confirmado" if campos and not pendientes(caso) else "detectado"
        if caso["sentencia"].get("generada"):
            caso["sentencia"] = {"archivo": None, "generada": None}
    guardar(caso)
    return 200, caso


def r_chequear(h, m, cuerpo):
    caso = cargar(m.group(1))
    if caso.get("estado") in ("procesando", "error"):
        raise ApiError(409, "El caso no está listo.")
    evaluar(caso, leer_config())
    guardar(caso)
    return 200, {"cotejo": caso["cotejo"], "chequeos": caso["chequeos"],
                 "honorarios": caso["honorarios"], "estado": caso["estado"],
                 "motivos": motivos_bloqueo(caso)}


def r_generar(h, m, cuerpo):
    caso = generar(m.group(1))
    return 200, {"ok": True, "estado": caso["estado"],
                 "descarga": "/api/casos/%s/sentencia" % caso["id"]}


def r_vista(h, m, cuerpo):
    caso = cargar(m.group(1))
    if not caso.get("campos"):
        raise ApiError(409, "El caso no está listo.")
    return 200, {"parrafos": motor("redactar", "armar_cuerpo")(caso, leer_config())}


def r_pagina(h, m, cuerpo):
    caso = cargar(m.group(1))
    n = int(m.group(2))
    for p in caso.get("paginas", []):
        if p.get("n") == n and p.get("imagen"):
            ruta = (carpeta(caso["id"]) / p["imagen"]).resolve()
            if carpeta(caso["id"]).resolve() in ruta.parents and ruta.exists():
                return 200, Binario(ruta.read_bytes(), "image/png")
    raise ApiError(404, "No hay imagen de esa página.")


def r_sentencia(h, m, cuerpo):
    ruta = carpeta(m.group(1)) / "sentencia.docx"
    if not ruta.exists():
        raise ApiError(404, "Todavía no se generó la sentencia.")
    return 200, Binario(
        ruta.read_bytes(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "sentencia-%s.docx" % m.group(1))


def r_lote_generar(h, m, cuerpo):
    datos, hechas, omitidas = generar_lote()
    return 200, Binario(datos, "application/zip", "sentencias.zip",
                        {"X-Generadas": str(len(hechas)), "X-Omitidas": str(len(omitidas))})


def r_borrar(h, m, cuerpo):
    d = carpeta(m.group(1))
    with _cerrojo:
        if not d.exists():
            raise ApiError(404, "No existe ese caso.")
        shutil.rmtree(d, ignore_errors=True)
    return 200, {"ok": True}


RUTAS = [
    ("GET", r"/api/estado", r_estado),
    ("PUT", r"/api/config", r_config),
    ("POST", r"/api/casos", r_crear),
    ("POST", r"/api/lote", r_lote),
    ("POST", r"/api/lote/generar", r_lote_generar),
    ("GET", r"/api/casos", r_listar),
    ("GET", r"/api/casos/([^/]+)", r_caso),
    ("PUT", r"/api/casos/([^/]+)/campos", r_campos),
    ("POST", r"/api/casos/([^/]+)/chequear", r_chequear),
    ("POST", r"/api/casos/([^/]+)/generar", r_generar),
    ("GET", r"/api/casos/([^/]+)/vista", r_vista),
    ("GET", r"/api/casos/([^/]+)/pagina/(\d+)", r_pagina),
    ("GET", r"/api/casos/([^/]+)/sentencia", r_sentencia),
    ("DELETE", r"/api/casos/([^/]+)", r_borrar),
]
RUTAS = [(met, re.compile("^" + pat + "$"), fn) for met, pat, fn in RUTAS]


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ConstructorMonitorias/" + VERSION

    def log_message(self, formato, *args):
        pass  # el log propio no lleva datos

    # -- respuestas
    def _enviar(self, estado, datos, tipo, extra=None):
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(datos)

    def _json(self, estado, obj):
        datos = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self._enviar(estado, datos, "application/json; charset=utf-8")

    # -- seguridad básica: solo pedidos de la propia máquina
    def _origen_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in HOSTS_OK:
            return False
        origen = self.headers.get("Origin")
        if origen and urlsplit(origen).hostname not in HOSTS_OK:
            return False
        return True

    def _despachar(self):
        t0 = time.time()
        estado = 500
        try:
            if not self._origen_ok():
                estado = 403
                return self._json(403, {"error": "Pedido no permitido."})
            ruta = unquote(urlsplit(self.path).path)
            if not ruta.startswith("/api/"):
                if self.command not in ("GET", "HEAD"):
                    estado = 405
                    return self._json(405, {"error": "Método no permitido."})
                estado = self._estatico(ruta)
                return
            cuerpo = None
            if self.command in ("POST", "PUT"):
                cuerpo = self._leer_json()
            for met, patron, fn in RUTAS:
                m = patron.match(ruta)
                if m and met == self.command:
                    estado, res = fn(self, m, cuerpo)
                    if isinstance(res, Binario):
                        extra = dict(res.extra)
                        if res.nombre:
                            extra["Content-Disposition"] = 'attachment; filename="%s"' % res.nombre
                        return self._enviar(estado, res.datos, res.tipo, extra)
                    return self._json(estado, res)
            estado = 404
            self._json(404, {"error": "No existe esa ruta."})
        except ApiError as e:
            estado = e.estado
            self._json(e.estado, dict(e.extra, error=e.mensaje))
        except MotorFaltante as e:
            estado = 503
            self._json(503, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError):
            estado = 0
        except Exception as e:
            estado = 500
            log("error interno:", type(e).__name__)
            try:
                self._json(500, {"error": "Error interno (%s)." % type(e).__name__})
            except OSError:
                pass
        finally:
            if self.path.startswith("/api/") and self.command != "GET":
                ids = re.findall(r"c-\d{4,}", self.path)
                log(self.command, re.sub(r"/pagina/\d+", "", urlsplit(self.path).path), estado,
                    "%.2fs" % (time.time() - t0), *ids[:0])

    def _leer_json(self):
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Largo inválido.")
        if largo > MAX_CUERPO:
            raise ApiError(413, "El pedido es demasiado grande.")
        crudo = self.rfile.read(largo) if largo else b""
        if not crudo:
            return {}
        try:
            return json.loads(crudo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "El cuerpo no es JSON válido.")

    def _estatico(self, ruta):
        if ruta in ("", "/"):
            ruta = "/index.html"
        destino = (WEB / ruta.lstrip("/")).resolve()
        if WEB.resolve() not in destino.parents or not destino.is_file():
            self._json(404, {"error": "No existe."})
            return 404
        tipo = mimetypes.guess_type(destino.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            tipo += "; charset=utf-8"
        self._enviar(200, destino.read_bytes(), tipo)
        return 200

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _despachar


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def crear_servidor(puerto=PUERTO):
    """Siempre en 127.0.0.1: nunca en otra interfaz."""
    return Servidor((HOST, puerto), Manejador)


def main():
    CASOS.mkdir(exist_ok=True)
    try:
        srv = crear_servidor(PUERTO)
    except OSError:
        log("No se pudo abrir el puerto %d. ¿Ya está corriendo?" % PUERTO)
        sys.exit(1)
    log("Constructor de monitorias en http://%s:%d (solo esta computadora)" % (HOST, PUERTO))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("Cerrando.")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
