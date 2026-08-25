"""Servicio para la generación de informes PDF siguiendo las guías de marca de LLYC 2026.
"""
import os
import logging
import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
from io import BytesIO
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, output_dir: str = "generated_reports", templates_dir: str = "templates"):
        self.base_dir = Path(__file__).parent.parent.absolute()
        self.output_dir = self.base_dir / output_dir
        self.templates_dir = self.base_dir / templates_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self._register_fonts()
        self.jinja_env = Environment(loader=FileSystemLoader(str(self.templates_dir)))

    def _register_fonts(self):
        # Desactivado temporalmente para debug
        pass
        """
        try:
            fonts_dir = self.base_dir / "static" / "fonts"
            
            # Registrar Montserrat (Usamos Bold para títulos)
            montserrat_path = fonts_dir / "Montserrat-Bold.ttf"
            if montserrat_path.exists():
                pdfmetrics.registerFont(TTFont('Montserrat', str(montserrat_path)))
                # También registrarla como Bold explícitamente si es necesario
                pdfmetrics.registerFont(TTFont('Montserrat-Bold', str(montserrat_path)))
            
            # Registrar Open Sans (Cuerpo de texto)
            opensans_path = fonts_dir / "OpenSans-Regular.ttf"
            if opensans_path.exists():
                pdfmetrics.registerFont(TTFont('Open Sans', str(opensans_path)))
                pdfmetrics.registerFont(TTFont('OpenSans-Regular', str(opensans_path)))
                
            # Log de fuentes registradas
            logger.info(f"Fuentes registradas desde: {fonts_dir}")
        except Exception as e:
            logger.warning(f"Error registering fonts: {e}")
        """

    def _link_callback(self, uri, rel):
        """
        Resuelve rutas relativas de recursos (imágenes, fuentes, css) a rutas absolutas del sistema.
        """
        # Rutas que empiezan con static/
        if uri.startswith("static/"):
            path = self.base_dir / uri
        # Rutas relativas simples (asumiendo desde root del proyecto o static)
        elif not uri.startswith("http") and not uri.startswith("/"):
            path = self.base_dir / uri
        else:
            return uri
            
        if not os.path.isfile(str(path)):
            # Intentar buscar en static si no se encuentra en root
            alt_path = self.base_dir / "static" / uri
            if os.path.isfile(str(alt_path)):
                return str(alt_path)
            logger.warning(f"PDF Resource not found: {path}")
            return uri
            
        return str(path)

    def _render_to_pdf(self, template_name: str, context: Dict[str, Any], output_path: str) -> bool:
        try:
            template = self.jinja_env.get_template(template_name)
            res = context.get("result", {})
            logger.info(f"PDF render - response_type: {context.get('response_type')}")
            # ... (código existente de contexto y logo)
            dr = res.get("date_range") or {}
            context["start_date"] = context.get("start_date") or dr.get("start_date") or "N/A"
            context["end_date"] = context.get("end_date") or dr.get("end_date") or "N/A"
            context["timestamp"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            context["summary"] = context.get("summary") or res.get("summary") or ""
            
            # Intentar cargar logo (Preferir PNG/JPG para PDF)
            if "logo_base64" not in context:
                logo_loaded = False
                for ext in ['png', 'jpg', 'jpeg']:
                    logo_path = self.base_dir / "static" / "img" / f"llyc_logo.{ext}"
                    if logo_path.exists():
                        try:
                            with open(logo_path, "rb") as f:
                                b64 = base64.b64encode(f.read()).decode('utf-8')
                                context["logo_base64"] = f"data:image/{ext};base64,{b64}"
                                logo_loaded = True
                                break
                        except Exception as e:
                            logger.warning(f"Error loading logo {ext}: {e}")
                
                if not logo_loaded:
                    context["logo_base64"] = None

            html_content = template.render(**context)
            
            # Debug: Guardar HTML para inspección si falla
            debug_html_path = output_path.replace(".pdf", ".html")
            with open(debug_html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
                
            with open(output_path, "wb") as pdf_file:
                # Usar link_callback para resolver rutas de fuentes/imágenes
                pisa_status = pisa.CreatePDF(
                    html_content, 
                    dest=pdf_file, 
                    encoding='utf-8',
                    link_callback=self._link_callback
                )
            
            if pisa_status.err:
                logger.error(f"PISA PDF Error: {pisa_status.err}")
                return False
                
            return True
        except Exception as e:
            logger.error(f"PDF Gen Exception: {str(e)}", exc_info=True)
            return False

    def generate_audit_report(self, property_id: str, results: Dict[str, Any]) -> str:
        file_path = self.output_dir / f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        if self._render_to_pdf("report_template.html", {"property_id": property_id, "response_type": "property_audit", "result": results, "title": "Auditoría de Configuración"}, str(file_path)):
            return str(file_path)
        raise RuntimeError("Audit PDF Failed")

    def generate_traffic_ia_report(self, title: str, content: Dict[str, Any], property_id: str, summary: str = "") -> str:
        file_path = self.output_dir / f"traffic_ia_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        if self._render_to_pdf("report_template.html", {"property_id": property_id, "response_type": "traffic_ia", "result": content, "title": title, "summary": summary}, str(file_path)):
            return str(file_path)
        raise RuntimeError("Traffic IA PDF Failed")

    def generate_risk_report(self, property_id: str, results: Dict[str, Any], summary: str = "") -> str:
        file_path = self.output_dir / f"risk_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        if self._render_to_pdf("report_template.html", {"property_id": property_id, "response_type": "risk_analysis", "result": results, "title": "Riesgo y Varianza", "summary": summary}, str(file_path)):
            return str(file_path)
        raise RuntimeError("Risk PDF Failed")

    def generate_deep_dive_report(self, property_id: str, results: Dict[str, Any], summary: str = "") -> str:
        file_path = self.output_dir / f"deep_dive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        if self._render_to_pdf("report_template.html", {"property_id": property_id, "response_type": "deep_dive", "result": results, "title": "Deep Dive 360", "summary": summary}, str(file_path)):
            return str(file_path)
        raise RuntimeError("Deep Dive PDF Failed")

    def generate_ai_pattern_report(self, property_id: str, results: Dict[str, Any]) -> str:
        file_path = self.output_dir / f"ai_pattern_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        if self._render_to_pdf("report_template.html", {"property_id": property_id, "response_type": "general", "result": results, "title": "Patrones IA"}, str(file_path)):
            return str(file_path)
        raise RuntimeError("AI Pattern PDF Failed")

    def generate_general_report(self, title: str, content: Dict[str, Any], property_id: str = "N/A") -> str:
        file_path = self.output_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        if self._render_to_pdf("report_template.html", {"property_id": property_id, "response_type": "general", "result": content, "title": title}, str(file_path)):
            return str(file_path)
        raise RuntimeError("General PDF Failed")
