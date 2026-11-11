# Constructor de sentencias monitorias

Arma sentencias monitorias a partir de la demanda y la boleta de deuda (SAT, Municipalidad y DGR), **sin IA** y sin que nada salga de la computadora. Paso a paso: detectar, construir, chequear y generar. También procesa varios expedientes a la vez.

## Por qué es público

Es una iniciativa de [derechointeligente.com.ar](https://derechointeligente.com.ar). Lo publicamos completo, con el código, el diseño y las reglas, para que cualquier juzgado, relator o estudio pueda usarlo, copiarlo, adaptarlo a su modelo de sentencia y mejorarlo.

Muestra que no todo necesita IA. Comparar una demanda con una boleta es una cuenta, y escribir una sentencia monitoria sin excepciones es llenar un modelo. Eso lo hace el código, sin alucinar y sin mandar los datos a ningún lado. La persona revisa y firma.

> ⚖️ Es una herramienta de productividad, no reemplaza el control del juez ni constituye asesoramiento jurídico. Los textos de `plantillas/` siguen el modelo de un juzgado de Tucumán: cada juzgado debe revisarlos y adaptarlos a su criterio.

## Arrancar

1. Requisitos: Python 3 y `pip install -r requirements.txt` (PyMuPDF, pytesseract, Pillow, openpyxl). Para leer páginas escaneadas, además, Tesseract con el idioma español (`scoop install tesseract tesseract-languages`, o el instalador de UB-Mannheim). Sin Tesseract funciona igual, pero las páginas escaneadas se cargan a mano.
2. Doble clic en `iniciar.bat`, o `python servidor.py`, y abrir `http://127.0.0.1:8765`.
3. La primera vez: botón de configuración. Hay que cargar la unidad y el centro judicial, la ciudad, el próximo número de sentencia, la tasa de interés, la cuenta judicial, el martillero y los honorarios.

El servidor escucha solo en `127.0.0.1`: no se puede abrir desde otra computadora de la red.

## Cómo se usa

| Paso | Qué pasa |
| --- | --- |
| 1 · Detectar | Se sueltan los PDF del expediente. Lee el texto de cada página; si es escaneo, aplica OCR. Clasifica las páginas (demanda, boleta, poder) y propone cada dato con su página, su cita y su confianza |
| 2 · Construir | La persona confirma o corrige cada dato, con la imagen de la página al lado. Lo que sale de OCR se revisa a mano |
| 3 · Chequear | Cotejo de la demanda frente a la boleta (código, sin IA), chequeos del título y del proceso, y honorarios por la Ley 5.480 |
| 4 · Generar | La sentencia en .docx con la plantilla oficial del PJT. Solo se genera con todo confirmado y sin faltantes. Lo que necesita criterio queda como `[COMPLETAR: …]` |
| Lote | Se sueltan muchos PDF, uno por expediente. Se procesan en paralelo; una tabla muestra el estado de cada uno y «Generar todas las listas» devuelve un .zip |

## Dónde se edita qué

- Textos de la sentencia por organismo: `plantillas/cuerpo-sat.txt`, `cuerpo-municipalidad.txt` y `cuerpo-dgr.txt`, con {marcadores}.
- Membrete, márgenes y pie: `plantillas/Plantilla-Sentencia-Monitoria-PJT.docx`.
- Reglas de detección por organismo: `motor/organismos.py`.
- Chequeos: `motor/chequeos.py`.
- El diseño completo y el contrato entre piezas: `DISEÑO.md`.

## Pruebas

`python -m unittest discover -s tests` corre 75 tests: detección, reglas, honorarios, montos en letras, .docx y servidor. `python herramientas/evaluar_muestras.py <carpeta>` mide la detección sobre expedientes reales y muestra solo conteos.

## Límites conocidos

- **El número de expediente no está en la demanda**: se presenta sin número, así que se carga a mano.
- **Detección floja**: los períodos y la fecha de la boleta cuando se citan dentro de la demanda, y el domicilio en las boletas de la SAT, cuyo texto viene con las columnas mezcladas.
- **El OCR propone, no decide**: con escaneos malos se equivoca.
- **Criterio jurídico**: la prescripción, la habilidad del título y la tasa de interés quedan para la persona (MANUAL o [COMPLETAR]).
- **Normas que faltan**: en DGR y Municipalidad, el artículo del Código Tributario que da fuerza ejecutiva al título no está en las fuentes, así que queda [COMPLETAR].
- **Pagaré**: todavía no está cubierto.

## Licencia

[MIT](LICENSE): se puede usar, copiar, modificar y distribuir libremente, también con fines comerciales, manteniendo el aviso de copyright y de licencia.
