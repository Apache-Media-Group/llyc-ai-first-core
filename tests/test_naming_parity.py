"""
test_naming_parity.py — Garantía de convergencia DEC_096.

El auditor v4.0 NO reimplementa reglas: comparte motor (engine.py) y gramática
(naming-grammar.yaml) con el generador. Este test falla si el grammar del agente
diverge del original del generador, o si el contrato de audit.py cambia de forma.
La fuente de verdad del grammar es el generador; el agente lleva una copia que
debe ser idéntica byte a byte.
"""
import hashlib
import pathlib
import pytest

from naming_engine.audit import Auditor

REPO = pathlib.Path(__file__).resolve().parent.parent
GRAMMAR = REPO / "naming_engine" / "grammar" / "naming-grammar.yaml"
FIXTURE = REPO / "tests" / "fixtures" / "compiled_naming.json"

# Hash del grammar validado (generador feature/iteration-2). Si el grammar del
# agente cambia sin re-sincronizar con el generador, este test salta.
EXPECTED_GRAMMAR_SHA256 = "dc535228f668fb6ea8bafac4c85563e821613469556a87213645276113c5a2fc"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_grammar_present():
    assert GRAMMAR.exists(), "falta naming-grammar.yaml en el paquete del agente"


@pytest.mark.skipif(EXPECTED_GRAMMAR_SHA256 is None, reason="hash no fijado aún")
def test_grammar_parity():
    assert _sha(GRAMMAR) == EXPECTED_GRAMMAR_SHA256, (
        "el grammar del agente diverge del validado en el generador — "
        "re-sincronizar (DEC_096)"
    )


def test_audit_contract_shape():
    """audit_naming/audit_utm devuelven lista de tuplas (error_type, detalle)."""
    a = Auditor(compiled_path=str(FIXTURE))
    nm = a.audit_naming("vv", "campaign", "S - Likes - Facebook")
    assert isinstance(nm, list) and all(isinstance(t, tuple) and len(t) == 2 for t in nm)
    ut = a.audit_utm("vv", "meta", "https://www.vidal-vidal.com/x",
                     "utm_source=meta&utm_medium=paid_social", "C", "G", "A")
    assert isinstance(ut, list) and all(isinstance(t, tuple) and len(t) == 2 for t in ut)


def test_na_cases_empty():
    """Boosting (sin destino) y destino no-web → UTM N/A = lista vacía."""
    a = Auditor(compiled_path=str(FIXTURE))
    assert a.audit_utm("vv", "meta", None, None, "C", "G", "A") == []
    assert a.audit_utm("vv", "meta", "https://www.facebook.com/123", None, "C", "G", "A") == []


def test_correct_utm_no_false_positive():
    """Forma macro correcta no genera error."""
    a = Auditor(compiled_path=str(FIXTURE))
    tags = ("utm_source=meta&utm_medium=paid_social&utm_id={{campaign.id}}"
            "&utm_source_platform=meta&utm_content={{adset.name}}_{{ad.name}}")
    assert a.audit_utm("vv", "meta", "https://www.vidal-vidal.com/x", tags, "C", "G", "A") == []
