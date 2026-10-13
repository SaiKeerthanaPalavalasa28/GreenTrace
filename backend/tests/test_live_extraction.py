"""LIVE extraction accuracy against the real Ollama model. Opt-in (costs API calls):

    ollama serve   (and: ollama pull llama3.1:8b)
    .venv\\Scripts\\python -m pytest -m live -v

Each text-layer sample bill goes through the real text extraction + LLM + validation, and
the extracted fields are compared with the values printed on the bill (samples/manifest.json).
"""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.calc.units import canonical_unit
from app.config import Settings
from app.pipeline.llm import LangChainExtractor, extract_structured
from app.pipeline.text import extract_text

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
MANIFEST = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
TEXT_BILLS = [b for b in MANIFEST["bills"] if not b["requires_ocr"]]

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def extractor():
    ex = LangChainExtractor(Settings(jwt_secret="x" * 32))
    try:
        httpx.get(ex.settings.llm_base_url, timeout=3)
    except httpx.HTTPError:
        pytest.skip(f"no Ollama server at {ex.settings.llm_base_url}")
    return ex


@pytest.mark.parametrize("bill", TEXT_BILLS, ids=[Path(b["file"]).stem for b in TEXT_BILLS])
def test_live_extraction_matches_bill(extractor, bill):
    pdf_text = extract_text((SAMPLES / bill["file"]).read_bytes())
    got = extract_structured(extractor, pdf_text.as_prompt()).data
    want = bill["expected_extraction"]

    assert got.utility_type == want["utility_type"]
    assert got.account_number and got.account_number.replace(" ", "") == want["account_number"].replace(" ", "")
    assert str(got.billing_period_start) == want["billing_period_start"]
    assert str(got.billing_period_end) == want["billing_period_end"]
    assert canonical_unit(got.unit) == canonical_unit(want["unit"])
    if want["quantity"] is None:
        # Only meter readings printed: the model must NOT compute a total itself.
        assert got.quantity is None
        mr = want["meter_readings"]
        assert (got.meter_readings.previous, got.meter_readings.current, got.meter_readings.multiplier) == \
            (Decimal(mr["previous"]), Decimal(mr["current"]), Decimal(mr["multiplier"]))
    else:
        assert got.quantity == Decimal(want["quantity"])
    assert got.page_number == want["page_number"]
