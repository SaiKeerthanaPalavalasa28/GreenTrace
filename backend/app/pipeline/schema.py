"""The contract between the LLM and the rest of the system. The LLM must return exactly this
shape; anything else is rejected (and retried once)."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MeterReadings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous: Decimal | None
    current: Decimal | None
    multiplier: Decimal | None


class LLMExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utility_type: Literal["electricity", "natural_gas", "unknown"]
    provider_name: str | None = Field(max_length=200)
    account_number: str | None = Field(max_length=100)
    billing_period_start: date | None
    billing_period_end: date | None
    quantity: Decimal | None
    unit: str | None = Field(max_length=40)
    meter_readings: MeterReadings
    read_type: Literal["actual", "estimated", "unknown"]
    multiple_meters_or_line_items: bool
    page_number: int = Field(ge=1)
    source_snippet: str = Field(max_length=600)
    confidence: float = Field(ge=0, le=1)
    notes: str | None = Field(max_length=2000)


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_STR = {"type": "string"}
_NUM = {"type": "number"}
_DATE = {"type": "string", "description": "ISO date YYYY-MM-DD"}

# JSON Schema sent to the model (structured output). Kept by hand, flat and $ref-free, because
# model providers support only a subset of JSON Schema. tests/test_llm_schema.py checks that it
# stays in sync with LLMExtraction.
RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "utility_type": {"type": "string", "enum": ["electricity", "natural_gas", "unknown"]},
        "provider_name": _nullable(_STR),
        "account_number": _nullable(_STR),
        "billing_period_start": _nullable(_DATE),
        "billing_period_end": _nullable(_DATE),
        "quantity": _nullable({**_NUM, "description": "Total consumption exactly as printed; null if not printed"}),
        "unit": _nullable({**_STR, "description": "Unit exactly as printed, e.g. kWh, SCM, therms"}),
        "meter_readings": {
            "type": "object",
            "properties": {
                "previous": _nullable(_NUM),
                "current": _nullable(_NUM),
                "multiplier": _nullable(_NUM),
            },
            "required": ["previous", "current", "multiplier"],
        },
        "read_type": {"type": "string", "enum": ["actual", "estimated", "unknown"]},
        "multiple_meters_or_line_items": {"type": "boolean"},
        "page_number": {"type": "integer", "minimum": 1},
        "source_snippet": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "notes": _nullable(_STR),
    },
    "required": [
        "utility_type", "provider_name", "account_number", "billing_period_start",
        "billing_period_end", "quantity", "unit", "meter_readings", "read_type",
        "multiple_meters_or_line_items", "page_number", "source_snippet", "confidence", "notes",
    ],
}
