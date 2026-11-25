from datetime import date
from unittest.mock import Mock

import duckdb
import pytest
import sqlglot
from sqlglot import exp

from funnel.analysis import total
from funnel.copilot import AnalysisRequest, EXAMPLES, demo_request, investigate
from funnel.warehouse import DIMENSIONS, Scope, Warehouse


@pytest.fixture(scope="module")
def reporting():
    warehouse = Warehouse()
    available = set(warehouse.run(warehouse.compile("coverage"))["report_date"].to_list())
    rows = warehouse.run(warehouse.compile("options"))
    options = {field: rows[field].unique().to_list() for field in DIMENSIONS}
    return warehouse, available, options, Scope(date(2021, 1, 18), date(2021, 1, 31))


@pytest.mark.parametrize(("question", "intent", "breakdown"), [
    (EXAMPLES[0], "diagnosis", "channel"),
    (EXAMPLES[1], "funnel", "channel"),
    (EXAMPLES[2], "segments", "channel"),
    (EXAMPLES[3], "products", "channel"),
    ("Show the checkout funnel", "funnel", "channel"),
    ("Compare the mobile vs desktop conversion rate", "segments", "device"),
    ("Compare new and returning visitors", "segments", "visitor"),
    ("Which channels have highest revenue?", "clarify", "channel"),
    ("Compare conversion by country", "clarify", "channel"),
    ("Show the purchase funnel today", "clarify", "channel"),
    ("What is our refund rate?", "clarify", "channel"),
    ("Give me the funnel for 2021-01-30", "clarify", "channel"),
    ("Show me a funnel for last month", "clarify", "channel"),
    ("Why did conversion increase last week?", "diagnosis", "channel"),
    ("Show the mobile funnel for 2021-01-18 to 2021-01-24", "funnel", "channel"),
])
def test_demo_request(reporting, question, intent, breakdown):
    _, _, options, _ = reporting
    request = demo_request(question, options)
    assert request.intent == intent
    assert request.breakdown == breakdown


def test_report_matches_dashboard_and_decomposition(reporting):
    warehouse, available, options, selection = reporting
    request = demo_request(EXAMPLES[0], options)
    result = investigate(request, selection, available, options, warehouse.compile, warehouse.run)
    scope = Scope(date(2021, 1, 25), date(2021, 1, 31), device="mobile")
    assert scope == result["scope"]
    assert result["counts"] == total(warehouse.run(warehouse.compile("daily", scope)))
    assert result["counts"]["purchasing_sessions"] == 80
    assert result["old"]["purchasing_sessions"] == 140
    assert result["change"] == pytest.approx(-6.7107, abs=0.001)
    assert sum(row["Total (pp)"] for row in result["comparison"]) == pytest.approx(result["change"])
    assert result["largest_step_loss"][0] == "Purchase"


@pytest.mark.parametrize("request_params", [
    {"intent": "clarify"},
    {"intent": "funnel", "device": "not a device"},
    {"intent": "funnel", "time_range": "custom", "start": "2021-01-02", "end": "2021-01-10"},
    {"intent": "diagnosis", "time_range": "custom", "start": "2021-01-04", "end": "2021-01-10"},
])
def test_rejected_intent_does_not_query(reporting, request_params):
    warehouse, available, options, selection = reporting
    execute = Mock()
    with pytest.raises(ValueError):
        investigate(AnalysisRequest(**request_params), selection, available, options, warehouse.compile, execute)
    execute.assert_not_called()


def test_premise_can_be_wrong_and_empty_segments_are_safe(reporting):
    warehouse, available, options, _ = reporting
    request = AnalysisRequest(intent="diagnosis", device="mobile")
    for start in (date(2021, 1, 11), date(2021, 1, 18)):
        selection = Scope(start, start.replace(day=start.day + 6))
        result = investigate(request, selection, available, options, warehouse.compile, warehouse.run)
        if not result["decline"]:
            break
    assert result["change"] >= 0
    empty = Scope(date(2021, 1, 25), date(2021, 1, 31), device="missing")
    result = investigate(AnalysisRequest(intent="diagnosis"), empty, available, options, warehouse.compile, warehouse.run)
    assert "change" not in result
    assert "no eligible sessions" in result["evidence"][-1]["description"]


def test_fixture_events_span_midnight_and_require_same_product(reporting):
    warehouse, *_ = reporting
    with duckdb.connect(str(warehouse.db_path), read_only=True) as conn:
        row = conn.execute("""
            select session_key, session_date, ordered_purchase, has_timestamp_ties
            from analytics.fct_sessions where user_key = 'fixture-midnight'
        """).fetchone()
        assert row[1:] == (date(2021, 1, 4), True, True)
        assert conn.execute("""
            select item_id, added_after_view, purchased_after_view
            from analytics.fct_session_items where session_key = ?
        """, [row[0]]).fetchall() == [("P01", True, False)]


def test_bigquery_templates_only_select_approved_relations(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "ga4-offline-validation")
    warehouse = Warehouse("bigquery")
    selection = Scope(date(2021, 1, 18), date(2021, 1, 31), device="mobile")
    warehouse_tables = set(["mart_data_quality", "mart_daily_funnel", "mart_daily_products",
                            "mart_weekly_cohorts", "mart_session_anomalies", "mart_journey_events"])
    for report in ["coverage", "options", "daily", "segments", "products", "cohorts", "anomalies", "journey", "quality"]:
        query = warehouse.compile(report, selection, dimension="device", session_key="demo:1")
        statements = sqlglot.parse(query.sql, read="bigquery")
        assert len(statements) == 1 and isinstance(statements[0], exp.Select)
        table = statements[0].find(exp.Table)
        assert table.name in warehouse_tables
        assert "demo:1" not in query.sql


def test_ollama_uses_structured_schema_and_validates_output(monkeypatch):
    from funnel.copilot import Ollama

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.post.return_value.json.return_value = {
        "message": {"content": '{"intent":"diagnosis","time_range":"last_week","device":"mobile"}'}
    }
    monkeypatch.setattr("funnel.copilot.httpx.Client", Mock(return_value=client))
    request = Ollama().structured("question", AnalysisRequest, "system instruction")
    assert request.intent == "diagnosis"
    assert request.device == "mobile"
    url = client.post.call_args.args[0]
    payload = client.post.call_args.kwargs["json"]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert payload["format"] == AnalysisRequest.model_json_schema()
    assert payload["stream"] is False


def test_step_hypotheses_reference_computed_evidence():
    from funnel.copilot import suggested_checks

    result = {"decline": True, "largest_step_loss": ("Add to cart", -5.5), "step_loss_evidence": "E7"}
    hypotheses = suggested_checks(result)
    assert len(hypotheses) == 1
    assert hypotheses[0].evidence_id == "E7"
    assert "cart" in hypotheses[0].how_to_check.lower()
    assert not suggested_checks({**result, "decline": False})


def test_snapshot_uses_same_report_contract(reporting, monkeypatch):
    demo, _, _, selection = reporting
    monkeypatch.setenv("FUNNEL_SNAPSHOT_PATH", str(demo.db_path))
    snapshot = Warehouse("snapshot")
    assert total(snapshot.run(snapshot.compile("daily", selection))) == total(
        demo.run(demo.compile("daily", selection))
    )
