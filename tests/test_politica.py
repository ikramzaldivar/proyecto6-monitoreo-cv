import pytest

from p6.politica import score_frame, zona


@pytest.mark.parametrize(
    ("s", "esperada"),
    [
        (0.70, "aceptada"),
        (0.95, "aceptada"),
        (0.6999, "duda"),
        (0.40, "duda"),
        (0.3999, "baja"),
        (0.0, "baja"),
    ],
)
def test_zonas_en_los_bordes(s, esperada):
    # igualdad con el inferior es duda; con el superior, aceptada
    assert zona(s, 0.40, 0.70) == esperada


def test_sin_puntuacion_no_tiene_zona():
    assert zona(None, 0.40, 0.70) is None


@pytest.mark.parametrize(("inf", "sup"), [(0.7, 0.4), (0.5, 0.5), (-0.1, 0.5), (0.2, 1.1)])
def test_umbrales_invalidos(inf, sup):
    with pytest.raises(ValueError):
        zona(0.5, inf, sup)


def test_score_frame_es_el_maximo_o_none():
    assert score_frame([0.2, 0.81, 0.5]) == 0.81
    assert score_frame([]) is None
