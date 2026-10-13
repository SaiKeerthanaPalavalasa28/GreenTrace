"""Structured extraction with an LLM. The model reads; it never calculates."""

import json
import logging
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pydantic import ValidationError

from app.config import Settings, get_settings
from app.pipeline.errors import ExtractionError
from app.pipeline.schema import RESPONSE_JSON_SCHEMA, LLMExtraction

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a careful data-entry clerk reading ONE utility bill (electricity or natural gas).
The bill text is given page by page, each page starting with a line "=== PAGE n ===".

Rules:
- Copy values exactly as printed. Do NOT calculate, convert units, add up, round, or infer.
- quantity: the total consumption for this billing period as printed (e.g. "Units consumed",
  "Total kWh", "Gas used"). Not a meter reading, not a charge in money, not a demand (kW/kVA) figure.
  If no total consumption is printed, set quantity to null and fill meter_readings instead.
- unit: the unit of that quantity exactly as printed (kWh, MWh, therms, m3, SCM, scf, CCF, MMBtu, GJ, units...).
- meter_readings: previous and current readings and the multiplier (MF / CT ratio) if printed; otherwise null.
- billing_period_start / billing_period_end: the consumption (service) period, as YYYY-MM-DD.
  Not the bill date or due date. If only a bill date is printed, use null.
- account_number: the consumer / account / customer number as printed.
- page_number: the page on which the consumption figure appears.
- source_snippet: copy, character for character, the line(s) from that page containing the
  consumption figure and its unit (max ~300 characters). Do not paraphrase or tidy it.
- read_type: "estimated" if the bill says the reading is estimated/assessed/provisional.
- multiple_meters_or_line_items: true if the bill covers more than one meter or more than one
  consumption line (e.g. day/night rates, several sites, import and export).
- notes: anything a reviewer should know: net metering, solar export, arrears for other periods,
  corrected or revised bill, illegible text. Otherwise null.
- confidence: your confidence (0 to 1) that quantity, unit and billing period are correct.
  Use a low value if anything is ambiguous, cut off, or illegible.
- If a field is not on the bill, use null. Never guess.
"""


class Extractor(Protocol):
    model_name: str

    def extract(self, document_text: str, correction: str | None = None) -> str:
        """Return the model's raw JSON text."""


@dataclass
class ExtractionResult:
    data: LLMExtraction
    model_used: str
    attempts: int


def parse_response(raw: str) -> LLMExtraction:
    # parse_float=Decimal keeps "1234.56" exact; json floats would not be.
    data = json.loads(raw, parse_float=Decimal)
    return LLMExtraction.model_validate(data)


def extract_structured(extractor: Extractor, document_text: str) -> ExtractionResult:
    """Call the model; on invalid output retry once with the error, then give up."""
    correction = None
    for attempt in (1, 2):
        raw = extractor.extract(document_text, correction)
        try:
            return ExtractionResult(parse_response(raw), extractor.model_name, attempt)
        except (json.JSONDecodeError, ValidationError) as e:
            log.warning("Invalid LLM output (attempt %s): %s", attempt, e)
            correction = _describe_error(e)
    raise ExtractionError(
        f"The extraction model returned invalid data twice. Last problem: {correction}"
    )


def _describe_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:5])
    return f"response was not valid JSON ({e})"


class RateLimiter:
    """Spaces calls evenly to stay under a requests-per-minute quota, across worker threads.
    None or 0 = no limit."""

    def __init__(self, per_minute: int | None):
        self.interval = 60.0 / per_minute if per_minute else 0.0
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        if slot > now:
            time.sleep(slot - now)


class LangChainExtractor:
    """LangChain chat model (a local Ollama server, so no API key) with JSON-schema-constrained
    output. Transient connection errors are retried with backoff."""

    MAX_ATTEMPTS = 4

    def __init__(self, settings: Settings | None = None, chat_model=None):
        self.settings = settings or get_settings()
        self.model_name = self.settings.llm_model
        self._chat_model = chat_model

    def _get_chat_model(self):
        if self._chat_model is None:
            from langchain_ollama import ChatOllama

            self._chat_model = ChatOllama(
                model=self.settings.llm_model,
                base_url=self.settings.llm_base_url,
                temperature=0,
                format=RESPONSE_JSON_SCHEMA,  # constrained decoding to the schema
                num_ctx=self.settings.llm_context_tokens,
                client_kwargs={"timeout": self.settings.llm_timeout_seconds},
            )
        return self._chat_model

    def extract(self, document_text: str, correction: str | None = None) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        if len(document_text) > self.settings.max_prompt_chars:
            # Never send a cut-off bill: the consumption figure could be in the missing part.
            raise ExtractionError(
                f"The bill's text is too long to extract reliably ({len(document_text):,} characters, "
                f"limit {self.settings.max_prompt_chars:,}). Upload only the bill pages."
            )
        prompt = f"Extract the billing data from this utility bill.\n\n{document_text}"
        if correction:
            prompt += (
                f"\n\nYour previous answer was rejected: {correction}\n"
                "Return JSON that matches the schema exactly."
            )
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
        model = self._get_chat_model()
        delay = 2.0
        for attempt in range(self.MAX_ATTEMPTS):
            last = attempt == self.MAX_ATTEMPTS - 1
            try:
                text = model.invoke(messages).content
            except Exception as e:
                kind = _classify(e)
                if kind == "transient" and not last:
                    log.warning("LLM server error %r, retrying in %.0fs", e, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                if kind == "model_missing":
                    raise ExtractionError(
                        f"The model {self.model_name!r} is not available on the LLM server. "
                        f"Run: ollama pull {self.model_name}") from e
                raise ExtractionError(
                    f"Could not reach the extraction model at {self.settings.llm_base_url} "
                    "(is the Ollama server running?). Reprocess the bill once it is up.") from e
            if not isinstance(text, str) or not text.strip():
                raise ExtractionError("The extraction model returned an empty response.")
            return text
        raise ExtractionError("The extraction service is unavailable. Try reprocessing later.")


def _classify(e: Exception) -> str:
    status = getattr(e, "status_code", None)
    if status == 404:
        return "model_missing"
    return "transient"


_extractor: Extractor | None = None


def get_extractor() -> Extractor:
    global _extractor
    if _extractor is None:
        _extractor = LangChainExtractor()
    return _extractor
