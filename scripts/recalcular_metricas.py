"""Recalculo independiente de una corrida (no importa el paquete `p6`).

    python scripts/recalcular_metricas.py evidencias/corridas/<run_id> [...]
    python scripts/recalcular_metricas.py --todas

Desde los JSONL y la config congelada de la corrida vuelve a obtener, con codigo propio:

1. la zona de cada evento a partir de su `score_frame` y los umbrales de la config;
2. los conteos, p_baja y el resultado de las reglas de cada ventana a partir de sus eventos;
3. que cada alerta abierta corresponde a una ventana que cumple su regla y que sus
   event_ids existen;
4. las metricas base G1-G7 de `metricas.json` (y el PSI adicional).

Imprime cada comprobacion y sale con codigo 1 si alguna no coincide.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
TOL = 1e-9


def jsonl(ruta: Path) -> list[dict]:
    return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines() if x.strip()]


def nearest_rank(valores: list[float], q: float) -> float:
    orden = sorted(valores)
    return orden[max(1, math.ceil(q * len(orden))) - 1]


def segundos(a: str) -> float:
    return datetime.fromisoformat(a.replace("Z", "+00:00")).timestamp()


class Verificador:
    def __init__(self) -> None:
        self.fallos = 0
        self.total = 0

    def igual(self, nombre: str, obtenido, esperado) -> None:
        self.total += 1
        if isinstance(obtenido, float) or isinstance(esperado, float):
            ok = obtenido is not None and esperado is not None and abs(obtenido - esperado) <= TOL
        else:
            ok = obtenido == esperado
        if not ok:
            self.fallos += 1
        marca = "OK   " if ok else "FALLA"
        print(f"  {marca} {nombre}: recalculado={obtenido!r} registrado={esperado!r}")


def verificar(d: Path) -> int:
    print(f"\n== {d.name}")
    v = Verificador()
    cfg = yaml.safe_load((d / "config" / "monitoreo.yaml").read_text(encoding="utf-8"))
    inf, sup = cfg["politica"]["umbral_inferior"], cfg["politica"]["umbral_superior"]
    minimo = cfg["ventanas"]["minimo_puntuados"]
    reglas = cfg["reglas"]
    eventos = jsonl(d / "eventos.jsonl")
    ventanas = jsonl(d / "ventanas.jsonl")
    alertas = jsonl(d / "alertas.jsonl")
    capturas = jsonl(d / "capturas.jsonl")
    met = json.loads((d / "metricas.json").read_text(encoding="utf-8"))["metricas"]
    ref_ruta = d / "config" / "referencia.json"
    ref = json.loads(ref_ruta.read_text(encoding="utf-8")) if ref_ruta.is_file() else None

    # 1. zonas por evento
    malas = 0
    for e in eventos:
        s = e["score_frame"]
        z = None if s is None else ("aceptada" if s >= sup else "duda" if s >= inf else "baja")
        top = max((x["score"] for x in e["detections"]), default=None)
        malas += z != e["zona_frame"] or top != s
    v.igual("eventos con zona y score_frame consistentes", len(eventos) - malas, len(eventos))

    # 2. ventanas
    por_id = {e["event_id"]: e for e in eventos}
    racha = 0
    p_ref = ref["p_baja"] if ref else None
    tol = reglas["cambio_sostenido"]["tolerancia"]
    k = reglas["cambio_sostenido"]["ventanas_consecutivas"]
    ventanas_ok = 0
    esperadas: dict[str, dict] = {}
    for w in ventanas:
        evs = [por_id[i] for i in w["event_ids"]]
        errores = sum(e["status"] == "error" for e in evs)
        punt = [e for e in evs if e["status"] == "ok" and e["score_frame"] is not None]
        baja = sum(e["zona_frame"] == "baja" for e in punt)
        p = baja / len(punt) if len(punt) >= minimo and punt else None
        rb = (
            "insuficiente"
            if p is None
            else ("cumple" if p >= reglas["baja_confianza"]["proporcion_minima"] else "no_cumple")
        )
        if p_ref is None:
            rs = "inactiva"
        elif p is None:
            rs = "insuficiente"
        elif p > p_ref + tol:
            racha += 1
            rs = "cumple" if racha >= k else "no_cumple"
        else:
            racha = 0
            rs = "no_cumple"
        re_ = reglas["errores_inferencia"]
        if len(evs) < re_["minimo_intentos"]:
            rerr = "insuficiente"
        else:
            rerr = "cumple" if errores / len(evs) >= re_["proporcion_minima"] else "no_cumple"
        calc = {"baja_confianza": rb, "cambio_sostenido": rs, "errores_inferencia": rerr}
        esperadas[w["ventana_id"]] = calc
        mismo_p = (p is None and w["p_baja"] is None) or (
            p is not None and w["p_baja"] is not None and abs(p - w["p_baja"]) < TOL
        )
        ventanas_ok += mismo_p and calc == w["reglas"] and w["conteos"]["baja"] == baja
    v.igual("ventanas con p_baja y reglas recalculadas iguales", ventanas_ok, len(ventanas))

    # 3. alertas
    aperturas = [a for a in alertas if a["registro"] == "apertura"]
    validas = 0
    for a in aperturas:
        refs_ok = all(e in por_id for e in a["event_ids"])
        if a["regla"] == "fuente_detenida":
            cond = a["observado"]["segundos_sin_frames"] > a["condicion"]["limite_sin_frames_s"]
        else:
            cond = esperadas.get(a["ventana_ids"][-1], {}).get(a["regla"]) == "cumple"
        validas += refs_ok and cond
    v.igual("alertas abiertas que cumplen su regla y cuyos eventos existen", validas, len(aperturas))

    # 4. metricas base
    ok = [e for e in eventos if e["status"] == "ok"]
    t = [e["tiempos_ms"]["modelo"] for e in ok]
    if t:
        v.igual(
            "G1 p50 tiempo de inferencia (ms)", nearest_rank(t, 0.5), met["G1_tiempo_inferencia_ms"]["p50"]
        )
        v.igual(
            "G1 p95 tiempo de inferencia (ms)", nearest_rank(t, 0.95), met["G1_tiempo_inferencia_ms"]["p95"]
        )
    if len(eventos) >= 2:
        fps = len(eventos) / (segundos(eventos[-1]["timestamp"]) - segundos(eventos[0]["t_captura"]))
        v.igual("G2 FPS de procesamiento", fps, met["G2_fps_procesamiento"]["valor"])
    rss = [e["recursos"]["rss_mb"] for e in eventos]
    v.igual("G3 RSS max (MB)", max(rss), met["G3_rss_mb"]["max"])
    punt = [e for e in ok if e["score_frame"] is not None]
    if punt:
        v.igual(
            "G4 p_baja", sum(e["zona_frame"] == "baja" for e in punt) / len(punt), met["G4_p_baja"]["valor"]
        )
    if capturas:
        ids = set(por_id)
        vinc = sum(
            (d / c["image_ref"]).is_file()
            and hashlib.sha256((d / c["image_ref"]).read_bytes()).hexdigest() == c["sha256"]
            and c["event_id"] in ids
            for c in capturas
        )
        v.igual("G5 imagenes vinculadas", vinc / len(capturas), met["G5_imagenes_vinculadas"]["valor"])
    desc = yaml.safe_load((d / "config" / "descriptor.yaml").read_text(encoding="utf-8"))
    v.igual(
        "G6 version esperada vs reportada",
        sum(e["model"]["sha256"] == desc["sha256"] for e in eventos) / len(eventos),
        met["G6_version_esperada_vs_reportada"]["valor"],
    )
    # G7: alertas abiertas en algun instante de (cierre anterior, cierre de la ventana]
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    abre = {a["alert_id"]: segundos(a["timestamp"]) for a in aperturas}
    cierra = {a["alert_id"]: segundos(a["timestamp"]) for a in alertas if a["registro"] == "resolucion"}
    serie, desde = [], segundos(run["inicio_utc"])
    for w in ventanas:
        hasta = segundos(w["evaluada_utc"])
        serie.append(len([k for k, t0 in abre.items() if t0 <= hasta and cierra.get(k, math.inf) > desde]))
        desde = hasta
    v.igual("G7 alertas activas por ventana", serie, met["G7_alertas_activas"]["serie"])
    if ref and punt:
        cortes = ref["bins"]
        dist = [0] * (len(cortes) - 1)
        for e in punt:
            for i in range(len(cortes) - 1):
                ultimo = i == len(cortes) - 2
                if cortes[i] <= e["score_frame"] and (e["score_frame"] < cortes[i + 1] or ultimo):
                    dist[i] += 1
                    break
        na, nr = sum(dist), sum(ref["distribucion"])
        psi = sum(
            (max(a / na, 1e-4) - max(r / nr, 1e-4)) * math.log(max(a / na, 1e-4) / max(r / nr, 1e-4))
            for a, r in zip(dist, ref["distribucion"], strict=True)
        )
        v.igual("G4x PSI frente a referencia", psi, met["G4x_psi_referencia"]["valor"])

    # 5. metricas adicionales
    n = len(eventos)
    v.igual(
        "G1x tasa de errores",
        sum(e["status"] == "error" for e in eventos) / n,
        met["G1x_tasa_errores"]["valor"],
    )
    e2e = [e["tiempos_ms"]["extremo_a_extremo"] for e in eventos]
    v.igual("G2x latencia e2e p95 (ms)", nearest_rank(e2e, 0.95), met["G2x_latencia_e2e_ms"]["p95"])
    cpu = [e["recursos"]["cpu_pct_proceso"] for e in eventos[1:]]
    if cpu:
        v.igual("G3x CPU media (%)", sum(cpu) / len(cpu), met["G3x_cpu_pct_proceso"]["media"])
    if ok:
        sin = sum(e["score_frame"] is None for e in ok)
        v.igual("G4x frames sin detecciones", sin / len(ok), met["G4x_sin_detecciones"]["valor"])
    clases: dict[str, int] = {}
    for e in ok:
        for x in e["detections"]:
            clases[x["class_name"]] = clases.get(x["class_name"], 0) + 1
    v.igual(
        "G4x detecciones por clase (total)",
        clases,
        {k: c["total"] for k, c in met["G4x_detecciones_por_clase"].items()},
    )
    campos = ("event_id", "run_id", "frame_id", "timestamp", "source_id", "model")
    campos += ("status", "config_ref", "ventana_id", "entrada")
    completos = 0
    for e in eventos:
        entrada = RAIZ / e["entrada"]["ruta"]
        integra = (
            entrada.is_file()
            and hashlib.sha256(entrada.read_bytes()).hexdigest() == e["entrada"]["sha256_manifiesto"]
        )
        completos += all(e.get(c) not in (None, "") for c in campos) and integra
    v.igual("G5x cobertura de trazabilidad", completos / n, met["G5x_cobertura_trazabilidad"]["valor"])
    tdet = {
        a["alert_id"]: segundos(a["timestamp"]) - segundos(a["inicio_condicion"])
        for a in aperturas
        if a.get("inicio_condicion")
    }
    registrado = {k: x["valor"] for k, x in met["G7x_tiempo_deteccion_s"].items()}
    v.igual("G7x tiempo de deteccion (s)", tdet, registrado)
    print(f"  -> {v.total - v.fallos}/{v.total} comprobaciones coinciden")
    return v.fallos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corridas", nargs="*", type=Path)
    ap.add_argument("--todas", action="store_true", help="todas las de evidencias/corridas")
    args = ap.parse_args()
    dirs = args.corridas
    if args.todas:
        dirs = sorted(p for p in (RAIZ / "evidencias" / "corridas").iterdir() if (p / "run.json").is_file())
    if not dirs:
        ap.error("indica una corrida o --todas")
    fallos = sum(verificar(d) for d in dirs)
    print("\nRESULTADO:", "todo coincide" if fallos == 0 else f"{fallos} discrepancias")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
