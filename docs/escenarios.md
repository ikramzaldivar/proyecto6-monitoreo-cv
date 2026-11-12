# Escenarios: entrada, comando, esperado y observado

Todas las corridas se ejecutaron el 11 nov 2026 (hora local; las horas UTC están en los
registros) con el commit `de41810`, salvo la referencia (`ad5229d`). Ningún archivo de
código, configuración ni escenarios tenía cambios sin commit (`run.json → git`).
Configuración `monitoreo-v1@2ea33802ba0c`, modelo YOLOX-Nano `c789161e…` y referencia
`config/referencia.json` (SHA-256 `4f55629e95b3…`, p_baja 0.3226). Los resultados
esperados están escritos en cada `escenarios/*.yaml` antes de la corrida.

Las puntuaciones salen siempre de `session.run` del modelo real. Ninguna se escribe ni se
ajusta a mano. Como el modelo es determinista, los mismos frames dan las mismas
puntuaciones en distintas corridas: por ejemplo, S5 frame 1 = 0.867 en C1 (#13), E1 (#1),
E2 (#1) y E3 (#1).

## C1 · Operación normal — `c1-normal-20261112T042108Z`

- **Entrada:** S1 (despejado, 12) → S5 (12) → S2 (17): 41 frames originales del carrito sin modificar.
- **Comando:** `python -m p6.monitor --escenario escenarios/c1-normal.yaml`
- **Esperado:** inferencias reales en 41 frames; las ventanas de S1, insuficientes; las de
  S5 y S2, suficientes con p_baja < 0.50; sin alertas ni fallos.
- **Observado:**

| Ventana | Frames | Puntuados | baja / duda / aceptada | Sin det. | p_baja | Estado | Reglas |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v1 | S1 #1–6 | 1 | 1/0/0 | 5 | null | insuficiente | baja: insuficiente · sostenida: insuficiente |
| v2 | S1 #7–12 | 0 | 0/0/0 | 6 | null | insuficiente | baja: insuficiente · sostenida: insuficiente |
| v3 | S5 #13–18 | 6 | 0/2/4 | 0 | 0.00 | suficiente | no cumple |
| v4 | S5 #19–24 | 6 | 0/1/5 | 0 | 0.00 | suficiente | no cumple |
| v5 | S2 #25–30 | 6 | 2/1/3 | 0 | 0.33 | suficiente | no cumple |
| v6 | S2 #31–36 | 5 | 1/3/1 | 1 | 0.20 | suficiente | no cumple |
| v7 | S2 #37–41 | 5 | 0/4/1 | 0 | 0.00 | suficiente | no cumple |

  Totales: aceptada 14 · duda 11 · baja 4 · sin detecciones 12 · error 0; p_baja 4/29 = 0.138.
  Alertas: 0. Capturas: 22 (11 duda, 4 baja, 7 muestra normal), todas vinculadas.
  FPS 2.047; inferencia p50 10.99 ms y p95 21.06 ms.
- **Lectura:** las dos primeras ventanas no se dan por sanas: el portal las marca como
  "evidencia insuficiente" (`evidencias/portal/15-ventana-c1-insuficiente.png`). C1 sí
  contiene frames de baja confianza (S1 #4 microwave 0.18; S2 #27, #29, #31), pero ninguna
  ventana llega a la proporción de la regla. Por eso no hay alerta, sin fabricar un estado
  sano.
- **Portal:** `01-tablero-c1.png`, `02-eventos-c1.png`, `03-evento-c1-aceptado.png`,
  `04-alertas-c1-vacio.png`.

## C2 · Baja confianza — `c2-baja-confianza-20261112T042129Z`

- **Entrada:** la escena de S5 con poca luz y desenfoque. Cada imagen se transformó con
  `GaussianBlur(3)` y `Brightness(0.30)` (`datos/preparadas/poca-luz/`, generada por
  `scripts/preparar_secuencias.py` y con SHA-256 de origen en su manifiesto). Son 12 frames.
- **Comando:** `python -m p6.monitor --escenario escenarios/c2-baja-confianza.yaml`
- **Umbrales y ventana:** inferior 0.40 y superior 0.70, ventana de 6 frames con mínimo 4,
  regla `baja-confianza-v1` (p_baja ≥ 0.50). Son los mismos que en C1.
- **Esperado:** la primera ventana cumple la regla y abre la alerta con los eventos de zona
  baja y sus capturas; la segunda ventana la resuelve.
- **Salidas del modelo (score_frame, clase top):** #1 0.303 tv · #2 0.252 tv · #3 0.299 person ·
  #4 0.272 tv · #5 0.361 person · #6 0.302 person · #7 0.236 person · #8 0.421 donut ·
  #9 0.706 person · #10 0.862 person · #11 0.756 person · #12 0.781 person.
  En la misma escena sin degradar (C1 #13–24) eran 0.47–0.88.
- **Observado:**
  - v1 (#1–6): 6 puntuados, los 6 en zona baja, p_baja = 1.00 → `baja-confianza-v1` **cumple**.
  - Alerta `c2-baja-confianza-20261112T042129Z-a01`, severidad advertencia, abierta
    04:21:32.114Z. Motivo: "6 de 6 frames puntuados con s < 0.4 (p_baja=1.00 >= 0.5)".
    Vincula la ventana v001 y los eventos f0001–f0006, cada uno con su captura.
    Inicio de la condición (captura de f0001): 04:21:29.594Z; tiempo de detección: 2.52 s.
  - v2 (#7–12): 1 baja, 1 duda, 4 aceptadas, p_baja = 0.17 → la alerta se **resuelve** a las 04:21:35.131Z.
  - Capturas: 9 (7 baja, 1 duda, 1 muestra normal), todas con archivo y SHA-256 válidos.
- **Portal:** `05-tablero-c2.png`, `06-eventos-c2-baja.png`, `07-alerta-c2.png`,
  `08-evento-c2-baja.png`, `14-capturas-revision.png` (revisión manual de f0001 y f0004).

## Escenarios adicionales

### E1 · Cambio sostenido — `e1-cambio-sostenido-20261112T042135Z`

- **Entrada:** S5 original (12) → S5 desenfocado, `GaussianBlur(7)` (12) → S5 con poca luz,
  la misma de C2 (12) → S5 original (12). Son 48 frames.
- **Esperado / observado:**

| Ventana | p_baja | Límite sostenido 0.623 | Racha | Alertas activas al cerrar |
| --- | --- | --- | --- | --- |
| v1, v2 (S5) | 0.00, 0.00 | no | 0 | 0 |
| v3 (desenfoque #13–18) | 1.00 | sí | 1 | 1 · abre `a01` baja-confianza |
| v4 (desenfoque #19–24) | 0.67 | sí | 2 | 1 · `a01` se actualiza |
| v5 (poca luz #25–30) | 1.00 | sí | 3 | 2 · abre `a02` **cambio-sostenido-v1** con las 3 ventanas y 15 eventos de zona baja |
| v6 (poca luz #31–36) | 0.17 | no | 0 | 0 · se resuelven `a01` y `a02` |
| v7, v8 (S5) | 0.00, 0.00 | no | 0 | 0 |

  Tiempo de detección de `a02`: 8.53 s desde la captura del primer frame bajo de la racha (#13).
- **Intento previo (no entregado como evidencia):** la primera versión de E1 usaba S5 y S2
  con desenfoque radio 7. Con S2 desenfocado el modelo casi no devolvía candidatas: las
  ventanas quedaron insuficientes y la racha nunca llegó a 3. Así lo define la regla (una
  ventana insuficiente no suma), así que no se cambió la regla: se cambió la entrada
  (commit `de41810`).
- **Portal:** `10-tablero-e1-sostenido.png`, `11-alerta-e1-sostenido.png`.

### E2 · Entradas corruptas (error de inferencia) — `e2-entradas-corruptas-20261112T042201Z`

- **Entrada:** S5 (12) → 5 archivos ilegibles (4 JPEG truncados al 30 % y 1 vacío) → S5 (12).
- **Observado:** #13–17 quedan con `status=error` y el mensaje del decodificador
  (`OSError: image file is truncated…`; el vacío da `UnidentifiedImageError`), sin
  puntuación ni zona y con sus bytes conservados como captura de motivo `error`.
  v3 (#13–18): 5 de 6 con error → `errores-inferencia-v1` **cumple** y abre `a01`
  (severidad alta) con los 5 eventos. v4 (#19–24): 0 de 6 con error → `a01` se resuelve.
  p_baja de v3 = null (1 puntuado, insuficiente): el error no se cuenta como baja confianza.
  Tasa de errores de la corrida: 5/29 = 0.172.
- **Portal:** `12-alerta-e2-errores.png`, `18-evento-e2-error.png`.

### E3 · Interrupción de la fuente — `e3-interrupcion-fuente-20261112T042216Z`

- **Entrada:** S5 (12) → pausa de 6 s sin frames → S2 (17).
- **Observado:** el último frame antes de la pausa (#12) se registró a las 04:22:21.733Z.
  A las 04:22:24.800Z (3.1 s sin frames) se abre `fuente-detenida-v1` (`a01`, severidad
  alta), que referencia el evento #12. El frame #13 se emite a las 04:22:27.718Z y la alerta
  se resuelve en ese instante; el procesamiento sigue. El FPS de la corrida baja a 1.486
  (contra 2.04–2.17 en las demás) porque la pausa cuenta en la duración.
- **Portal:** `13-alerta-e3-fuente.png`.

## Reproducir

```bash
python -m p6.monitor --escenario escenarios/c2-baja-confianza.yaml --salida /tmp/p6-repro
python scripts/recalcular_metricas.py /tmp/p6-repro/<run_id>
```

Las puntuaciones por frame deben coincidir con las de esta tabla, porque el modelo y las
entradas son los mismos. Tiempos, FPS y RAM variarán según el equipo.
[`evidencias/reproduccion.md`](../evidencias/reproduccion.md) documenta esta prueba
hecha desde un clon limpio.
