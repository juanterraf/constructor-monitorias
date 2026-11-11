# Constructor de sentencias monitorias · diseño del núcleo

Herramienta local, **sin IA**, para armar sentencias monitorias a partir de la demanda y la boleta de deuda. Alcance de la versión 1: boletas de la **SAT** (Sociedad Aguas del Tucumán), la **Municipalidad** y la **DGR**. El pagaré queda para después.

Este documento es el contrato entre las piezas. Si algo de acá no alcanza, se cambia acá primero.

## Principios

1. **Sin IA.** Todo es regla, código y plantilla. El OCR (Tesseract, local) propone y la persona confirma.
2. **Nada sale de la computadora.** El servidor escucha solo en `127.0.0.1`. Ninguna llamada a internet.
3. **Cada dato con su fuente.** Todo valor detectado lleva página, cita literal, origen (texto u OCR), confianza y regla que lo encontró.
4. **La persona confirma.** Un dato detectado no se usa hasta que alguien lo confirma o lo corrige. La sentencia sale solo con todo confirmado.
5. **Lo que necesita criterio no se inventa.** Queda marcado para completar.
6. **Lo que se ve por consola no lleva datos personales**: solo ids, conteos y estados.

## Flujo

```
1 DETECTAR   PDF ─► páginas (texto nativo · OCR si es escaneo) ─► tipo de página ─► candidatos por campo
2 CONSTRUIR  la persona confirma o corrige cada campo, con la página al lado
3 CHEQUEAR   cotejo demanda frente a boleta (código) + chequeos del título y del proceso
4 GENERAR    cuerpo según organismo + plantilla oficial del PJT ─► sentencia.docx
LOTE         varios expedientes a la vez, con una tabla de estados y «generar todas las listas»
```

## Dónde vive cada cosa

```
servidor.py              servidor local (biblioteca estándar), API JSON y archivos de web/
iniciar.bat              levanta el servidor y abre el navegador
motor/leer.py            PDF ─► páginas; imágenes de las páginas para la interfaz
motor/ocr.py             Tesseract opcional
motor/detectar.py        tipo de cada página, organismo y candidatos de cada campo
motor/organismos.py      patrones propios de SAT, Municipalidad y DGR
motor/cotejo.py          demanda frente a boleta, campo por campo
motor/chequeos.py        chequeos del título y del proceso
motor/honorarios.py      Ley 5.480 (porta src/lib/honorarios/calc.ts de C:\dev\monitorias)
motor/letras.py          montos en letras
motor/redactar.py        cuerpo de la sentencia y .docx con la plantilla oficial
plantillas/              Plantilla-Sentencia-Monitoria-PJT.docx y los textos por organismo
web/                     index.html, app.js, estilos.css (sin compilar nada)
casos/<id>/              un expediente: originales, paginas/*.png, caso.json, sentencia.docx (fuera de git)
config.local.json        datos del juzgado (fuera de git)
```

## El caso (`casos/<id>/caso.json`)

```json
{
  "id": "c-0001",
  "creado": "2026-11-11T12:00:00",
  "estado": "detectado | confirmado | chequeado | observado | generado | error",
  "archivos": ["expediente.pdf"],
  "paginas": [
    {"n": 1, "archivo": "expediente.pdf", "origen": "texto | ocr | vacia",
     "confianza_ocr": null, "tipo": "demanda | boleta | poder | otro",
     "imagen": "paginas/p001.png", "texto": "…"}
  ],
  "organismo": {"valor": "SAT | MUNICIPALIDAD | DGR | null", "pagina": 1, "cita": "…", "confianza": 0.9},
  "campos": {
    "demanda.monto_capital": {
      "valor": "12345.67",
      "confirmado": false,
      "candidatos": [
        {"valor": "12345.67", "pagina": 2, "cita": "…capital de $ 12.345,67…",
         "origen": "texto", "confianza": 0.8, "regla": "monto-capital-demanda"}
      ]
    }
  },
  "cotejo": [],
  "chequeos": [],
  "honorarios": {},
  "sentencia": {"archivo": null, "generada": null}
}
```

- `valor` es el elegido: arranca como el candidato de mayor confianza y la persona lo puede cambiar. Si no hay candidatos, `null`.
- Montos como texto decimal con punto (`"12345.67"`). Fechas `AAAA-MM-DD`. Períodos como lista `["2025-01", "2025-02"]`. CUIT solo con dígitos.

## Campos

Prefijo `demanda.` para lo que sale de la demanda; `boleta.` para el título (boleta o certificado de deuda); `juzgado.` para lo que carga la persona o sale de la configuración.

| Campo | demanda | boleta | Notas |
| --- | --- | --- | --- |
| ejecutante | ✓ | ✓ | SAT, Municipalidad de …, DGR |
| letrado_nombre, letrado_matricula | ✓ | | Matrícula o T°/F° del C.A.T. |
| ejecutado_nombre | ✓ | ✓ (titular) | |
| ejecutado_documento | ✓ | ✓ | CUIT, CUIL o DNI |
| ejecutado_domicilio | ✓ | ✓ | Real, fiscal o de suministro |
| concepto | ✓ | ✓ | Tributo o servicio |
| periodos | ✓ | ✓ | |
| boleta_numero | ✓ | ✓ | |
| boleta_fecha | ✓ | ✓ | Fecha de emisión |
| monto_capital | ✓ | ✓ | |
| monto_total | ✓ | ✓ | Lo reclamado |
| expediente_numero, caratula | ✓ | | |
| juzgado.unidad, juzgado.centro, juzgado.nro_sentencia, juzgado.fecha_sentencia | | | Configuración o carga manual |

## Funciones (contrato entre piezas)

```python
# motor/leer.py
def leer_pdf(ruta_pdf, carpeta_caso, ocr=True) -> list[dict]          # páginas, con imagen PNG guardada en carpeta_caso/paginas/
# motor/ocr.py
def ocr_disponible() -> tuple[bool, str]                             # (sí/no, motivo)
def ocr_imagen(ruta_png, idioma="spa") -> tuple[str, float]          # (texto, confianza media 0-1)
# motor/detectar.py
def clasificar_paginas(paginas) -> list[dict]                        # completa "tipo"
def detectar(paginas) -> dict                                        # {"organismo": {...}, "campos": {...}}
# motor/cotejo.py
def cotejar(campos) -> list[dict]          # [{"campo","demanda","boleta","resultado": "COINCIDE|DIFIERE|FALTA","detalle"}]
# motor/chequeos.py
def chequear(caso, config) -> list[dict]   # [{"id","titulo","resultado": "OK|OBSERVAR|FALTA|MANUAL","detalle"}]
# motor/honorarios.py
def calcular(base, reduccion=True, pct_art14=16, multiplicador=1.55, minimo_cat=None) -> dict
# motor/letras.py
def monto_en_letras(valor: Decimal) -> str
# motor/redactar.py
def armar_cuerpo(caso, config) -> list[dict]                         # párrafos: {"texto","estilo": "titulo|parrafo|resuelvo"}
def generar_docx(caso, config, ruta_salida) -> str
```

## API del servidor (`http://127.0.0.1:8765`)

| Método y ruta | Qué hace |
| --- | --- |
| `GET /` | La interfaz |
| `GET /api/estado` | Versión, si hay OCR y la configuración del juzgado |
| `PUT /api/config` | Guarda la configuración del juzgado |
| `POST /api/casos` | Sube uno o más PDF de UN expediente: `{"archivos": [{"nombre": "…", "base64": "…"}]}` ─► crea el caso, lee y detecta |
| `POST /api/lote` | Sube PDF de VARIOS expedientes, uno por expediente, con el mismo formato JSON ─► un caso por archivo, en paralelo |
| `GET /api/casos` | Lista con id, carátula, organismo, estado y avance |
| `GET /api/casos/<id>` | El caso completo |
| `PUT /api/casos/<id>/campos` | Confirma o corrige campos: `{"demanda.monto_capital": {"valor": "…", "confirmado": true}}` |
| `POST /api/casos/<id>/chequear` | Cotejo, chequeos y honorarios |
| `POST /api/casos/<id>/generar` | Genera `sentencia.docx` (solo con todo confirmado y sin `FALTA`) |
| `GET /api/casos/<id>/pagina/<n>` | Imagen PNG de la página |
| `GET /api/casos/<id>/sentencia` | Descarga el .docx |
| `POST /api/lote/generar` | Genera todas las listas y devuelve un .zip |
| `DELETE /api/casos/<id>` | Borra el caso |

## Material de referencia

- Reglas del dominio: el artefacto original de los relatores (estructura de la sentencia, vía según organismo, fórmulas, resuelvo y formato) y los prompts de la app `monitorias` (checklist A–J de control). No están en este repositorio.
- Honorarios: `motor/honorarios.py` porta el cálculo de la Ley 5.480 de la app `monitorias`, con sus casos de prueba.
- Plantilla oficial: `plantillas/Plantilla-Sentencia-Monitoria-PJT.docx`, con `{caratula}`, `{expediente}`, `{nroSentencia}`, `{fechaSentencia}`, `{unidadJudicial}`, `{centroJudicial}`, `{fechaImpresion}` y `{@cuerpo}` (el cuerpo va como OOXML).
- Muestras reales: demandas de SAT, Municipalidad y DGR, tres sentencias monitorias reales y un listado de causas. Sirvieron para calibrar la detección y los textos, y **no están en el repositorio** porque tienen datos personales. Para medir la detección con las propias: `python herramientas/evaluar_muestras.py <carpeta con PDF>`.
- Los datos personales de las muestras **no se copian** al repositorio: ni en tests ni en ejemplos.
