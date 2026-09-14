"""
test_dv360_pacing.py — dailyMaxMicros no debe volver a asignar budget total
como tope diario (hallazgo dry-run E2E 28/08, ver DEC_088).
Cubre los tres casos que motivaron el bug: division por duracion real del
flight (no divisor fijo), flight de 1 dia (caso limite), y flight invertido
(end < start) que debe fallar explicito en vez de degradar a divisor=1.
"""
import pytest
from scripts.dv360._common.pacing import daily_max_micros


def test_flight_31_dias():
    # Caso real del hallazgo: 5 EUR / 31 dias
    assert daily_max_micros(5.0, "2026-07-01", "2026-07-31") == 161290


def test_flight_1_dia():
    # Caso limite: start == end, debe ser 1 dia, no 0 (division por cero)
    assert daily_max_micros(10.0, "2026-07-01", "2026-07-01") == 10_000_000


def test_flight_invertido_falla_explicito():
    # end anterior a start: no debe degradar a divisor=1 (reintroduciria
    # el bug de asignar el budget total como tope diario)
    with pytest.raises(ValueError):
        daily_max_micros(5.0, "2026-07-31", "2026-07-01")


def test_redondeo_no_trunca():
    # round(), no int() — evita perder precision en la conversion a micros
    resultado = daily_max_micros(1.0, "2026-01-01", "2026-01-03")
    assert resultado == 333333
