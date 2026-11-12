from pathlib import Path

import pytest
import yaml

from p6.config import ConfigError, cargar

CONFIG = Path(__file__).resolve().parents[1] / "config" / "monitoreo.yaml"


def escribir(tmp_path, cambio):
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cambio(data)
    ruta = tmp_path / "monitoreo.yaml"
    ruta.write_text(yaml.safe_dump(data), encoding="utf-8")
    return ruta


def test_config_versionada_es_valida():
    cfg = cargar(CONFIG)
    assert 0 <= cfg.umbral_inferior < cfg.umbral_superior <= 1
    assert cfg.config_ref.startswith("monitoreo-v1@")
    assert set(cfg.reglas) == {
        "baja_confianza",
        "cambio_sostenido",
        "errores_inferencia",
        "fuente_detenida",
    }


@pytest.mark.parametrize(
    "cambio",
    [
        lambda d: d["politica"].update(umbral_inferior=0.8),
        lambda d: d["politica"].update(umbral_superior=1.2),
        lambda d: d["ventanas"].update(minimo_puntuados=99),
        lambda d: d["fuente"].update(fps=0),
        lambda d: d["reglas"]["baja_confianza"].update(proporcion_minima=1.5),
        lambda d: d.update(extra=1),
        lambda d: d["captura"].update(zonas=["rara"]),
    ],
)
def test_config_invalida_se_rechaza(tmp_path, cambio):
    with pytest.raises(ConfigError):
        cargar(escribir(tmp_path, cambio))
