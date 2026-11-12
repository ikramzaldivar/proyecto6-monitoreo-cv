# Índice de evidencias

## Revisiones Git

| Commit | Contenido | Relación con las evidencias |
| --- | --- | --- |
| `56ede4d` | Código, configuración, escenarios, datos y pruebas | — |
| `ad5229d` | `.gitattributes` (LF) | Revisión con la que corrió `r0-referencia` |
| `862916f` | `config/referencia.json` y corrida r0 | Referencia congelada antes de C1/C2 |
| `de41810` | LF en JSON, motivo de resolución por regla, E1 rediseñado | **Revisión con la que corrieron C1, C2, E1, E2 y E3** (`run.json → git.commit`, sin cambios en el código) |
| commit de entrega (siguiente a `de41810`) | Corridas C1–E3, capturas del portal, documentación, recálculo y reproducción | Solo agrega evidencias y docs. Además cambia la posición de las etiquetas de umbral en las gráficas SVG (`src/p6/portal.py`, `_umbral`) y amplía `scripts/recalcular_metricas.py` a las métricas extra; ninguno de los dos cambios afecta a las corridas ya registradas |

Configuración de todas las corridas C1–E3: `monitoreo-v1@2ea33802ba0c`. Modelo:
`yolox_nano 0.1.1rc0`, SHA-256 `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d`.

## Corridas

| Escenario | run_id | Frames | Alertas |
| --- | --- | --- | --- |
| Referencia | `r0-referencia-20261112T041654Z` | 78 | 2 × baja-confianza (S3/S4) |
| **C1** normal | `c1-normal-20261112T042108Z` | 41 | ninguna |
| **C2** baja confianza | `c2-baja-confianza-20261112T042129Z` | 12 | `…-a01` baja-confianza-v1 |
| E1 sostenido | `e1-cambio-sostenido-20261112T042135Z` | 48 | `…-a01` baja-confianza, `…-a02` cambio-sostenido |
| E2 corruptas | `e2-entradas-corruptas-20261112T042201Z` | 29 | `…-a01` errores-inferencia |
| E3 interrupción | `e3-interrupcion-fuente-20261112T042216Z` | 29 | `…-a01` fuente-detenida |

Cada carpeta `evidencias/corridas/<run_id>/` contiene `run.json`, `config/` (copia exacta),
`eventos.jsonl`, `ventanas.jsonl`, `alertas.jsonl`, `capturas.jsonl`, `imagenes/` y
`metricas.json`.

## Cadena de una muestra (C2)

1. **Entrada:** `datos/preparadas/poca-luz/S5-poca-luz_S5_20800b49d3044edf9c90975516e5fbcc.jpg` (SHA-256 `c029c21c…`). Su manifiesto
   indica el origen `datos/carrito/S5/…` con SHA-256 y la transformación aplicada.
2. **Inferencia → evento** `c2-baja-confianza-20261112T042129Z-f0001` (`eventos.jsonl`,
   línea 1): `status=ok`, candidatas tv 0.303, cat 0.225, person 0.166, cat 0.107, `score_frame=0.303`,
   `zona_frame=baja`, modelo `c789161e…`, `config_ref monitoreo-v1@2ea33802ba0c`,
   `ventana_id …-v001`, `imagen_ref imagenes/0001_S5_20800b49d3044edf9c90975516e5fbcc-poca-luz.jpg`.
3. **Captura:** `capturas.jsonl → …-f0001-img`, motivo `zona_baja`, SHA-256 del archivo copiado.
4. **Ventana** `…-v001` (`ventanas.jsonl`): 6 puntuados, 6 en zona baja, p_baja 1.0,
   `baja_confianza: cumple`.
5. **Alerta** `…-a01` (`alertas.jsonl`): apertura con `ventana_ids [v001]` y `event_ids
   f0001–f0006`; resolución en v002.
6. **Portal:** `/alertas/c2-baja-confianza-20261112T042129Z-a01` lleva a la ventana, a los
   eventos y a las capturas (`portal/07-alerta-c2.png`, `portal/08-evento-c2-baja.png`).
7. **Recálculo:** `recalculo.txt`, bloque `c2-…`: zonas, ventanas, alerta y métricas coinciden.

## Criterios

| Criterio | Evidencia |
| --- | --- |
| R1.1 Fuente como stream | `src/p6/fuente.py` (2 fps, cola 8, descarte del más antiguo); `config/monitoreo.yaml → fuente`; `run.json → fuente` (emitidos = procesados, 0 descartes); `datos/PROCEDENCIA.md` |
| R1.2 Inferencia real | `src/p6/detector_onnx.py` (SHA-256 verificado al cargar); `eventos.jsonl → detections, tiempos_ms.modelo`; mismos scores en corridas distintas (`docs/escenarios.md`); `tests/test_monitor_real.py` |
| R1.3 Identidad del modelo | `README.md#autoría`, `modelo/descriptor.yaml` (URL, bytes, SHA-256, 80 clases, entrada/salida), `config/detector.yaml`, `run.json → modelo, entorno` |
| R2 Métricas G1–G7 | `docs/metricas.md` (inventario, aplicabilidad G=7, M1–M5 por grupo, resultados); `metricas.json` de cada corrida; `src/p6/metricas.py`; `recalculo.txt` |
| R3.1 Umbrales | `config/monitoreo.yaml → politica` (0.40 / 0.70); `docs/umbrales.md` (distribución de la referencia y justificación) |
| R3.2 Tres zonas | `src/p6/politica.py`, `tests/test_politica.py`; piso 0.10 y NMS en `config/detector.yaml`; zona por candidata y por frame en cada evento; `resultado=sin_detecciones` aparte; `portal/03-evento-c1-aceptado.png` (candidatas bajas dentro de un frame aceptado) |
| R3.3 Referencia y regla sostenida | `config/referencia.json`; `config/monitoreo.yaml → ventanas, reglas.cambio_sostenido`; `src/p6/reglas.py` (insuficiente ≠ normal); `ventanas.jsonl → estado`; `portal/15-ventana-c1-insuficiente.png` |
| R4.1 Eventos | `eventos.jsonl` (identidad, fechas, fuente, modelo, status, detections, score, zona, config_ref, umbrales, imagen_ref); correspondencia con el contrato de la guía en `README.md` y `docs/escenarios.md` |
| R4.2 Persistencia y consulta | JSONL append-only + `src/p6/almacen.py`; `/eventos`, `/eventos/<id>` con vínculos a ventana, alertas, configuración y línea JSONL; `portal/02-…`, `03-…`, `06-…`, `08-…` |
| R4.3 Imágenes | Política en `config/monitoreo.yaml → captura` (baja, duda, error, alerta, 1 de cada 4 normales); `capturas.jsonl` + `imagenes/`; sin código de borrado; G5 = 100 % en todas las corridas |
| R5.1 Reglas | `config/monitoreo.yaml → reglas`, `src/p6/reglas.py` (docstring), `docs/umbrales.md#ventanas-y-reglas` |
| R5.2 Alertas desde observaciones | `alertas.jsonl` (regla, condición, valores observados, ventanas, eventos, config_ref); verificadas contra las ventanas en `recalculo.txt` |
| R5.3 Alertas en el portal | `/alertas`, `/alertas/<id>` (momento, motivo, severidad, acción sugerida, estado); `portal/07-…`, `09-alertas-todas.png`, `11-…`, `12-…`, `13-…` |
| R6.1 C1 | `docs/escenarios.md#c1`, corrida `c1-normal-…`, `portal/01-…` a `04-…` |
| R6.2 C2 | `docs/escenarios.md#c2`, corrida `c2-baja-confianza-…`, `portal/05-…` a `08-…`, `14-…` |
| R7.1 Instalación y comandos | `README.md`, `requirements.txt` (versiones exactas), `pyproject.toml` |
| R7.2 Evidencias verificables | este índice, `recalculo.txt`, `reproduccion.md` (clon limpio) |
| R7.3 Autoría | `README.md#autoría`, `datos/PROCEDENCIA.md`, encabezado de `src/p6/detector_onnx.py` |
| Extras | [`extras.md`](extras.md) |

## Capturas del portal (`evidencias/portal/`)

Tomadas con Chrome headless contra `python -m p6.portal` sobre estas mismas corridas.

| Archivo | Vista |
| --- | --- |
| 01-tablero-c1 | Tablero con la corrida C1 |
| 02-eventos-c1 | Lista de eventos de C1 |
| 03-evento-c1-aceptado | Detalle de un evento aceptado con captura y candidatas |
| 04-alertas-c1-vacio | Alertas de C1: ninguna, con aviso de que no implica operación sana |
| 05-tablero-c2 | Tablero con la corrida C2 |
| 06-eventos-c2-baja | Eventos de C2 filtrados por zona baja |
| 07-alerta-c2 | Detalle de la alerta de C2 con ventanas, eventos y capturas |
| 08-evento-c2-baja | Detalle de un evento de baja confianza (con revisión manual) |
| 09-alertas-todas | Lista de todas las alertas |
| 10-tablero-e1-sostenido | Tablero con E1 |
| 11-alerta-e1-sostenido | Alerta de cambio sostenido con la racha de 3 ventanas |
| 12-alerta-e2-errores | Alerta de errores de inferencia |
| 13-alerta-e3-fuente | Alerta de fuente detenida |
| 14-capturas-revision | Revisión manual de capturas de C2 |
| 15-ventana-c1-insuficiente | Ventana con evidencia insuficiente |
| 16-corrida-c2-config | `run.json`, configuración congelada y métricas de C2 |
| 17-eventos-filtro-vacio | Estado vacío de un filtro |
| 18-evento-e2-error | Evento con `status=error` |
