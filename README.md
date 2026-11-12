# Proyecto 6 · Centro de monitoreo de computer vision

Entrega **individual**. Un stream visual (las secuencias de la cámara del carrito del
Proyecto 5) se reproduce a ritmo fijo, un detector real (YOLOX-Nano en ONNX Runtime CPU)
procesa cada frame y el sistema registra eventos, conserva imágenes, calcula métricas por
ventana y genera alertas que se consultan en un portal web.

- **Tarea:** detección de objetos (80 clases COCO). No se mide calidad predictiva: no hay
  etiquetas, accuracy, IoU ni mAP. Una puntuación alta es "aceptada por la política", no
  "correcta".
- **Índice de evidencias por criterio:** [`evidencias/indice.md`](evidencias/indice.md).
- **Extras reclamados:** [`evidencias/extras.md`](evidencias/extras.md).

## Autoría

| | |
| --- | --- |
| Estudiante | Ikram Zaldívar (@ikramzaldivar) · matrícula 743709 |
| Curso | Integración de Servicios de Aprendizaje Automático, ITESO, otoño 2026 |
| Repositorio | este repositorio; revisión de las evidencias en [`evidencias/indice.md`](evidencias/indice.md) |

**Aporte propio (todo lo de este repositorio salvo lo listado abajo):** fuente por
secuencias con cola acotada, política de dos umbrales y tres zonas, ventanas y cuatro
reglas de alerta, persistencia JSONL, índice SQLite, métricas G1–G7 y su recálculo
independiente, referencia de confianza, secuencias preparadas, escenarios, portal Flask y
pruebas.

**Componentes reutilizados:**

| Componente | Origen | Cambios |
| --- | --- | --- |
| `src/p6/detector_onnx.py` (pre/posprocesamiento YOLOX) | P5 `src/p5/detector_onnx.py`, autora Edith (equipo P5), repo [sebastian0023/Proyecto-3-Clasificador-de-imagenes](https://github.com/sebastian0023/Proyecto-3-Clasificador-de-imagenes) commit `b63ddbc` | `Deteccion` propia, tiempos por etapa, sin la interfaz del recorrido de P5 |
| `scripts/descargar_modelo.py` y `modelo/descriptor.yaml` | P5, mismo commit | solo el user-agent |
| `datos/carrito/` (78 frames S1–S6) | P5 `datos/evaluacion/`, capturados por el equipo con la ESP32-CAM | ninguno; ver [`datos/PROCEDENCIA.md`](datos/PROCEDENCIA.md) |

**Modelo:** YOLOX-Nano `0.1.1rc0` de Megvii (Apache-2.0), pesos oficiales entrenados en
COCO 2017, sin reentrenamiento. Archivo `yolox_nano.onnx`, 3 659 407 bytes, SHA-256
`c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d`
([release](https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0)).

## Arquitectura

```
escenarios/*.yaml ──► Productor (hilo, 2 fps) ──cola acotada──► Monitor
  (frames del carrito                                            │
   o secuencias preparadas)                                      ├─ DetectorONNX: letterbox 416, session.run, NMS
                                                                 ├─ política: score del frame → aceptada / duda / baja
                                                                 ├─ evento ──► eventos.jsonl
                                                                 ├─ captura ─► imagenes/ + capturas.jsonl
                                                                 ├─ ventana de 6 frames ─► reglas ─► ventanas.jsonl
                                                                 │                         └──────► alertas.jsonl
                                                                 └─ vigilancia de la fuente (sin frames > 3 s)
evidencias/corridas/<run_id>/ ──► p6.metricas ──► metricas.json
                             └──► p6.almacen ──► portal.sqlite ──► portal Flask (eventos, alertas, tablero, capturas)
```

| Módulo | Función |
| --- | --- |
| `src/p6/fuente.py` | Carga el escenario y emite los frames a `fps` en una cola acotada (descarta el más antiguo si se llena). |
| `src/p6/detector_onnx.py` | Inferencia real YOLOX-Nano; verifica el SHA-256 de los pesos al cargar. |
| `src/p6/politica.py` | Zonas por umbral; score del frame = máximo de sus candidatas. |
| `src/p6/reglas.py` | Conteos por ventana, p_baja, evidencia insuficiente y reglas. |
| `src/p6/monitor.py` | Orquesta la corrida y escribe los registros primarios. |
| `src/p6/metricas.py` | Métricas G1–G7 desde los JSONL. |
| `src/p6/referencia.py` | Congela `config/referencia.json` desde una corrida. |
| `src/p6/almacen.py`, `src/p6/portal.py` | Índice SQLite reconstruible y portal. |
| `scripts/recalcular_metricas.py` | Recálculo independiente (no importa `p6`). |

## Instalación

Probado en Windows 11 con Python 3.12.10, solo CPU. No requiere cámara, GPU ni servicios externos.

En Windows, clona en una ruta corta o activa `git config --global core.longpaths true`
antes de clonar: algunas rutas de evidencias llegan a 121 caracteres.
La reproducción desde un clon limpio está en [`evidencias/reproduccion.md`](evidencias/reproduccion.md).

```bash
git clone <este repositorio> p6 && cd p6
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt   # versiones exactas, incluidas las indirectas
python scripts/descargar_modelo.py --destino modelo/   # verifica el SHA-256; sale 1 si no coincide
```

Los comandos se ejecutan desde la raíz con `src` en `PYTHONPATH`:
PowerShell `$env:PYTHONPATH = "src"`, bash `export PYTHONPATH=src`.

```bash
pytest -q          # 30 pruebas; la de integración usa el modelo real
ruff check .
```

## Configuración

| Archivo | Contenido |
| --- | --- |
| [`config/monitoreo.yaml`](config/monitoreo.yaml) | fuente (2 fps, cola 8, 3 s sin frames), umbrales 0.40/0.70, ventanas de 6 frames con mínimo 4 puntuados, reglas, política de captura |
| [`config/detector.yaml`](config/detector.yaml) | modelo, entrada 416, relleno 114, **piso de salida 0.10**, NMS 0.45, máx. 100 detecciones |
| [`config/referencia.json`](config/referencia.json) | referencia congelada desde la corrida `r0-referencia-20261112T045031Z` |
| [`escenarios/*.yaml`](escenarios/) | frames y pausas de cada escenario, descripción y resultado esperado |

Justificación de umbrales, piso y referencia: [`docs/umbrales.md`](docs/umbrales.md).
Definición de métricas e inventario G1–G7: [`docs/metricas.md`](docs/metricas.md).

## Ejecución

```bash
# 0. (opcional) regenerar las secuencias derivadas; son deterministas y ya están versionadas
python scripts/preparar_secuencias.py

# 1. referencia (ya ejecutada y congelada; solo para reproducirla)
python -m p6.monitor --escenario escenarios/r0-referencia.yaml
python -m p6.referencia evidencias/corridas/<run_id_r0> --salida config/referencia.json

# 2. escenarios base
python -m p6.monitor --escenario escenarios/c1-normal.yaml
python -m p6.monitor --escenario escenarios/c2-baja-confianza.yaml

# 3. escenarios adicionales
python -m p6.monitor --escenario escenarios/e1-cambio-sostenido.yaml
python -m p6.monitor --escenario escenarios/e2-entradas-corruptas.yaml
python -m p6.monitor --escenario escenarios/e3-interrupcion-fuente.yaml

# 4. portal en http://127.0.0.1:8000
python -m p6.portal

# 5. recálculo independiente de todas las corridas (sale 1 si algo no coincide)
python scripts/recalcular_metricas.py --todas
```

Cada corrida crea `evidencias/corridas/<escenario>-<UTC>/` con `run.json`, una copia
exacta de la configuración, `eventos.jsonl`, `ventanas.jsonl`, `alertas.jsonl`,
`capturas.jsonl`, `imagenes/` y `metricas.json`. Para ejecutar sin mezclar con las
evidencias entregadas: `--salida <otra carpeta>` y `python -m p6.portal --corridas <otra carpeta>`.

## Portal

| Vista | Ruta | Contenido |
| --- | --- | --- |
| Eventos (base) | `/eventos`, `/eventos/<event_id>` | filtros por corrida, zona, status, resultado, clase, secuencia, score y captura; detalle con imagen y cajas, candidatas con su zona, tiempos, configuración, ventana, alertas y la línea JSONL |
| Alertas (base) | `/alertas`, `/alertas/<alert_id>` | momento, regla, severidad, estado, motivo, acción sugerida; detalle con condición, valores observados, ventanas, eventos con capturas y registros |
| Tablero (extra) | `/` | tarjetas por corrida, gráficas de score por frame, p_baja por ventana y alertas activas, y métricas base |
| Revisión de capturas (extra) | `/capturas` | galería filtrable y veredicto manual persistido en `evidencias/revisiones.jsonl` |
| Exportación (extra) | `/export/eventos.csv` | CSV con los mismos filtros de `/eventos` |
| Ventanas y corridas | `/ventanas/<id>`, `/corridas/<run_id>` | conteos y reglas por ventana; `run.json`, configuración congelada y métricas |

Las capturas de pantalla de cada vista están en [`evidencias/portal/`](evidencias/portal/).

## Límites conocidos

- La fuente es una **reproducción** de imágenes capturadas por el carrito, no la cámara en
  vivo: el ritmo (2 fps) lo impone el productor y la hora de captura es la de emisión.
- El modelo es COCO: en las escenas del carrito con peluches y objetos de casa produce
  clases implausibles (toilet, fire hydrant, refrigerator) con puntuaciones bajas o medias.
  Eso explica que la referencia tenga p_baja = 0.32. No se evalúa si las clases son correctas.
- C2, E1 y E2 usan secuencias preparadas (iluminación, enfoque, archivos truncados): se
  modifica la imagen de entrada, nunca la puntuación.
- Pocas observaciones por corrida (12–78 frames): el PSI frente a la referencia es
  informativo y ruidoso con n < 50; no dispara alertas.
- Las mediciones de tiempo, CPU y RAM son de un portátil con Windows y otros procesos
  activos; no se fijó afinidad de CPU.
- La alerta de fuente detenida se evalúa en el mismo proceso que recibe los frames; si el
  proceso muere no hay alerta (no hay vigilancia externa).
