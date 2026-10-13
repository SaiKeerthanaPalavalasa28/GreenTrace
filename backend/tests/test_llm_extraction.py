from decimal import Decimal

import pytest

from app.config import Settings
from app.pipeline.errors import ExtractionError
from app.pipeline.llm import GeminiExtractor, extract_structured, parse_response
from app.pipeline.schema import RESPONSE_JSON_SCHEMA, LLMExtraction, MeterReadings
from tests.helpers import FakeExtractor, llm_json


def test_response_schema_matches_pydantic_model():
    props = RESPONSE_JSON_SCHEMA["properties"]
    assert set(props) == set(LLMExtraction.model_fields)
    assert set(RESPONSE_JSON_SCHEMA["required"]) == set(LLMExtraction.model_fields)
    meter = props["meter_readings"]
    assert set(meter["properties"]) == set(MeterReadings.model_fields) == set(meter["required"])
    assert props["utility_type"]["enum"] == ["electricity", "natural_gas", "unknown"]


def test_parse_keeps_decimals_exact():
    raw = FakeExtractor(llm_json(quantity="0.1")).extract("")
    assert '"quantity": 0.1' in raw  # sent as a JSON number, as a model would
    x = parse_response(raw)
    assert x.quantity == Decimal("0.1")  # float(0.1) would not be exact
    assert isinstance(x.meter_readings.current, Decimal)


def test_extra_fields_rejected():
    with pytest.raises(Exception):
        parse_response(FakeExtractor(llm_json(total_co2="5 tonnes")).extract(""))


def test_valid_first_time():
    fake = FakeExtractor(llm_json())
    r = extract_structured(fake, "doc")
    assert r.attempts == 1 and r.model_used == "fake-model"
    assert r.data.quantity == Decimal(12500)
    assert fake.calls == [("doc", None)]


def test_retries_once_with_the_error_then_succeeds():
    fake = FakeExtractor("not json at all", llm_json())
    r = extract_structured(fake, "doc")
    assert r.attempts == 2
    assert "not valid JSON" in fake.calls[1][1]


def test_schema_violation_is_described_in_retry():
    fake = FakeExtractor(llm_json(confidence=1.7), llm_json())
    extract_structured(fake, "doc")
    assert "confidence" in fake.calls[1][1]


def test_gives_up_after_second_invalid_answer():
    fake = FakeExtractor(llm_json(utility_type="water"))
    with pytest.raises(ExtractionError, match="invalid data twice.*utility_type"):
        extract_structured(fake, "doc")
    assert len(fake.calls) == 2


def test_gemini_without_key_fails_readably():
    ex = GeminiExtractor(Settings(jwt_secret="x" * 32, gemini_api_key=None, _env_file=None))
    with pytest.raises(ExtractionError, match="GEMINI_API_KEY is not configured"):
        ex.extract("doc")


# ---------------------------------------------------------------- Gemini client error handling (mocked)

class _FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return type("R", (), {"text": o})()


SLEEPS = []


def _gemini(outcomes, monkeypatch):
    import app.pipeline.llm as llm_mod

    SLEEPS.clear()
    monkeypatch.setattr(llm_mod.time, "sleep", SLEEPS.append)
    # _env_file=None: never pick up the developer's backend/.env (e.g. a request throttle).
    ex = GeminiExtractor(Settings(jwt_secret="x" * 32, gemini_api_key="test-key", gemini_model="gemini-test",
                                  gemini_requests_per_minute=None, _env_file=None))
    models = _FakeModels(outcomes)
    ex._client = type("C", (), {"models": models})()
    return ex, models


def _api_error(code):
    from google.genai import errors

    return errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})


def test_gemini_request_shape(monkeypatch):
    ex, models = _gemini(['{"ok": true}'], monkeypatch)
    assert ex.extract("=== PAGE 1 ===\nbill", correction="confidence: too high") == '{"ok": true}'
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    assert "=== PAGE 1 ===" in call["contents"] and "previous answer was rejected: confidence" in call["contents"]
    assert call["config"].response_json_schema == RESPONSE_JSON_SCHEMA
    assert call["config"].temperature == 0
    assert "Do NOT calculate" in call["config"].system_instruction


def test_gemini_retries_transient_errors(monkeypatch):
    import httpx

    ex, models = _gemini([_api_error(503), httpx.ConnectTimeout("t"), _api_error(429), '{"ok": 1}'], monkeypatch)
    assert ex.extract("doc") == '{"ok": 1}'
    assert len(models.calls) == 4


def test_gemini_gives_up_after_repeated_transient_errors(monkeypatch):
    ex, _ = _gemini([_api_error(503)] * 5, monkeypatch)
    with pytest.raises(ExtractionError, match="HTTP 503"):
        ex.extract("doc")


@pytest.mark.parametrize(("code", "message"), [(401, "refused the request .HTTP 401.: x"), (403, "refused the request .HTTP 403.: x"),
                                                (404, "'gemini-test' was not found"), (400, "HTTP 400")])
def test_gemini_permanent_errors_are_readable(monkeypatch, code, message):
    ex, models = _gemini([_api_error(code)], monkeypatch)
    with pytest.raises(ExtractionError, match=message):
        ex.extract("doc")
    assert len(models.calls) == 1


def test_gemini_empty_response(monkeypatch):
    ex, _ = _gemini([""], monkeypatch)
    with pytest.raises(ExtractionError, match="empty response"):
        ex.extract("doc")


def test_gemini_refuses_to_send_truncated_bill(monkeypatch):
    ex, models = _gemini(["{}"], monkeypatch)
    ex.settings.max_prompt_chars = 100
    with pytest.raises(ExtractionError, match="too long"):
        ex.extract("x" * 101)
    assert models.calls == []


def _rate_limited(retry_delay="18s"):
    from google.genai import errors

    return errors.APIError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}]}})


def test_rate_limit_waits_as_long_as_the_api_asks(monkeypatch):
    ex, models = _gemini([_rate_limited("18s"), _rate_limited("59.5s"), '{"ok": 1}'], monkeypatch)
    assert ex.extract("doc") == '{"ok": 1}'
    assert SLEEPS == [19.0, 60.0]  # requested delay + 1 s, capped at 60 s


def test_daily_quota_fails_immediately_with_reset_time(monkeypatch):
    ex, models = _gemini([_rate_limited("38735s")], monkeypatch)
    with pytest.raises(ExtractionError, match="resets in about 10.8 h"):
        ex.extract("doc")
    assert len(models.calls) == 1 and SLEEPS == []


def test_rate_limit_exhausted_gives_actionable_message(monkeypatch):
    ex, _ = _gemini([_rate_limited()] * 5, monkeypatch)
    with pytest.raises(ExtractionError, match="quota is exhausted.*GEMINI_REQUESTS_PER_MINUTE"):
        ex.extract("doc")


def test_rate_limiter_spaces_requests(monkeypatch):
    import app.pipeline.llm as llm_mod

    clock = [100.0]
    monkeypatch.setattr(llm_mod.time, "monotonic", lambda: clock[0])
    slept = []
    monkeypatch.setattr(llm_mod.time, "sleep", slept.append)
    limiter = llm_mod.RateLimiter(5)  # one request every 12 s
    for _ in range(3):
        limiter.wait()
    assert slept == [12.0, 24.0]
    assert llm_mod.RateLimiter(None).interval == 0
