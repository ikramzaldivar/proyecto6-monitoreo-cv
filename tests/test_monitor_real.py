"""Integracion con el modelo real sobre frames del carrito (se omite sin pesos)."""

import json
from pathlib import Path

import pytest
import yaml

from p6 import config, metricas
from p6.fuente import cargar_escenario
from p6.monitor import Monitor
from p6.portal import crear_app

RAIZ = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not (RAIZ / "modelo" / "yolox_nano.onnx").is_file(),
    reason="faltan los pesos: python scripts/descargar_modelo.py --destino modelo/",
)


def test_corrida_corta_con_modelo_real(tmp_path):
    esc = tmp_path / "esc.yaml"
    esc.write_text(
        yaml.safe_dump(
            {
                "escenario_id": "prueba",
                "descripcion": "prueba",
                "segmentos": [
                    {"manifiesto": "datos/carrito/capturas.csv", "secuencias": ["S5"]},
                    {"manifiesto": "datos/preparadas/corruptas/capturas.csv"},
                ],
            }
        ),
        encoding="utf-8",
    )
    cfg = config.cargar(RAIZ / "config" / "monitoreo.yaml")
    escenario, items = cargar_escenario(esc)
    mon = Monitor(cfg, escenario, tmp_path / "corridas")
    d = mon.ejecutar(items[:2] + items[-3:])
    eventos = metricas.leer_jsonl(d / "eventos.jsonl")
    assert len(eventos) == 5
    assert [e["status"] for e in eventos] == ["ok"] * 2 + ["error"] * 3
    assert all(e["score_frame"] is None and e["zona_frame"] is None for e in eventos[2:])
    assert eventos[0]["score_frame"] > 0.7  # S5 frame 1: el modelo lo puntua alto
    capturas = metricas.leer_jsonl(d / "capturas.jsonl")
    assert all((d / c["image_ref"]).is_file() for c in capturas)
    alertas = metricas.leer_jsonl(d / "alertas.jsonl")
    assert any(a["rule_id"] == "errores-inferencia-v1" for a in alertas)
    met = json.loads((d / "metricas.json").read_text(encoding="utf-8"))["metricas"]
    assert met["G5_imagenes_vinculadas"]["valor"] == 1.0
    assert met["G1x_tasa_errores"]["valor"] == 3 / 5

    app = crear_app(tmp_path / "corridas", tmp_path / "p.sqlite", tmp_path / "rev.jsonl")
    c = app.test_client()
    assert c.get("/eventos").status_code == 200
    assert c.get(f"/eventos/{eventos[-1]['event_id']}").status_code == 200
    alert_id = alertas[0]["alert_id"]
    assert alert_id.encode() in c.get("/alertas").data
    assert c.get(f"/alertas/{alert_id}").status_code == 200
    assert c.get("/eventos/no-existe").status_code == 404
