"""Sistema de Aprendizaje Crítico (CLS) - Critical Learning System.

Módulo que implementa el aprendizaje autónomo y la validación inteligente de feedback.
El sistema evalúa cada sugerencia de mejora contra la documentación de GA4 antes de aplicarla.
"""

from .feedback_evaluator import FeedbackEvaluator
from .knowledge_base import KnowledgeBaseService, LearnedRule
from .notification_mgr import NotificationManager

__all__ = [
    "FeedbackEvaluator",
    "KnowledgeBaseService",
    "LearnedRule",
    "NotificationManager",
]

