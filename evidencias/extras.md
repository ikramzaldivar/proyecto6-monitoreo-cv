# Inventario de adicionales reclamados

No se reclaman como extra las vistas mínimas de eventos y alertas, los dos umbrales, las
capturas obligatorias, C1/C2 ni la regla sostenida documentada (R3.3): son base. Cada
elemento de esta tabla tiene un ID único, y el nivel solicitado es el mayor que considero
completamente demostrado. Las rutas de imagen son relativas a `evidencias/portal/`.

## F · Funcionalidades opcionales

| ID | Descripción | Nivel solicitado | Complejidad y evidencia | Doble conteo |
| --- | --- | --- | --- | --- |
| F1 | **Tablero con gráficas históricas por corrida** (`/`): tarjetas de todas las corridas con KPIs; para la corrida elegida, score por frame con zonas, umbrales y piso; p_baja por ventana con la línea de la regla, la de la referencia y la de referencia + tolerancia (ventanas insuficientes en gris); serie de alertas activas; tabla de métricas base | 10 | Consulta parametrizada (`?run=`); cada punto o barra lleva a su evento o ventana; datos persistidos (JSONL → SQLite); estado vacío ("La corrida no tiene eventos", "Sin ventanas evaluadas", "La corrida no generó alertas") y error (`/?run=nope` → 404). `01-tablero-c1.png`, `05-tablero-c2.png`, `10-tablero-e1-sostenido.png` | Es una sola funcionalidad (tablero y gráficas en la misma vista); no se reclama "dashboard" y "gráficas" por separado |
| F2 | **Revisión manual de capturas** (`/capturas`) | 10 | Galería filtrable por corrida, motivo, zona y estado de revisión; formulario de veredicto (`baja_confirmada`, `falsa_alarma`, `requiere_seguimiento`) con nota, persistido en `evidencias/revisiones.jsonl` (append-only) y visible en el detalle del evento; estados: veredicto inválido → 400, captura inexistente → 404, archivo ausente y bytes no decodificables con mensaje propio, "Ninguna captura cumple los filtros". `14-capturas-revision.png`, `08-evento-c2-baja.png` | El veredicto no modifica puntuaciones ni alertas |
| F3 | **Filtros avanzados de eventos** (`/eventos`) | 10 | Además de corrida y zona: status, resultado, clase detectada (subconsulta sobre candidatas), secuencia, score menor que X, solo capturados y paginación de 50; estado vacío (`17-eventos-filtro-vacio.png`) y error (`score_max=abc` → 400) | La vista mínima de eventos es base; se reclaman solo los filtros que van más allá de consultarla |
| F4 | **Exportación CSV de eventos** (`/export/eventos.csv`) | 5 | Descarga con los mismos filtros activos de F3 (19 columnas, incluye `imagen_ref` y `config_ref`); probada en `tests/test_monitor_real.py` vía portal y en el smoke test | Es una salida distinta (archivo), no otra vista |

## M · Métricas adicionales

Definiciones en [`docs/metricas.md`](../docs/metricas.md#métricas-adicionales-reclamadas-como-extra).
Todas se recalculan con `scripts/recalcular_metricas.py`
([`recalculo.txt`](recalculo.txt)).

| ID | Grupo | Métrica | Nivel solicitado | Justificación |
| --- | --- | --- | --- | --- |
| M1 | G1 | Tasa de errores técnicos | 5 | Proporción con población (frames procesados) y null sin datos; E2 da 5/29 = 0.172 y las demás 0 |
| M2 | G2 | Latencia de extremo a extremo p50/p95/máx | 5 | Distribución por corrida con puntos de medición declarados (emisión del frame → evento registrado, mismo reloj); distinta del FPS base |
| M3 | G4 | Proporción de frames sin detecciones | 5 | Población `status=ok`; excluye errores; C1 12/41, E1 1/48 |
| M4 | G4 | PSI de score_frame frente a la referencia | 5 | Compara la distribución con la referencia congelada, con intervalos, suavizado y null definidos. **No se pide 8:** el cambio controlado no se separa con claridad (C1 normal da 1.13, C2 1.39), límite documentado |
| M5 | G5 | Cobertura de trazabilidad | 5 | Campos requeridos más integridad de la entrada (SHA-256 contra el manifiesto); 100 % en las 6 corridas |
| M6 | G7 | Tiempo de detección | 8 | Correlaciona dos etapas (captura del primer frame que cumple la condición → apertura de la alerta) en casos con inicio controlado: C2 2.52 s, E1 sostenida 8.52 s (3 ventanas, como predice la regla), E2 2.52 s, E3 3.02 s (límite 3 s más el sondeo de 0.1 s) |
| M7 | G3 | CPU del proceso | 3 | Agregado simple (media y máximo) con psutil |
| M8 | G4 | Detecciones por clase y zona | 3 | Conteo con unidad declarada (candidata, no frame) |

## S · Escenarios adicionales

Detalle de entrada, esperado y observado en [`docs/escenarios.md`](../docs/escenarios.md#escenarios-adicionales).

| ID | Escenario | Corrida | Nivel solicitado | Etapas demostradas |
| --- | --- | --- | --- | --- |
| S1 | E1 · Cambio sostenido de confianza | `e1-cambio-sostenido-20261112T045149Z` | 8 | Transición (v3), persistencia por 3 ventanas suficientes y apertura de `cambio-sostenido-v1` (v5), recuperación y resolución (v6), estabilidad posterior (v7–v8). `10-…`, `11-alerta-e1-sostenido.png` |
| S2 | E2 · Error de inferencia por entradas corruptas | `e2-entradas-corruptas-20261112T045213Z` | 10 | Fallo (5 archivos ilegibles), diagnóstico (mensaje del decodificador por evento y bytes conservados), reacción (`errores-inferencia-v1`), recuperación (resolución en v4) y verificación posterior (v4–v5 con 0 errores; recálculo 19/19). `12-…`, `18-evento-e2-error.png` |
| S3 | E3 · Interrupción del stream | `e3-interrupcion-fuente-20261112T045228Z` | 8 | Interrupción de 6 s, alerta por tiempo a los 3.0 s, resolución con el primer frame nuevo, continuidad del procesamiento; efecto visible en el FPS. `13-alerta-e3-fuente.png` |

Ninguno repite C2: E1 prueba la regla sostenida (otra condición de aceptación) y E2/E3,
fallos técnicos con sus propias reglas.

## Suma solicitada

F 10 + 10 + 10 + 5 = 35 · M 5 + 5 + 5 + 5 + 5 + 8 + 3 + 3 = 39 · S 8 + 10 + 8 = 26 →
**100 puntos extra solicitados**, sujetos a la verificación del evaluador.
