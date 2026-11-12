# Reproducción desde un clon limpio

Hecha el 11 nov 2026 (hora local) en Windows 11 con Python 3.12.10, sobre un clon nuevo
**desde GitHub** del commit `35d82b1` en `C:\tmp\rp`, con un entorno virtual nuevo y los
pesos descargados de la URL pública. Las corridas nuevas se guardaron fuera del
repositorio, en `C:\tmp\rp-out`.

```bash
git clone https://github.com/ikramzaldivar/proyecto6-monitoreo-cv.git rp && cd rp
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python scripts/descargar_modelo.py --destino modelo/
set PYTHONPATH=src
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check .
.venv\Scripts\python scripts/recalcular_metricas.py --todas
# para cada escenario c1-normal, c2-baja-confianza, e1-…, e2-…, e3-…:
.venv\Scripts\python -m p6.monitor --escenario escenarios/<escenario>.yaml --salida C:/tmp/rp-out
.venv\Scripts\python scripts/recalcular_metricas.py C:/tmp/rp-out/<run_id>
```

| Paso | Resultado |
| --- | --- |
| Descarga del modelo | SHA-256 `c789161e…` coincide con `modelo/descriptor.yaml` |
| `pytest -q` | 30 passed (incluida la integración con el modelo real) |
| `ruff check .` | sin hallazgos |
| Recálculo de las 6 corridas entregadas | 114/114 comprobaciones coinciden |
| SHA-256 de `config/monitoreo.yaml` / `config/referencia.json` en el clon | `2ea33802ba0c…` / `5b42974101f9…`, iguales a los de `run.json` de C1–E3 |
| C1, C2, E1, E2 y E3 de nuevo | Para los 5 escenarios: **listas de detecciones idénticas** a las entregadas, **la misma secuencia de alertas** (regla, registro y ventanas) y **la misma serie G7**. Recálculo de las corridas nuevas: 19/19 en cada una |

Las corridas nuevas registran `git.commit = 35d82b1` sin cambios locales. Entre `cce0f6c`
(commit de las corridas entregadas) y `35d82b1` no cambia código, configuración, escenarios,
scripts ni pruebas (`git diff cce0f6c 35d82b1 -- src config escenarios scripts tests` vacío).

## Historial de hallazgos

- **Primera reproducción (commit `b669f96`).** El recálculo independiente encontró que M5
  (cobertura de trazabilidad) daba 0.0 cuando la corrida se guarda fuera del repositorio:
  la raíz se deducía de la carpeta de la corrida. Se corrigió en `29b6725`.
- **Autoevaluación con la rúbrica.** G7 solo contaba las alertas abiertas en el instante
  del cierre de cada ventana y dejaba en cero la alerta de fuente detenida de E3. Se
  corrigió en `7c4a1b8` (alertas activas en cualquier instante de la ventana) y todas las
  corridas se regeneraron con el código final.

## Notas para reproducir en Windows

- Algunas rutas del repositorio llegan a 121 caracteres. Si el clon está en una carpeta
  profunda, Windows puede fallar con `Filename too long`. Clonar en una ruta corta o activar
  `git config --global core.longpaths true` antes de clonar.
- Tiempos, FPS, CPU y RAM cambian entre equipos; las puntuaciones no, porque el modelo y las
  entradas son los mismos.
