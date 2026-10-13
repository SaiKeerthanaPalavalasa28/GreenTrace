"""LIVE extraction accuracy against the real Gemini API. Opt-in (costs API calls):

    set GEMINI_API_KEY=...   (or put it in backend/.env)
    .venv\\Scripts\\python -m pytest -m live -v

Each text-layer sample bill goes through the real text extraction + Gemini + validation, and
the extracted fields are compared with the values printed on the bill (samples/manifest.json).
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.calc.units import canonical_unit
from app.config import Settings
from app.pipeline.llm import GeminiExtractor, extract_structured
from app.pipeline.text import extract_text

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
MANIFEST = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
TEXT_BILLS = [b for b in MANIFEST["bills"] if not b["requires_ocr"]]

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def extractor():
    # Real settings from the environment / backend/.env, not the test overrides.
    import os

    key = os.environ.get("GEMINI_API_KEY") or Settings(jwt_secret="x" * 32, _env_file=Path(__file__).parents[1] / ".env").gemini_api_key
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    return GeminiExtractor(Settings(jwt_secret="x" * 32, gemini_api_key=key,
                                    _env_file=Path(__file__).parents[1] / ".env"))


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
