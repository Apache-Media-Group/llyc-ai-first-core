import os
import logging
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ReportGeneratorService:
    """Servicio para generar reportes HTML basados en plantillas."""

    def __init__(self):
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        self.env = Environment(loader=FileSystemLoader(template_dir))
        
        # Cargar logo si existe
        self.logo_base64 = ""
        # Intenta cargar desde resources o directorio actual
        possible_paths = [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "logo_base64.txt"),
            os.path.join(os.getcwd(), "logo_base64.txt"),
            "logo_base64.txt"
        ]
        for logo_path in possible_paths:
            if os.path.exists(logo_path):
                with open(logo_path, "r") as f:
                    self.logo_base64 = f.read().strip()
                break

    def generate_html_report(self, event_data: Dict[str, Any]) -> str:
        """Genera un reporte HTML a partir de los datos de un evento del historial."""
        try:
            template = self.env.get_template("report_template.html")
            
            # Preparar datos para el template
            render_data = {
                "property_id": event_data.get("property_id"),
                "response_type": event_data.get("response_type"),
                "result": event_data.get("result"),
                "timestamp": event_data.get("timestamp"),
                "start_date": event_data.get("result", {}).get("date_range", {}).get("start_date", "N/A"),
                "end_date": event_data.get("result", {}).get("date_range", {}).get("end_date", "N/A"),
                "logo_base64": self.logo_base64
            }
            
            # Ajustar fechas si no están en la estructura estándar
            if render_data["start_date"] == "N/A" and "start_date" in event_data.get("result", {}):
                 render_data["start_date"] = event_data["result"]["start_date"]
                 render_data["end_date"] = event_data["result"]["end_date"]

            return template.render(**render_data)
        except Exception as e:
            logger.error(f"Error generating HTML report: {e}")
            return f"<h1>Error al generar reporte</h1><p>{str(e)}</p>"


# Crear instancia singleton
report_generator_service = ReportGeneratorService()
