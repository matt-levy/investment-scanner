import asyncio
import json
from datetime import date
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.main import app
from app.research_llm import ReportBody, validate_grounding
from app.research_sources import clean_html, sec_filings, SourceError

QUOTE = "The company reported a material change in operations."
def statement(text="The filing could point to operational changes."):
    return {"text": text, "citations": [{"source_id": 1, "quote": QUOTE}]}

def body():
    return {"market_view": [statement()], "catalysts": [], "bullish": {"outcome": statement("Operations could improve."), "evidence_against": []},
        "neutral": None, "bearish": None, "reasons_correctly_priced": [], "open_questions": ["What further evidence is needed?"]}

def test_report_requires_real_quotes_and_no_probability():
    report = ReportBody.model_validate(body())
    validate_grounding(report, {1: QUOTE + " More context."})
    with pytest.raises(ValueError, match="citation"):
        validate_grounding(report, {1: "A different source."})
    data = body()
    data["bullish"]["outcome"]["text"] = "There is a 70% chance of improvement."
    with pytest.raises(ValidationError):
        ReportBody.model_validate(data)
    data = body()
    data["market_view"][0]["text"] = "The chance is 70 percent."
    with pytest.raises(ValueError, match="Numerical"):
        validate_grounding(ReportBody.model_validate(data), {1: QUOTE})

def test_sec_requires_identifying_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SourceError, match="SEC_USER_AGENT"):
        asyncio.run(sec_filings("AAPL"))

def test_html_extraction_and_truncation():
    text, coverage = clean_html("<p>hello</p><script>ignore me</script><p>world</p>", 8)
    assert text == "hello wo"
    assert coverage == "truncated_excerpt"

def test_refresh_and_report_validate_ticker_and_evidence(monkeypatch):
    async def sec(ticker):
        return [{"provider":"sec", "external_id":"accession", "kind":"10-K", "title":"Example filing", "url":"https://www.sec.gov/example", "published_on":date(2026,1,1), "content":QUOTE, "coverage":"full_text"}]
    async def news(ticker):
        raise SourceError("News unavailable")
    class FakeLLM:
        async def generate(self, documents):
            data = body()
            data["market_view"][0]["citations"][0]["source_id"] = documents[0]["id"]
            data["bullish"]["outcome"]["citations"][0]["source_id"] = documents[0]["id"]
            report = ReportBody.model_validate(data)
            validate_grounding(report, {d["id"]:d["content"] for d in documents})
            return report, "test", "mock"
    monkeypatch.setattr("app.research_api.sec_filings", sec)
    monkeypatch.setattr("app.research_api.alpaca_news", news)
    monkeypatch.setattr("app.research_api.OpenAICompatibleProvider", FakeLLM)
    with TestClient(app) as client:
        refresh = client.post("/research/AAPL/sources/refresh?force=true")
        assert refresh.status_code == 200
        assert refresh.json()["errors"]["alpaca_news"] == "News unavailable"
        assert client.post("/research/AAPL/sources/refresh?force=true").json()["new_sources"] == 0
        sources = client.get("/research/AAPL/sources").json()
        source = next(item for item in sources if item["title"] == "Example filing")
        assert client.post("/research/MSFT/reports", json={"source_ids":[source["id"]]}).status_code == 422
        generated = client.post("/research/AAPL/reports", json={"source_ids":[source["id"]]})
        assert generated.status_code == 201
        assert generated.json()["source_ids"] == [source["id"]]
        assert client.get("/research/AAPL/reports").json()[0]["report"]["bullish"]["outcome"]["citations"][0]["quote"] == QUOTE
def test_llm_invalid_quote_is_rejected(monkeypatch):
    from app.research_llm import OpenAICompatibleProvider, ProviderError
    import httpx
    async def handler(request):
        return httpx.Response(200, json={"choices":[{"message":{"content":json.dumps(body())}}]})
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr("app.research_llm.httpx.AsyncClient", lambda **kwargs: real(transport=transport))
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "test")
    with pytest.raises(ProviderError, match="no report was saved"):
        asyncio.run(OpenAICompatibleProvider().generate([{"id":1, "content":"An unrelated source passage."}]))
