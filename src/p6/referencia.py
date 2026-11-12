"""Congela la referencia de confianza a partir de una corrida.

    python -m p6.referencia evidencias/corridas/<run_id> --salida config/referencia.json

La referencia guarda, para la poblacion de frames puntuados de esa corrida: p_baja,
conteo por zona, distribucion de `score_frame` en los cortes de `p6.metricas.BINS`,
percentiles y la p_baja de cada ventana suficiente. La regla `cambio-sostenido` compara
contra `p_baja`; la metrica adicional PSI compara contra `distribucion`.

Para que la comparacion sea valida, las corridas posteriores deben usar el mismo modelo,
preprocesamiento y umbrales; se registran aqui para comprobarlo.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from p6.fuente import utc_iso
from p6.metricas import BINS, distribucion, leer_jsonl, percentil


def construir(dir_run: Path) -> dict:
    run = json.loads((dir_run / "run.json").read_text(encoding="utf-8"))
    eventos = leer_jsonl(dir_run / "eventos.jsonl")
    ventanas = leer_jsonl(dir_run / "ventanas.jsonl")
    puntuados = [e for e in eventos if e["status"] == "ok" and e["score_frame"] is not None]
    if not puntuados:
        raise SystemExit("la corrida no tiene frames puntuados: no puede ser referencia")
    scores = [e["score_frame"] for e in puntuados]
    zonas = Counter(e["zona_frame"] for e in puntuados)
    return {
        "run_id": run["run_id"],
        "creada_utc": utc_iso(),
        "git": run["git"],
        "config_ref": run["config_ref"],
        "modelo": run["modelo"],
        "politica": run["politica"],
        "unidad": "frame puntuado (status=ok con al menos una candidata)",
        "n_frames": len(eventos),
        "n_puntuados": len(puntuados),
        "sin_detecciones": sum(e["status"] == "ok" and e["score_frame"] is None for e in eventos),
        "errores": sum(e["status"] == "error" for e in eventos),
        "zonas": {k: zonas[k] for k in ("aceptada", "duda", "baja")},
        "p_baja": zonas["baja"] / len(puntuados),
        "score_frame_percentiles": {f"p{q}": percentil(scores, q / 100) for q in (10, 25, 50, 75, 90)},
        "bins": list(BINS[:-1]) + [1.0],
        "distribucion": distribucion(scores),
        "p_baja_por_ventana": [
            {"ventana_id": v["ventana_id"], "p_baja": v["p_baja"]}
            for v in ventanas
            if v["p_baja"] is not None
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Congela config/referencia.json")
    ap.add_argument("corrida", type=Path)
    ap.add_argument("--salida", type=Path, required=True)
    args = ap.parse_args(argv)
    ref = construir(args.corrida)
    args.salida.write_text(json.dumps(ref, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: ref[k] for k in ("run_id", "n_puntuados", "zonas", "p_baja")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
