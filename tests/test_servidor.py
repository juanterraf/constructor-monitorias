"""Pruebas del servidor local, con motor/ simulado. Datos 100 % inventados."""
import base64
import http.client
import json
import sys
import tempfile
import threading
import time
import types
import unittest
import zipfile
import io
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import servidor  # noqa: E402

PDF = base64.b64encode(b"%PDF-1.4 inventado").decode()


def _campo(valor, pagina=1, origen="texto", conf=0.9):
    return {"valor": valor, "confirmado": False, "candidatos": [
        {"valor": valor, "pagina": pagina, "cita": "cita " + str(valor), "origen": origen,
         "confianza": conf, "regla": "prueba"}]}


def motor_falso(cotejo="COINCIDE"):
    def modulo(nombre, **funciones):
        m = types.ModuleType("motor." + nombre)
        for k, v in funciones.items():
            setattr(m, k, v)
        return m

    def generar_docx(caso, config, ruta):
        Path(ruta).write_bytes(b"PK docx falso")
        return ruta

    return {
        "motor.leer": modulo("leer", leer_pdf=lambda ruta, carpeta, ocr=True: [
            {"n": 1, "origen": "texto", "confianza_ocr": None, "tipo": "otro", "imagen": None, "texto": "a"},
            {"n": 2, "origen": "texto", "confianza_ocr": None, "tipo": "otro", "imagen": None, "texto": "b"}]),
        "motor.ocr": modulo("ocr", ocr_disponible=lambda: (False, "sin tesseract")),
        "motor.detectar": modulo(
            "detectar",
            clasificar_paginas=lambda p: p,
            detectar=lambda p: {
                "organismo": {"valor": "SAT", "pagina": 1, "cita": "x", "confianza": 0.9},
                "campos": {"demanda.caratula": _campo("PEREZ c/ GOMEZ"),
                           "demanda.monto_capital": _campo("1000.00"),
                           "boleta.monto_capital": _campo("1000.00", origen="ocr", conf=0.6)}}),
        "motor.cotejo": modulo("cotejo", cotejar=lambda campos: [
            {"campo": "monto_capital", "demanda": "1000.00", "boleta": "1000.00",
             "resultado": cotejo, "detalle": ""}]),
        "motor.chequeos": modulo("chequeos", chequear=lambda caso, cfg: [
            {"id": "A", "titulo": "Título hábil", "resultado": "OK", "detalle": ""}]),
        "motor.honorarios": modulo("honorarios", calcular=lambda base, **kw: {"total": str(base)}),
        "motor.redactar": modulo(
            "redactar",
            armar_cuerpo=lambda caso, cfg: [{"texto": "Resuelvo", "estilo": "resuelvo"}],
            generar_docx=generar_docx),
    }


class Base(unittest.TestCase):
    cotejo = "COINCIDE"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.parches = [
            mock.patch.object(servidor, "CASOS", t / "casos"),
            mock.patch.object(servidor, "CONFIG", t / "config.local.json"),
            mock.patch.dict(sys.modules, motor_falso(self.cotejo)),
        ]
        for p in self.parches:
            p.start()
        self.srv = servidor.crear_servidor(0)
        self.puerto = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        for p in reversed(self.parches):
            p.stop()
        self.tmp.cleanup()

    def pedir(self, metodo, ruta, cuerpo=None, host=None):
        con = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        datos = json.dumps(cuerpo) if cuerpo is not None else None
        cab = {"Content-Type": "application/json"}
        if host:
            cab["Host"] = host
        con.request(metodo, ruta, body=datos, headers=cab)
        r = con.getresponse()
        crudo = r.read()
        con.close()
        if r.getheader("Content-Type", "").startswith("application/json"):
            return r.status, json.loads(crudo)
        return r.status, crudo

    def crear(self):
        st, caso = self.pedir("POST", "/api/casos", {"archivos": [{"nombre": "exp.pdf", "base64": PDF}]})
        self.assertEqual(st, 201)
        return caso

    def confirmar_todo(self, caso):
        cambios = {k: {"confirmado": True} for k in caso["campos"]}
        st, caso = self.pedir("PUT", "/api/casos/%s/campos" % caso["id"], cambios)
        self.assertEqual(st, 200)
        return caso


class TestServidor(Base):
    def test_crear_caso(self):
        caso = self.crear()
        self.assertEqual(caso["id"], "c-0001")
        self.assertEqual(caso["estado"], "detectado")
        self.assertEqual(len(caso["paginas"]), 2)
        self.assertEqual(caso["organismo"]["valor"], "SAT")
        self.assertIn("juzgado.unidad", caso["campos"])
        self.assertTrue((servidor.CASOS / "c-0001" / "caso.json").exists())

    def test_rechaza_lo_que_no_es_pdf(self):
        st, r = self.pedir("POST", "/api/casos", {"archivos": [
            {"nombre": "x.pdf", "base64": base64.b64encode(b"hola").decode()}]})
        self.assertEqual(st, 400)

    def test_listar(self):
        self.crear()
        st, r = self.pedir("GET", "/api/casos")
        self.assertEqual(st, 200)
        self.assertEqual(len(r["casos"]), 1)
        c = r["casos"][0]
        self.assertEqual((c["id"], c["organismo"], c["estado"]), ("c-0001", "SAT", "detectado"))
        self.assertEqual(c["confirmados"], 0)
        self.assertEqual(c["caratula"], "PEREZ c/ GOMEZ")

    def test_confirmar_campos(self):
        caso = self.crear()
        st, caso = self.pedir("PUT", "/api/casos/c-0001/campos", {
            "demanda.monto_capital": {"valor": "1200.50", "confirmado": True}})
        self.assertEqual(st, 200)
        c = caso["campos"]["demanda.monto_capital"]
        self.assertEqual((c["valor"], c["confirmado"]), ("1200.50", True))
        # cambiar el valor sin confirmar deja el campo sin confirmar
        st, caso = self.pedir("PUT", "/api/casos/c-0001/campos", {"demanda.monto_capital": {"valor": "1"}})
        self.assertFalse(caso["campos"]["demanda.monto_capital"]["confirmado"])
        st, _ = self.pedir("PUT", "/api/casos/c-0001/campos", {"raro": {"valor": "1"}})
        self.assertEqual(st, 400)

    def test_generar_bloqueado_si_falta_confirmar(self):
        self.crear()
        st, r = self.pedir("POST", "/api/casos/c-0001/generar")
        self.assertEqual(st, 409)
        self.assertTrue(any("Falta confirmar" in m for m in r["motivos"]))
        self.assertFalse((servidor.CASOS / "c-0001" / "sentencia.docx").exists())

    def test_generar_bloqueado_si_el_cotejo_difiere(self):
        caso = self.crear()
        self.confirmar_todo(caso)
        with mock.patch.dict(sys.modules, motor_falso("DIFIERE")):
            st, r = self.pedir("POST", "/api/casos/c-0001/generar")
        self.assertEqual(st, 409)
        self.assertTrue(any("DIFIERE" in m for m in r["motivos"]))

    def test_generar_con_todo_confirmado(self):
        caso = self.crear()
        self.confirmar_todo(caso)
        st, r = self.pedir("POST", "/api/casos/c-0001/chequear")
        self.assertEqual((st, r["estado"]), (200, "chequeado"))
        self.assertEqual(r["honorarios"], {"total": "1000.00"})
        st, r = self.pedir("POST", "/api/casos/c-0001/generar")
        self.assertEqual((st, r["estado"]), (200, "generado"))
        st, docx = self.pedir("GET", "/api/casos/c-0001/sentencia")
        self.assertEqual((st, docx), (200, b"PK docx falso"))
        st, v = self.pedir("GET", "/api/casos/c-0001/vista")
        self.assertEqual(v["parrafos"][0]["estilo"], "resuelvo")
        # el número de sentencia automático avanzó
        self.assertEqual(servidor.leer_config()["proximo_nro_sentencia"], 2)

    def test_lote(self):
        st, r = self.pedir("POST", "/api/lote", {"archivos": [
            {"nombre": "a.pdf", "base64": PDF}, {"nombre": "b.pdf", "base64": PDF},
            {"nombre": "c.pdf", "base64": PDF}]})
        self.assertEqual(st, 202)
        self.assertEqual(len(r["ids"]), 3)
        for _ in range(100):
            st, lista = self.pedir("GET", "/api/casos")
            if all(c["estado"] != "procesando" for c in lista["casos"]):
                break
            time.sleep(0.1)
        self.assertEqual([c["estado"] for c in lista["casos"]], ["detectado"] * 3)
        # solo el primero queda listo
        self.confirmar_todo({"id": "c-0001", "campos": self.pedir("GET", "/api/casos/c-0001")[1]["campos"]})
        st, datos = self.pedir("POST", "/api/lote/generar")
        self.assertEqual(st, 200)
        z = zipfile.ZipFile(io.BytesIO(datos))
        nombres = z.namelist()
        self.assertIn("sentencia-c-0001.docx", nombres)
        self.assertNotIn("sentencia-c-0002.docx", nombres)
        self.assertIn("OMITIDAS.txt", nombres)

    def test_lote_sin_listas_da_409(self):
        self.crear()
        st, r = self.pedir("POST", "/api/lote/generar")
        self.assertEqual(st, 409)

    def test_motor_faltante_da_503(self):
        caso = self.crear()
        with mock.patch.dict(sys.modules, {"motor.chequeos": None}):
            st, r = self.pedir("POST", "/api/casos/c-0001/chequear")
        self.assertEqual(st, 503)
        self.assertIn("chequeos", r["error"])

    def test_borrar(self):
        self.crear()
        st, _ = self.pedir("DELETE", "/api/casos/c-0001")
        self.assertEqual(st, 200)
        self.assertEqual(self.pedir("GET", "/api/casos/c-0001")[0], 404)

    def test_solo_escucha_en_127_0_0_1(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")
        self.assertEqual(servidor.HOST, "127.0.0.1")
        # y rechaza pedidos con otro Host (rebinding)
        st, _ = self.pedir("GET", "/api/estado", host="ejemplo.com")
        self.assertEqual(st, 403)
        self.assertEqual(self.pedir("GET", "/api/estado")[0], 200)

    def test_no_sale_de_web(self):
        st, _ = self.pedir("GET", "/..%2fservidor.py")
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
