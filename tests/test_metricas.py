import math

from p6.metricas import distribucion, percentil, psi


def test_percentil_nearest_rank():
    valores = [5, 1, 4, 2, 3]
    assert percentil(valores, 0.5) == 3
    assert percentil(valores, 0.95) == 5
    assert percentil(valores, 0.2) == 1
    assert percentil([], 0.5) is None


def test_distribucion_incluye_el_1_y_excluye_bajo_el_piso():
    assert distribucion([0.10, 0.39, 0.40, 0.99, 1.0, 0.05]) == [1, 1, 1, 0, 0, 2]


def test_psi_cero_si_igual_y_none_sin_datos():
    assert psi([1, 2, 3, 0, 0, 4], [2, 4, 6, 0, 0, 8]) == 0
    assert psi([0] * 6, [1] * 6) is None
    alto = psi([6, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 6])
    assert math.isfinite(alto) and alto > 1
