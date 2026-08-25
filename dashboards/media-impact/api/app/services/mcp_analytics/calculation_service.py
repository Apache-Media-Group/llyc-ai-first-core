"""Servicio de cálculos con precisión decimal para métricas de GA4.

Este servicio proporciona funciones de cálculo precisas para ratios, porcentajes
y métricas derivadas, utilizando el módulo Decimal de Python para evitar
errores de precisión en operaciones de punto flotante.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Union, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Plantilla para 2 decimales (estándar de reporting)
TWO_DECIMALS = Decimal('0.01')
# Plantilla para 4 decimales (para cálculos internos)
FOUR_DECIMALS = Decimal('0.0001')


class CalculationService:
    """Servicio centralizado para cálculos de métricas con precisión decimal."""

    @staticmethod
    def to_decimal(value: Union[int, float, str,None]) -> Decimal:
        """
        Convierte un valor a Decimal de forma segura.
        
        Args:
            value: Valor a convertir (int, float, str)
            
        Returns:
            Decimal: Valor convertido, o Decimal('0') si hay error
        """
        if value is None:
            return Decimal('0')
        
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as e:
            logger.warning(f"Error converting {value} to Decimal: {e}")
            return Decimal('0')

    @staticmethod
    def calculate_percentage(
        numerator: Union[int, float, Decimal],
        denominator: Union[int, float, Decimal],
        decimals: int = 2
    ) -> float:
        """
        Calcula un porcentaje con precisión decimal.
        
        Args:
            numerator: Numerador
            denominator: Denominador
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: Porcentaje redondeado. 0.0 si denominador es 0.
            
        Example:
            >>> calculate_percentage(1234, 7943, 2)
            15.54
        """
        num = CalculationService.to_decimal(numerator)
        den = CalculationService.to_decimal(denominator)
        
        if den == 0:
            return 0.0
        
        percentage = (num / den * 100).quantize(
            Decimal(10) ** -decimals,
            rounding=ROUND_HALF_UP
        )
        
        return float(percentage)

    @staticmethod
    def calculate_ratio(
        numerator: Union[int, float, Decimal],
        denominator: Union[int, float, Decimal],
        decimals: int = 2
    ) -> float:
        """
        Calcula un ratio (división simple) con precisión decimal.
        
        Args:
            numerator: Numerador
            denominator: Denominador
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: Ratio redondeado. 0.0 si denominador es 0.
            
        Example:
            >>> calculate_ratio(12345, 7943, 2)
            1.55
        """
        num = CalculationService.to_decimal(numerator)
        den = CalculationService.to_decimal(denominator)
        
        if den == 0:
            return 0.0
        
        ratio = (num / den).quantize(
            Decimal(10) ** -decimals,
            rounding=ROUND_HALF_UP
        )
        
        return float(ratio)

    @staticmethod
    def calculate_conversion_rate(
        conversions: Union[int, float],
        sessions: Union[int, float],
        decimals: int = 2
    ) -> float:
        """
        Calcula tasa de conversión con precisión decimal.
        
        Formula: (conversions / sessions) * 100
        
        Args:
            conversions: Número de conversiones
            sessions: Número de sesiones
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: Tasa de conversión en porcentaje. 0.0 si sessions es 0.
            
        Example:
            >>> calculate_conversion_rate(1234.5, 79436.0, 2)
            1.55
        """
        return CalculationService.calculate_percentage(conversions, sessions, decimals)

    @staticmethod
    def calculate_drop_rate(
        previous_count: Union[int, float],
        current_count: Union[int, float],
        decimals: int = 2
    ) -> float:
        """
        Calcula tasa de abandono entre dos pasos de un funnel.
        
        Formula: ((previous - current) / previous) * 100
        
        Args:
            previous_count: Contador del paso anterior
            current_count: Contador del paso actual
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: Tasa de abandono en porcentaje. 0.0 si previous_count es 0.
            
        Example:
            >>> calculate_drop_rate(10000, 7500, 2)
            25.00
        """
        prev = CalculationService.to_decimal(previous_count)
        curr = CalculationService.to_decimal(current_count)
        
        if prev == 0:
            return 0.0
        
        # Asegurar que drop no sea negativo (si current > previous)
        drop = max(prev - curr, Decimal('0'))
        
        drop_rate = (drop / prev * 100).quantize(
            Decimal(10) ** -decimals,
            rounding=ROUND_HALF_UP
        )
        
        return float(drop_rate)

    @staticmethod
    def calculate_engagement_rate(
        engaged_sessions: Union[int, float],
        total_sessions: Union[int, float],
        decimals: int = 2
    ) -> float:
        """
        Calcula tasa de engagement.
        
        Formula: (engaged_sessions / total_sessions) * 100
        
        Args:
            engaged_sessions: Sesiones con engagement
            total_sessions: Total de sesiones
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: Tasa de engagement en porcentaje. 0.0 si total_sessions es 0.
        """
        return CalculationService.calculate_percentage(engaged_sessions, total_sessions, decimals)

    @staticmethod
    def calculate_bounce_rate(
        bounces: Union[int, float],
        sessions: Union[int, float],
        decimals: int = 2
    ) -> float:
        """
        Calcula tasa de rebote (bounce).
        
        Nota: En GA4, bounceRate viene pre-calculado desde la API como ratio (0.0-1.0).
        Si recibes el valor directo de GA4, usa convert_ga4_rate_to_percentage.
        
        Formula: (bounces / sessions) * 100
        
        Args:
            bounces: Número de rebotes
            sessions: Total de sesiones
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: Tasa de rebote en porcentaje. 0.0 si sessions es 0.
        """
        return CalculationService.calculate_percentage(bounces, sessions, decimals)

    @staticmethod
    def convert_ga4_rate_to_percentage(
        ga4_rate: Union[float, str],
        decimals: int = 2
    ) -> float:
        """
        Convierte un rate de GA4 (0.0-1.0) a porcentaje (0-100).
        
        GA4 devuelve métricas como engagementRate y bounceRate como decimales
        (ej: 0.6543 = 65.43%). Esta función convierte y redondea correctamente.
        
        Args:
            ga4_rate: Valor del rate desde GA4 API (0.0-1.0)
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: Porcentaje redondeado (0-100)
            
        Example:
            >>> convert_ga4_rate_to_percentage(0.65432, 2)
            65.43
        """
        rate = CalculationService.to_decimal(ga4_rate)
        percentage = (rate * 100).quantize(
            Decimal(10) ** -decimals,
            rounding=ROUND_HALF_UP
        )
        return float(percentage)

    @staticmethod
    def calculate_average(
        total: Union[int, float, Decimal],
        count: Union[int, float, Decimal],
        decimals: int = 2
    ) -> float:
        """
        Calcula un promedio con precisión decimal.
        
        Args:
            total: Suma total
            count: Número de elementos
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: Promedio redondeado. 0.0 si count es 0.
            
        Example:
            >>> calculate_average(12345, 100, 2)
            123.45
        """
        return CalculationService.calculate_ratio(total, count, decimals)

    @staticmethod
    def calculate_aov(
        revenue: Union[float, Decimal],
        transactions: Union[int, float, Decimal],
        decimals: int = 2
    ) -> float:
        """
        Calcula Average Order Value (valor promedio del pedido).
        
        Formula: revenue / transactions
        
        Args:
            revenue: Ingresos totales
            transactions: Número de transacciones
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: AOV redondeado. 0.0 si transactions es 0.
            
        Example:
            >>> calculate_aov(125430.50, 523, 2)
            239.83
        """
        return CalculationService.calculate_ratio(revenue, transactions, decimals)

    @staticmethod
    def calculate_sniper_score(
        conversions: Union[int, float],
        avg_duration: Union[int, float],
        pages_per_session: Union[int, float]
    ) -> float:
        """
        Calcula el Sniper Score v3+ (High Intent AI Score).
        
        Formula: S(c, d, p) = B(c) + [30 / log10((d * p) + 10)]
        Donde B(c) = 70 si conversiones > 0, else 0.
        
        Args:
            conversions: Número de conversiones
            avg_duration: Duración media en segundos
            pages_per_session: Páginas por sesión
            
        Returns:
            float: Score de 0 a 100.
        """
        import math
        try:
            c = float(conversions)
            d = float(avg_duration)
            p = float(pages_per_session)
            
            base_bonus = 70.0 if c > 0 else 0.0
            friction = (d * p) + 10.0
            denominator = math.log10(friction)
            if denominator <= 0:
                denominator = 1.0
                
            score = base_bonus + (30.0 / denominator)
            return round(float(min(100.0, score)), 1)
        except Exception as e:
            logger.error(f"Error calculating sniper score: {e}")
            return 0.0

    @staticmethod
    def calculate_confidence_index(
        known_ai_sessions: int,
        total_sessions: int
    ) -> Dict[str, Any]:
        """
        Calcula el Índice de Confianza dinámico del análisis.
        
        Formula: Confianza = (Factor_volumen * 0.70) + (Factor_ratio * 0.30)
        
        Args:
            known_ai_sessions (n): Sesiones IA referidas conocidas
            total_sessions (U): Total sesiones del site
            
        Returns:
            Dict: Con score (0-1), label (Baja, Media, Alta) y explicación.
        """
        n = int(known_ai_sessions)
        u = int(total_sessions)
        
        if u == 0:
            return {"score": 0.0, "label": "Baja", "percentage": "0%"}
            
        # Factor Volumen (techo en 1000 sesiones, peso 70%)
        factor_volumen = min(n / 1000.0, 1.0)
        
        # Factor Ratio (óptimo en 5% del tráfico, peso 30%)
        factor_ratio = min((n / u) / 0.05, 1.0)
        
        confidence_score = (factor_volumen * 0.70) + (factor_ratio * 0.30)
        
        label = "Baja"
        if confidence_score > 0.60:
            label = "Alta"
        elif confidence_score >= 0.30:
            label = "Media"
            
        return {
            "score": round(confidence_score, 3),
            "label": label,
            "percentage": f"{round(confidence_score * 100, 1)}%",
            "known_ai_sessions": n,
            "total_sessions": u
        }

    @staticmethod
    def safe_divide(
        numerator: Union[int, float, Decimal],
        denominator: Union[int, float, Decimal],
        default: float = 0.0,
        decimals: int = 2
    ) -> float:
        """
        División segura que retorna un valor por defecto si el denominador es 0.
        
        Args:
            numerator: Numerador
            denominator: Denominador
            default: Valor a retornar si denominator es 0 (default: 0.0)
            decimals: Número de decimales (default: 2)
            
        Returns:
            float: Resultado de la división o valor por defecto
        """
        num = CalculationService.to_decimal(numerator)
        den = CalculationService.to_decimal(denominator)
        
        if den == 0:
            return default
        
        result = (num / den).quantize(
            Decimal(10) ** -decimals,
            rounding=ROUND_HALF_UP
        )
        
        return float(result)


# ==================================================================================
# FUNCIONES DE CONVENIENCIA (Wrappers para uso directo sin instanciar la clase)
# ==================================================================================

def calculate_percentage(numerator, denominator, decimals=2) -> float:
    """Wrapper para CalculationService.calculate_percentage"""
    return CalculationService.calculate_percentage(numerator, denominator,decimals)


def calculate_conversion_rate(conversions, sessions, decimals=2) -> float:
    """Wrapper para CalculationService.calculate_conversion_rate"""
    return CalculationService.calculate_conversion_rate(conversions, sessions, decimals)


def calculate_engagement_rate(engaged_sessions, total_sessions, decimals=2) -> float:
    """Wrapper para CalculationService.calculate_engagement_rate"""
    return CalculationService.calculate_engagement_rate(engaged_sessions, total_sessions, decimals)


def calculate_drop_rate(previous_count, current_count, decimals=2) -> float:
    """Wrapper para CalculationService.calculate_drop_rate"""
    return CalculationService.calculate_drop_rate(previous_count, current_count, decimals)


def convert_ga4_rate_to_percentage(ga4_rate, decimals=2) -> float:
    """Wrapper para CalculationService.convert_ga4_rate_to_percentage"""
    return CalculationService.convert_ga4_rate_to_percentage(ga4_rate, decimals)


def calculate_aov(revenue, transactions, decimals=2) -> float:
    """Wrapper para CalculationService.calculate_aov"""
    return CalculationService.calculate_aov(revenue, transactions, decimals)


def calculate_average(total, count, decimals=2) -> float:
    """Wrapper para CalculationService.calculate_average"""
    return CalculationService.calculate_average(total, count, decimals)


def calculate_ratio(numerator, denominator, decimals=2) -> float:
    """Wrapper para CalculationService.calculate_ratio"""
    return CalculationService.calculate_ratio(numerator, denominator, decimals)
