# Umbrales, piso de salida y referencia

Todos los valores están en [`config/monitoreo.yaml`](../config/monitoreo.yaml) y
[`config/detector.yaml`](../config/detector.yaml), y se fijaron **antes** de ejecutar C1,
C2 y los escenarios adicionales. Todas esas corridas usan `monitoreo-v1@2ea33802ba0c`.

## Unidad de análisis y denominador

- **Unidad:** el frame. Su puntuación (`score_frame`) es la máxima entre sus detecciones
  candidatas, es decir, las que quedan tras el piso de salida y el NMS. Cada candidata
  conserva también su propia puntuación y zona en `detections[]`.
- **Frames sin detecciones** (`status=ok`, `resultado=sin_detecciones`): no tienen
  puntuación ni zona y no se les asigna un cero artificial.
- **Frames con fallo** (`status=error`): igual, estado aparte.
- **p_baja** = frames en zona baja / frames puntuados. Los sin detecciones y los errores
  quedan fuera del denominador.
- Los frames consecutivos de una misma escena se parecen. Las secuencias del carrito ya
  están espaciadas (son capturas seleccionadas, no video continuo) y no se presentan como
  observaciones independientes: las reglas trabajan por ventana.

## Piso de salida y NMS (detector)

- **Piso `umbral_confianza = 0.10`.** P5 usaba 0.30, que ocultaría casi toda la zona baja
  (0.10–0.40). En un sondeo exploratorio con piso 0.05 sobre S1–S6 (no versionado; se
  repite cambiando el valor en `config/detector.yaml`), lo que aparecía entre 0.05 y 0.10
  eran sobre todo candidatas de fondo (bird 0.06, cell phone 0.06, umbrella 0.05), varias
  en frames que ya tenían otra candidata mayor. Con 0.10 la zona baja queda visible sin
  llenar los eventos de ruido.
- **NMS por clase, IoU 0.45** (valor por defecto de YOLOX). Máximo 100 candidatas por frame.
- **Entrada 416×416** con letterbox gris 114, BGR, 0–255 sin normalizar (export oficial).

## Corrida de referencia

`r0-referencia-20261112T041654Z` (commit `ad5229d`): las seis secuencias originales del
carrito (S1–S6, 78 frames) con la iluminación normal de la captura de P5. Puntuación del
frame por secuencia (`—` = sin detecciones):

| Secuencia | Escena | score_frame por frame |
| --- | --- | --- |
| S1 | despejado | — — — 0.18 — — — — — — — — |
| S2 | obstáculos | 0.87 0.90 0.17 0.45 0.19 0.82 0.21 0.66 0.50 0.61 0.86 — 0.41 0.71 0.63 0.54 0.49 |
| S3 | obstáculos | — 0.31 0.44 0.46 0.22 0.34 0.27 0.33 0.15 0.69 0.91 0.85 0.45 |
| S4 | obstáculos | 0.18 0.28 0.24 0.33 0.88 0.80 0.82 0.85 0.74 0.25 0.23 0.46 |
| S5 | obstáculos | 0.87 0.81 0.86 0.66 0.83 0.47 0.86 0.50 0.76 0.88 0.86 0.88 |
| S6 | mixto | 0.41 0.45 0.16 0.53 0.35 0.88 — 0.72 0.21 0.30 — — |

Distribución de los 62 frames puntuados (`config/referencia.json`):

| Intervalo | [0.10, 0.25) | [0.25, 0.40) | [0.40, 0.55) | [0.55, 0.70) | [0.70, 0.85) | [0.85, 1.00] |
| --- | --- | --- | --- | --- | --- | --- |
| Frames | 11 | 9 | 14 | **5** | 9 | 14 |

Percentiles: p10 0.21 · p25 0.31 · p50 0.50 · p75 0.82 · p90 0.87.

## Elección de los umbrales

- **Superior 0.70.** La distribución es bimodal, con un valle en [0.55, 0.70) donde solo
  hay 5 de 62 frames. Por encima se agrupan 23 frames (0.71–0.91): las personas, gatos y
  perros de S2, S4 y S5, con el objeto completo en cuadro. Cortar en 0.70 deja ese grupo
  como "aceptada" y manda a revisión (duda) lo intermedio. No afirma que esas detecciones
  sean correctas.
- **Inferior 0.40.** Separa el tercio inferior de la referencia (20 de 62, entre p25 y
  p50). Por debajo están las candidatas débiles: S1 0.18, S3 0.15–0.34, S4 0.18–0.33.
  Entre 0.40 y 0.70 quedan 19 frames de duda.
- **Resultado en la referencia:** aceptada 23 · duda 19 · baja 20 · sin detecciones 16 ·
  error 0. **p_baja de referencia = 20/62 = 0.3226.**
- Se cumple `0 ≤ 0.40 < 0.70 ≤ 1`. La igualdad con el inferior es duda y la igualdad con
  el superior es aceptada (`src/p6/politica.py`, `tests/test_politica.py`).

## Ventanas y reglas

| Parámetro | Valor | Justificación |
| --- | --- | --- |
| Ventana | 6 frames procesados consecutivos, sin traslape (3 s a 2 fps) | La mitad de una secuencia del carrito (12 frames): una escena se evalúa en 2 ventanas |
| Mínimo de observaciones | 4 frames puntuados | En la referencia, las ventanas de S1 tienen 0–1 puntuados; con menos de 4 de 6, una sola candidata decidiría la ventana |
| Insuficiente | `p_baja = null`, `estado = insuficiente` | No es normalidad: no dispara ni resuelve alertas y la racha sostenida no avanza ni se reinicia |
| `baja-confianza-v1` | p_baja ≥ 0.50 en una ventana suficiente | En la referencia, 2 de 10 ventanas suficientes llegan a 0.67 (S3/S4 con peluches) y 8 están en ≤ 0.33; 0.50 exige que la mayoría de los frames puntuados sean bajos |
| `cambio-sostenido-v1` | p_baja > 0.3226 + 0.30 = 0.623 en 3 ventanas suficientes seguidas | Ninguna racha de la referencia pasa de 1 ventana sobre 0.623; 3 ventanas (9 s) evitan alertar por una escena aislada |
| `errores-inferencia-v1` | ≥ 50 % de frames con error, con al menos 3 intentos | Fallos técnicos, separados de la confianza |
| `fuente-detenida-v1` | más de 3 s sin frames nuevos | 6 periodos a 2 fps; se resuelve con el siguiente frame |

Las alertas abiertas se resuelven en la primera ventana evaluable que ya no cumple su
regla. La confianza no confirma drift ni pérdida de calidad: la acción sugerida pide
revisar capturas y condiciones, no reentrenar.

## Comparabilidad

Referencia, C1, C2 y los extras usan el mismo modelo (SHA-256 `c789161e…`), el mismo
preprocesamiento (416, relleno 114), el mismo piso (0.10), el mismo NMS (0.45) y los mismos
umbrales. `run.json` de cada corrida guarda estos valores y el SHA-256 de la referencia
usada (`4f55629e95b3…`). Si alguno cambiara, la serie se separa: la referencia tendría que
recalcularse con `p6.referencia` sobre una corrida con la nueva configuración.
