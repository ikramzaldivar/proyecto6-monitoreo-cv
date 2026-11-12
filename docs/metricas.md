# Inventario de métricas G1–G7

Los siete grupos **aplican** (G = 7): hay inferencia visual (G1, G2), un proceso medible
con psutil (G3), salidas con puntuación (G4), eventos e imágenes (G5), una fuente y una
versión de modelo reportadas en cada evento (G6) y alertas (G7). No se excluye ninguno.

Reglas comunes:

- **Ventana de cálculo:** la corrida completa (`evidencias/corridas/<run_id>/`). G7 se
  reporta además por ventana de 6 frames.
- **Fuente de datos:** solo archivos primarios de la corrida (`eventos.jsonl`,
  `ventanas.jsonl`, `alertas.jsonl`, `capturas.jsonl`, `run.json`, `config/`). Lo calcula
  `src/p6/metricas.py` y lo escribe en `metricas.json` al cerrar la corrida.
- **Cero observaciones:** si la población está vacía, el valor es `null` con
  `motivo_null`; nunca se reporta 0 por falta de datos.
- **Percentiles:** nearest-rank, es decir, el elemento en la posición ⌈q·n⌉ de la lista
  ordenada, sin interpolar.
- **Verificación:** `python scripts/recalcular_metricas.py --todas` recalcula con código
  propio (no importa `p6`) y compara con `metricas.json`. El resultado entregado está en
  [`evidencias/recalculo.txt`](../evidencias/recalculo.txt): 114/114 comprobaciones coinciden (base, reglas, alertas y extras).

## Métricas base (una por grupo)

| Grupo | Métrica base | Clave en `metricas.json` |
| --- | --- | --- |
| G1 Salud y rendimiento | Tiempo de inferencia del modelo, p50/p95 | `G1_tiempo_inferencia_ms` |
| G2 Captura y stream | FPS de procesamiento | `G2_fps_procesamiento` |
| G3 Recursos | RAM (RSS) del proceso del monitor, máximo y media | `G3_rss_mb` |
| G4 Predicciones | Proporción de baja confianza (frames) | `G4_p_baja` |
| G5 Datos y trazabilidad | Imágenes vinculadas | `G5_imagenes_vinculadas` |
| G6 Fuentes y versiones | Versión esperada frente a reportada | `G6_version_esperada_vs_reportada` |
| G7 Alertas | Alertas activas por ventana | `G7_alertas_activas` |

### G1 · Tiempo de inferencia del modelo

- **Qué mide:** la duración de `session.run` de ONNX Runtime, separada de la decodificación
  y el letterbox (preproceso) y de la decodificación de la rejilla y el NMS (posproceso),
  que se registran aparte en `tiempos_ms`. **Unidad:** ms.
- **Fórmula:** p50 y p95 (nearest-rank) de `tiempos_ms.modelo`.
- **Población:** eventos con `status=ok` de la corrida. **Exclusiones:** frames con error
  (no llegan a `session.run` o fallan). Sin frames `ok`, el valor es null.
- **Instrumentación:** `time.perf_counter()` antes y después de `session.run`
  (`DetectorONNX.detectar_imagen`).
- **Trazabilidad:** cada valor sale de `eventos.jsonl → tiempos_ms.modelo` con su `event_id`.

### G2 · FPS de procesamiento

- **Qué mide:** frames procesados (inferidos, `ok` o `error`) por segundo de pared.
  **Unidad:** frames/s.
- **Fórmula:** `n / (timestamp del último evento − t_captura del primero)`. Ambos tiempos
  son UTC del mismo reloj del proceso.
- **Población:** todos los eventos de la corrida. Con menos de 2, el valor es null.
- **Exclusiones:** ninguna. Las pausas del escenario (E3) **sí** cuentan en la duración:
  una interrupción baja el FPS observado, que es justo lo que se quiere ver.
- **Instrumentación:** `t_captura` lo pone el productor al emitir el frame y `timestamp`,
  el monitor al registrar el evento (`src/p6/fuente.py`, `src/p6/monitor.py`).

### G3 · RAM (RSS) del proceso

- **Qué mide:** memoria residente del proceso Python del monitor (incluye ONNX Runtime y
  el productor; no incluye al portal ni a otros procesos). **Unidad:** MiB.
- **Fórmula:** máximo y media de `recursos.rss_mb`, con una muestra por frame tomada al
  terminar la inferencia (`psutil.Process().memory_info().rss / 2**20`).
- **Población:** todos los eventos. Sin eventos, el valor es null.

### G4 · Proporción de baja confianza

- **Qué mide:** fracción de frames puntuados cuya `score_frame` está bajo el umbral
  inferior. Describe salidas, no aciertos. **Unidad:** proporción [0, 1].
- **Fórmula:** `frames con zona_frame = baja / frames con status=ok y score_frame ≠ null`.
- **Exclusiones:** frames sin detecciones y frames con error, que se reportan en `G4_zonas`.
  Sin frames puntuados, el valor es null.
- Es la misma proporción que usan las reglas por ventana. Aquí se reporta para la corrida
  completa.

### G5 · Imágenes vinculadas

- **Qué mide:** capturas que siguen siendo evidencia válida de su evento. **Unidad:** proporción.
- **Fórmula:** `capturas cuyo archivo existe, cuyo SHA-256 coincide con el registrado y
  cuyo event_id existe en eventos.jsonl / capturas registradas en capturas.jsonl`.
- **Población:** todas las líneas de `capturas.jsonl`. Sin capturas, el valor es null.

### G6 · Versión esperada frente a reportada

- **Qué mide:** si cada evento fue producido por el modelo esperado. **Unidad:** proporción.
- **Fórmula:** `eventos con model.sha256 = sha256 de config/descriptor.yaml de la corrida / eventos`.
  También se reporta la distribución `nombre@sha12` de las versiones que aparecen.
- **Instrumentación:** el SHA-256 se calcula sobre los bytes del `.onnx` al cargar el
  detector, que se niega a arrancar si no coincide con el descriptor. Cada evento copia el
  valor calculado.

### G7 · Alertas activas por ventana

- **Qué mide:** número de alertas que estuvieron abiertas en algún instante de cada
  ventana. **Unidad:** alertas.
- **Intervalo de la ventana k:** `(cierre de la ventana k−1, cierre de la ventana k]`, con
  `evaluada_utc` de `ventanas.jsonl` como cierre y `run.json → inicio_utc` como límite
  inferior de la primera. Los intervalos son contiguos: cubren toda la corrida sin huecos.
- **Fórmula:** una alerta cuenta en la ventana k si `apertura ≤ fin_k` y (no tiene
  resolución o `resolución > inicio_k`), con aperturas y resoluciones de `alertas.jsonl`.
  Resumen: máximo por ventana, abiertas al cierre de la corrida, total abiertas y total
  resueltas.
- **Población:** ventanas evaluadas (incluye la parcial final). Sin ventanas, el valor es null.
- **Por qué este intervalo:** cuenta también las alertas por tiempo que abren y se resuelven
  entre dos cierres (`fuente-detenida-v1` en E3). Una alerta resuelta al cerrar la ventana k
  cuenta en k porque estuvo activa durante ella. Se conserva aparte la serie al cierre
  (`serie_al_cierre_de_ventana`, la `n_alertas_activas` de cada ventana).
- **Cambio:** la primera versión solo contaba las alertas abiertas en el instante del cierre
  y dejaba E3 en cero. Se corrigió en el commit `7c4a1b8` y todas las corridas se
  regeneraron con el código corregido.

## Resultados por corrida

| Corrida | G1 p50 / p95 ms | G2 FPS | G3 RSS máx MiB | G4 p_baja | G5 vinculadas | G6 | G7 serie (máx) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| r0-referencia | 11.81 / 22.46 | 2.023 | 82.35 | 20/62 = 0.323 | 49/49 | 78/78 | 0,0,0,0,0,1,1,1,1,0,0,0,0 (1) |
| c1-normal | 10.17 / 19.33 | 2.046 | 79.87 | 4/29 = 0.138 | 22/22 | 41/41 | 0 ×7 (0) |
| c2-baja-confianza | 10.92 / 25.24 | 2.174 | 79.33 | 7/12 = 0.583 | 9/9 | 12/12 | 1,1 (1) |
| e1-cambio-sostenido | 12.23 / 22.66 | 2.041 | 82.03 | 16/47 = 0.340 | 31/31 | 48/48 | 0,0,1,1,2,2,0,0 (2) |
| e2-entradas-corruptas | 10.64 / 20.47 | 2.069 | 83.49 | 0/24 = 0.000 | 16/16 | 29/29 | 0,0,1,1,0 (1) |
| e3-interrupcion-fuente | 12.03 / 19.77 | 1.486 | 79.47 | 3/28 = 0.107 | 18/18 | 29/29 | 0,0,1,0,0 (1) |

Entorno de todas las corridas: Windows 11, Python 3.12.10, onnxruntime 1.31.1 con
CPUExecutionProvider (detalle en `run.json → entorno`).

## Métricas adicionales (reclamadas como extra)

Son distintas de las bases de su grupo y están en el mismo `metricas.json`. Su nivel
solicitado y su justificación están en [`evidencias/extras.md`](../evidencias/extras.md).

| ID | Grupo | Métrica | Definición |
| --- | --- | --- | --- |
| M1 | G1 | Tasa de errores técnicos | `status=error / frames procesados`; null sin frames |
| M2 | G2 | Latencia de extremo a extremo p50/p95/máx | `(registro del evento − emisión del frame)` en ms, mismo reloj `perf_counter`; incluye cola, decodificación, inferencia y escritura |
| M3 | G4 | Frames sin detecciones | `sin_detecciones / frames status=ok`; no se trata como error ni como baja confianza |
| M4 | G4 | Distribución de score_frame frente a la referencia (PSI) | 6 intervalos fijos de [0.10, 1.00]; `PSI = Σ (a−r)·ln(a/r)` con proporciones suavizadas a 1e-4; null sin puntuados o sin referencia |
| M5 | G5 | Cobertura de trazabilidad | eventos con los 10 campos requeridos no vacíos **y** cuya entrada existe con el SHA-256 del manifiesto / eventos |
| M6 | G7 | Tiempo de detección | `apertura de la alerta − t_captura del primer frame que cumple la condición` (s) |
| M7 | G3 | CPU del proceso | `psutil cpu_percent` del proceso entre muestras (% de un núcleo), media y máximo; excluye la primera muestra |
| M8 | G4 | Detecciones por clase y zona | unidad: candidata (no frame), conteo por `class_name` × zona |

Valores observados de M4 (PSI): C1 1.13, C2 1.39, E1 0.16, E2 2.68, E3 1.17 (r0 da 0.00 contra la referencia anterior, que tiene la misma distribución). Con 12–48
frames por corrida, el PSI depende mucho de los intervalos poco poblados: C1 (operación
normal, solo S1/S5/S2) da un valor alto porque concentra frames en [0.70, 1.00] y no tiene
los de S3/S4 de la referencia. Por eso el PSI es **informativo** y ninguna regla lo usa.
