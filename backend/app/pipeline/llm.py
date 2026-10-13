"""Structured extraction with an LLM. The model reads; it never calculates."""

import json
import logging
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx
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


def _retry_after(e) -> float | None:
    """Seconds from a google.rpc.RetryInfo detail, e.g. {'retryDelay': '18s'}."""
    details = (getattr(e, "details", None) or {}).get("error", {}).get("details", [])
    for d in details if isinstance(details, list) else []:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("RetryInfo"):
            try:
                return float(str(d.get("retryDelay", "")).rstrip("s"))
            except ValueError:
                return None
    return None


class GeminiExtractor:
    """Gemini with JSON-schema-constrained output. Transient API errors are retried with backoff."""

    TRANSIENT_STATUS = {429, 500, 502, 503, 504}
    MAX_ATTEMPTS = 5
    MAX_RETRY_WAIT = 60.0

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.model_name = self.settings.gemini_model
        self._client = None
        self._limiter = RateLimiter(self.settings.gemini_requests_per_minute)

    def _get_client(self):
        if not self.settings.gemini_api_key:
            raise ExtractionError("GEMINI_API_KEY is not configured on the server. Set it, then reprocess the bill.")
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self.settings.gemini_api_key,
                http_options=types.HttpOptions(timeout=self.settings.gemini_timeout_seconds * 1000),
            )
        return self._client

    def extract(self, document_text: str, correction: str | None = None) -> str:
        from google.genai import errors, types

        client = self._get_client()
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
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=RESPONSE_JSON_SCHEMA,
            temperature=0,
        )
        delay = 2.0
        for attempt in range(self.MAX_ATTEMPTS):
            last = attempt == self.MAX_ATTEMPTS - 1
            try:
                self._limiter.wait()
                response = client.models.generate_content(model=self.model_name, contents=prompt, config=config)
                if not response.text:
                    raise ExtractionError("The extraction model returned an empty response (possibly blocked).")
                return response.text
            except errors.APIError as e:
                retry_after = _retry_after(e) if e.code == 429 else None
                if retry_after is not None and retry_after > self.MAX_RETRY_WAIT:
                    # A daily quota: waiting a minute won't help, so fail now and say when it resets.
                    raise ExtractionError(
                        f"The Gemini API quota is used up; it resets in about {retry_after / 3600:.1f} h. "
                        "Reprocess the bill after that, or upgrade the API plan (free-tier keys allow very few "
                        "requests per day).") from e
                if e.code in self.TRANSIENT_STATUS and not last:
                    # Rate limits say how long to wait; honour that instead of guessing.
                    wait = retry_after
                    wait = min(wait + 1, self.MAX_RETRY_WAIT) if wait is not None else delay
                    log.warning("Gemini %s, retrying in %.0fs", e.code, wait)
                    time.sleep(wait)
                    delay *= 2
                    continue
                if e.code == 429:
                    raise ExtractionError(
                        "The Gemini API quota is exhausted (HTTP 429). Lower GEMINI_REQUESTS_PER_MINUTE or upgrade "
                        "the API plan, then reprocess the bill.") from e
                if e.code in (401, 403):
                    # 403 also covers project-level blocks ("Your project has been denied access"),
                    # which no key change on our side fixes, so pass Google's message through.
                    raise ExtractionError(f"The Gemini API refused the request (HTTP {e.code}): "
                                          f"{(e.message or 'no detail')[:200]} Check GEMINI_API_KEY and the "
                                          "Google AI Studio / Cloud project it belongs to.") from e
                if e.code == 404:
                    raise ExtractionError(f"Gemini model {self.model_name!r} was not found (check GEMINI_MODEL).") from e
                raise ExtractionError(f"The extraction service failed (HTTP {e.code}). Try reprocessing later.") from e
            except httpx.HTTPError as e:  # network errors, timeouts
                if not last:
                    log.warning("Gemini network error %r, retrying in %.0fs", e, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ExtractionError("Could not reach the extraction service (network error or timeout).") from e
        raise ExtractionError("The extraction service is unavailable. Try reprocessing later.")


_extractor: Extractor | None = None


def get_extractor() -> Extractor:
    global _extractor
    if _extractor is None:
        _extractor = GeminiExtractor()
    return _extractor
