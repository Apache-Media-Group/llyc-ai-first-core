"""
scripts/dv360/_common/pacing.py
Calculo de dailyMaxMicros para pacing PACING_TYPE_EVEN / PACING_PERIOD_DAILY.

DV360 API v4 exige dailyMaxMicros como tope diario explicito (DEC_088) —
no lo infiere del budget total ni de la duracion del flight. Esta funcion
centraliza ese calculo para create_io.py y create_line_item.py, evitando
divisores hardcodeados o ausencia de division (hallazgo dry-run E2E 28/08).
"""
from datetime import datetime


def daily_max_micros(budget_eur: float, start_date: str, end_date: str) -> int:
    """
    Calcula el tope diario en micros a partir del budget total y la
    duracion real del flight (inclusiva: end-start+1 dias).

    Lanza ValueError si end_date es anterior a start_date — un flight
    invertido no debe degradar silenciosamente a divisor=1 (que
    reintroduciria el bug de asignar el budget total como tope diario).
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    days = (end - start).days + 1
    if days <= 0:
        raise ValueError(
            f"end_date ({end_date}) es anterior a start_date ({start_date}) "
            f"— flight invertido, no se puede calcular dailyMaxMicros."
        )
    return round(budget_eur * 1_000_000 / days)
