from decimal import Decimal

import pytest

from app.config import Settings
from app.pipeline.errors import ExtractionError
from app.pipeline.llm import LangChainExtractor, extract_structured, parse_response
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


# ---------------------------------------------------------------- LangChain extractor (mocked chat model)

class _FakeChat:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return type("R", (), {"content": o})()


class _StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


SLEEPS = []


def _extractor(outcomes, monkeypatch):
    import app.pipeline.llm as llm_mod

    SLEEPS.clear()
    monkeypatch.setattr(llm_mod.time, "sleep", SLEEPS.append)
    chat = _FakeChat(outcomes)
    ex = LangChainExtractor(Settings(jwt_secret="x" * 32, llm_model="test-model"), chat_model=chat)
    return ex, chat


def test_request_shape(monkeypatch):
    ex, chat = _extractor(['{"ok": true}'], monkeypatch)
    assert ex.extract("=== PAGE 1 ===\nbill", correction="confidence: too high") == '{"ok": true}'
    system, human = chat.calls[0]
    assert "Do NOT calculate" in system.content
    assert "=== PAGE 1 ===" in human.content and "previous answer was rejected: confidence" in human.content


def test_chat_model_is_configured_without_any_key():
    from langchain_ollama import ChatOllama

    ex = LangChainExtractor(Settings(jwt_secret="x" * 32, llm_model="test-model", llm_base_url="http://llm:11434"))
    model = ex._get_chat_model()
    assert isinstance(model, ChatOllama)
    assert model.model == "test-model" and model.temperature == 0 and model.format == RESPONSE_JSON_SCHEMA


def test_retries_transient_errors(monkeypatch):
    ex, chat = _extractor([ConnectionError("down"), _StatusError(503), '{"ok": 1}'], monkeypatch)
    assert ex.extract("doc") == '{"ok": 1}'
    assert len(chat.calls) == 3 and SLEEPS == [2.0, 4.0]


def test_gives_up_when_server_unreachable(monkeypatch):
    ex, chat = _extractor([ConnectionError("down")] * 4, monkeypatch)
    with pytest.raises(ExtractionError, match="Could not reach the extraction model"):
        ex.extract("doc")
    assert len(chat.calls) == 4


def test_missing_model_is_actionable(monkeypatch):
    ex, chat = _extractor([_StatusError(404)], monkeypatch)
    with pytest.raises(ExtractionError, match="ollama pull test-model"):
        ex.extract("doc")
    assert len(chat.calls) == 1


def test_empty_response(monkeypatch):
    ex, _ = _extractor([""], monkeypatch)
    with pytest.raises(ExtractionError, match="empty response"):
        ex.extract("doc")


def test_refuses_to_send_truncated_bill(monkeypatch):
    ex, chat = _extractor(["{}"], monkeypatch)
    ex.settings.max_prompt_chars = 100
    with pytest.raises(ExtractionError, match="too long"):
        ex.extract("x" * 101)
    assert chat.calls == []
