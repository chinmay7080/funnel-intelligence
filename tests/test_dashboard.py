from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from funnel.copilot import EXAMPLES

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_dashboard_reports_render(monkeypatch):
    monkeypatch.setenv("FUNNEL_MODE", "demo")
    app = AppTest.from_file(APP, default_timeout=20).run()
    for page in ("Overview", "Segments & cohorts", "Products", "Anomalies"):
        app.radio[0].set_value(page).run()
        assert not app.error
        assert not app.exception
        assert app.dataframe


@pytest.mark.parametrize("example", EXAMPLES)
def test_copilot_examples_render(example, monkeypatch):
    monkeypatch.setenv("FUNNEL_MODE", "demo")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_PROVIDER", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    app = AppTest.from_file(APP, default_timeout=20).run()
    app.radio[0].set_value("Analytics Copilot").run()
    app.selectbox(key="copilot-example").set_value(example).run()
    app.button[0].click().run()
    assert not app.error
    assert not app.warning
    assert not app.exception
    assert app.get("plotly_chart")
    assert any(element.value.startswith("E1") for element in app.text)
