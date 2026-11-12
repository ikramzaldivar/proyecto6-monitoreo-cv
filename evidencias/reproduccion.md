# Reproducción desde un clon limpio

Hecha el 11 nov 2026 en el mismo equipo (Windows 11, Python 3.12.10), sobre un clon nuevo
del commit `b669f96` en `C:\tmp\p6-clon`, con un entorno virtual nuevo y los pesos
descargados de la URL pública. La salida de la corrida nueva se guardó fuera del
repositorio (`C:\tmp\p6-repro`).

```bash
git clone <repo> p6-clon && cd p6-clon
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python scripts/descargar_modelo.py --destino modelo/
set PYTHONPATH=src
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check .
.venv\Scripts\python scripts/recalcular_metricas.py --todas
.venv\Scripts\python -m p6.monitor --escenario escenarios/c2-baja-confianza.yaml --salida C:/tmp/p6-repro
.venv\Scripts\python scripts/recalcular_metricas.py C:/tmp/p6-repro/<run_id>
```

| Paso | Resultado |
| --- | --- |
| Descarga del modelo | SHA-256 `c789161e…` coincide con `modelo/descriptor.yaml` |
| `pytest -q` | 30 passed (incluida la integración con el modelo real) |
| `ruff check .` | sin hallazgos |
| Recálculo de las 6 corridas entregadas | todo coincide |
| SHA-256 de `config/monitoreo.yaml` / `config/referencia.json` en el clon | `2ea33802ba0c…` / `4f55629e95b3…`, iguales a los de `run.json` de las corridas |
| C2 de nuevo (`c2-baja-confianza-20261112T043158Z`) | **las 12 puntuaciones, zonas y listas de detecciones son idénticas** a las de la corrida entregada; misma alerta `baja-confianza-v1`, abierta en v1 y resuelta en v2 |

## Hallazgo corregido durante la reproducción

El recálculo independiente de la corrida nueva marcó una discrepancia en la métrica
adicional M5 (cobertura de trazabilidad): `metricas.json` decía 0.0 y el recálculo, 1.0.
La causa: `src/p6/metricas.py` deducía la raíz del repositorio a partir de la carpeta de la
corrida (`parents[2]`), lo que solo vale dentro de `evidencias/corridas/`. Con `--salida`
fuera del repositorio no encontraba las entradas. Se corrigió para usar la raíz del
paquete. Recalcular `metricas.json` de las seis corridas entregadas con el código
corregido da archivos idénticos, porque están dentro del repositorio. Después de la
corrección, el recálculo de la corrida nueva coincide por completo.

## Notas para reproducir en Windows

- Algunas rutas del repositorio llegan a 121 caracteres. Si el clon está en una carpeta
  profunda, Windows puede fallar con `Filename too long`. Clonar en una ruta corta o activar
  `git config --global core.longpaths true` antes de clonar.
- Tiempos, FPS, CPU y RAM cambian entre equipos; las puntuaciones no, porque el modelo y las
  entradas son los mismos.
