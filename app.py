"""Streamlit entry point for the funnel intelligence dashboard."""

import logging
import os
from dataclasses import replace
from datetime import date, timedelta

import plotly.graph_objects as go
import polars as pl
import streamlit as st

from funnel.analysis import (
    add_conversion, daily_alerts, funnel_rows, has_coverage, percent, previous,
    rate, top_product_opportunities, total,
)
from funnel.copilot import EXAMPLES, configured_provider, create_provider, demo_request, investigate, suggested_checks
from funnel.warehouse import DIMENSIONS, DIMENSION_LABELS, Scope, Warehouse

st.set_page_config(page_title="Funnel Intelligence", layout="wide", page_icon="📊")
logger = logging.getLogger(__name__)

GREEN = "#007b67"
BLUE = "#4565a5"
GRAYS = ["#cde7e0", "#9dd2c5", "#68b7a4", "#268f7c", GREEN]
PERCENT = st.column_config.NumberColumn(format="percent")


@st.cache_data(ttl=600, show_spinner=False)
def query_data(mode, config, sql, parameters):
    from funnel.warehouse import Query

    return Warehouse(mode).run(Query(sql, parameters))


def execute(query):
    config = (warehouse.project, warehouse.dataset, str(warehouse.db_path),
              warehouse.db_path.stat().st_mtime_ns if warehouse.mode != "bigquery" else None)
    return query_data(warehouse.mode, config, query.sql, query.parameters)


def report(name, scope=None, dimension=None, session_key=None):
    return execute(warehouse.compile(name, scope, dimension, session_key))


def chart(figure, height=330):
    figure.update_layout(
        height=height, margin=dict(l=20, r=25, t=18, b=25),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#24352f"), hoverlabel=dict(namelength=-1),
        legend=dict(orientation="h", y=1.09),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def trend(daily):
    values = add_conversion(daily)
    fig = go.Figure(go.Scatter(
        x=values["session_date"].to_list(), y=values["Conversion"].to_list(), mode="lines+markers",
        line=dict(color=GREEN, width=3), marker=dict(size=5), customdata=values["sessions"].to_list(),
        hovertemplate="%{x|%b %d}<br>Conversion %{y:.1%}<br>%{customdata:,} sessions<extra></extra>",
    ))
    fig.update_yaxes(title="Purchase conversion", tickformat=".1%", rangemode="tozero", gridcolor="#dfe8e4")
    chart(fig)


def funnel_chart(counts, prior=None):
    current = funnel_rows(counts)
    figure = go.Figure(go.Bar(
        name="Selected", x=[row["Sessions"] for row in current], y=[row["Stage"] for row in current],
        orientation="h", marker_color=GRAYS if prior is None else GREEN,
        text=[f'{row["Sessions"]:,}' for row in current], textposition="auto",
        hovertemplate="%{y}<br>%{x:,} sessions<extra></extra>",
    ))
    if prior is not None:
        previous_rows = funnel_rows(prior)
        figure.add_bar(name="Prior", x=[row["Sessions"] for row in previous_rows],
                       y=[row["Stage"] for row in previous_rows], orientation="h", marker_color=BLUE,
                       hovertemplate="%{y}<br>%{x:,} sessions<extra></extra>")
    figure.update_yaxes(autorange="reversed")
    figure.update_xaxes(title="Sessions", gridcolor="#dfe8e4")
    chart(figure)


def segment_view(data):
    if data.is_empty():
        st.info("No sessions match these filters.")
        return
    ranked = data.sort("Conversion", descending=True, nulls_last=True)
    colors = [GREEN if value >= 50 else "#b1c2bb" for value in ranked["sessions"]]
    figure = go.Figure(go.Bar(
        x=ranked["Conversion"].to_list(), y=ranked["segment"].to_list(), orientation="h", marker_color=colors,
        customdata=ranked["sessions"].to_list(),
        hovertemplate="%{y}<br>%{x:.1%} conversion<br>%{customdata:,} sessions<extra></extra>",
    ))
    figure.update_yaxes(autorange="reversed")
    figure.update_xaxes(tickformat=".1%", gridcolor="#dfe8e4")
    chart(figure, max(240, 33 * len(ranked) + 85))
    st.dataframe(ranked.select("segment", "sessions", "purchasing_sessions", "Conversion"), hide_index=True,
                 column_config={"Conversion": PERCENT, "purchasing_sessions": "Purchasing sessions",
                                "segment": "Segment", "sessions": "Sessions"})
    st.caption("Muted bars indicate fewer than 50 sessions.")


def product_view(data):
    if data.is_empty():
        st.info("No items reached the minimum number of viewing sessions.")
        return
    figure = go.Figure(go.Scatter(
        x=data["views"].to_list(), y=data["Conversion"].to_list(),
        text=data["item_name"].to_list(), mode="markers", marker=dict(color=GREEN, size=10, opacity=0.65),
        hovertemplate="%{text}<br>%{x:,} viewing sessions<br>%{y:.1%} same-item conversion<extra></extra>",
    ))
    figure.update_xaxes(title="Viewing sessions", gridcolor="#dfe8e4")
    figure.update_yaxes(title="Same-item purchase rate", tickformat=".1%", rangemode="tozero", gridcolor="#dfe8e4")
    chart(figure)
    st.dataframe(data.select("item_id", "item_name", "category", "views", "purchases", "Conversion"),
                 hide_index=True, column_config={"Conversion": PERCENT, "item_name": "Product",
                                                "views": "Viewing sessions", "purchases": "Same-item buyers (sessions)"})
    st.caption("Ranked among the 200 most-viewed eligible products. Each item’s rate uses its own viewing sessions.")


def show_overview(scope, available):
    daily = report("daily", scope)
    counts = total(daily)
    prior = previous(scope)
    prior_counts = total(report("daily", prior)) if has_coverage(prior, available) else None
    purchase_rate = rate(counts["purchasing_sessions"], counts["sessions"])
    old_rate = rate(prior_counts["purchasing_sessions"], prior_counts["sessions"]) if prior_counts else None
    change = f"{(purchase_rate - old_rate) * 100:+.2f} pp" if purchase_rate is not None and old_rate is not None else None
    measures = st.columns(4)
    measures[0].metric("Sessions", f'{counts["sessions"]:,}')
    measures[1].metric("Purchase conversion", percent(purchase_rate), delta=change)
    measures[2].metric("Purchasing sessions", f'{counts["purchasing_sessions"]:,}')
    measures[3].metric("Ordered funnel completion", percent(rate(counts["ordered_purchases"], counts["sessions"])))
    if prior_counts:
        st.caption(f"Comparison period · {prior.start:%b %d}–{prior.end:%b %d, %Y}")
    if not counts["sessions"]:
        st.info("No sessions match the selected filters.")
        return
    left, right = st.columns(2)
    with left:
        st.subheader("Shopping funnel")
        funnel_chart(counts)
        st.dataframe(funnel_rows(counts), hide_index=True, column_config={"Step rate": PERCENT})
    with right:
        st.subheader("Purchase conversion by day")
        trend(daily)
        full_path = rate(counts["ordered_purchases"], counts["purchasing_sessions"])
        st.caption(f"{percent(full_path)} of purchasing sessions followed every recorded funnel step in order.")
    with st.expander("Data coverage and orders"):
        quality = report("quality", scope)
        cols = st.columns(3)
        view_coverage = rate(quality["view_events_with_item_id"].sum(), quality["view_events"].sum())
        order_coverage = rate(quality["orders_with_revenue"].sum(), quality["orders"].sum())
        cols[0].metric("Purchases without a session", f'{quality["unassigned_purchases"].sum():,}')
        cols[1].metric("Views with a usable item ID", percent(view_coverage))
        cols[2].metric("Canonical orders with USD revenue", percent(order_coverage))
        st.caption("Coverage, deduplicated orders, and gross observed USD revenue are by event date for all segments.")
        st.dataframe(quality, hide_index=True)


def show_segments(scope, available):
    dimension = st.selectbox("Break down by", DIMENSIONS, format_func=DIMENSION_LABELS.get)
    segment_view(add_conversion(report("segments", scope, dimension)))
    st.subheader("Weekly return cohorts")
    st.caption("All segments, grouped by first observed week. Weeks require seven days of data.")
    data = report("cohorts", scope)
    cells = {(row["cohort_week"], row["week_number"]): row for row in data.iter_rows(named=True)}
    cohorts = sorted(cohort for cohort, week in cells if week == 0
                     and has_coverage(Scope(cohort, cohort + timedelta(days=6)), available)
                     and cohort + timedelta(days=6) <= scope.end)
    if not cohorts:
        st.info("Select a date range with a fully observed Monday–Sunday cohort.")
        return
    weeks = list(range((scope.end - cohorts[0]).days // 7 + 1))
    values = []
    for cohort in cohorts:
        size = cells[(cohort, 0)]["cohort_size"]
        values.append([
            cells.get((cohort, week), {}).get("active_users", 0) / size
            if cohort + timedelta(days=7 * week + 6) <= scope.end
            and has_coverage(Scope(cohort + timedelta(days=7 * week), cohort + timedelta(days=7 * week + 6)), available)
            else None for week in weeks
        ])
    fig = go.Figure(go.Heatmap(
        x=[f"Week {week}" for week in weeks], y=[cohort.isoformat() for cohort in cohorts],
        z=values, zmin=0, zmax=1, colorscale=[[0, "#edf4f1"], [1, GREEN]],
        colorbar=dict(tickformat=".0%"), hoverongaps=False,
        text=[[percent(value) for value in row] for row in values], texttemplate="%{text}",
        hovertemplate="Cohort %{y}<br>%{x} · %{z:.1%}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed")
    chart(fig, max(260, len(cohorts) * 34 + 80))


def show_anomalies(scope, available):
    st.subheader("Unusual daily conversion")
    history = replace(scope, start=min(available))
    alerts = [alert for alert in daily_alerts(report("daily", history)) if alert["Date"] >= scope.start]
    st.caption("Flags days that differ by at least 2.5 percentage points from two or more prior matching weekdays. Minimum 75 sessions per day.")
    if alerts:
        st.dataframe(alerts, hide_index=True, column_config={"Conversion": PERCENT, "Baseline": PERCENT})
    else:
        st.info("No daily conversion flags for these filters.")
    st.subheader("Session review queue")
    data = report("anomalies", scope)
    if data.is_empty():
        st.info("No flagged sessions match these filters.")
        return
    reasons = {"repeated_purchase": "Repeated purchase event",
               "purchase_without_checkout": "Purchase without a checkout event",
               "unusual_events": "Event count above the device’s 99th percentile",
               "unusual_duration": "Observed duration above the device’s 99th percentile"}
    rows = {}
    for index, row in enumerate(data.iter_rows(named=True), 1):
        label = f'{row["session_date"]:%b %d} · {row["device"]} · Session {index}'
        row["Reasons"] = ", ".join(title for field, title in reasons.items() if row[field])
        rows[label] = row
    st.dataframe([
        {"Session": label, "Reasons": row["Reasons"], "Events": row["events"],
         "Seconds": row["observed_seconds"], "Device p99 events": row["p99_events"],
         "Device p99 seconds": row["p99_seconds"], "Device baseline sessions": row["baseline_sessions"]}
        for label, row in rows.items()
    ], hide_index=True)
    selected = rows[st.selectbox("Inspect an event sequence", rows.keys())]
    journey = report("journey", Scope(selected["session_date"], max(available)),
                     session_key=selected["session_key"])
    if len(journey):
        st.dataframe(journey.with_columns(((pl.col("event_us") - pl.col("event_us").min()) / 1_000_000)
                                          .alias("Seconds from first event")).drop("event_us"), hide_index=True)


def show_copilot(scope, options, available):
    provider_name = configured_provider()
    st.caption({
        "ollama": "Ollama runs a local model to interpret questions and summarize aggregate evidence.",
        "gemini": "Gemini interprets questions and summarizes aggregate evidence.",
        "example": "Example mode uses a built-in question matcher. Configure Ollama or Gemini for model-powered interpretation.",
    }[provider_name])
    st.caption(f"“Last week” uses the latest complete Monday–Sunday period ending on or before {scope.end:%b %d, %Y}.")
    example = st.selectbox("Start with an example", EXAMPLES, key="copilot-example")
    question = st.text_input("Your question", value=example, max_chars=500, key=f"question-{example}")
    context = (warehouse.mode, scope, question, provider_name)
    if st.button("Run analysis", type="primary", disabled=not question.strip()):
        st.session_state.pop("analysis_result", None)
        try:
            provider = create_provider(provider_name)
            with st.spinner("Checking the available data and running the analysis…"):
                request = provider.ask(question, options) if provider else demo_request(question, options)
                result = investigate(request, scope, available, options, warehouse.compile, execute)
                interpretation = None
                if provider and result["evidence"]:
                    try:
                        interpretation = provider.summarize(result)
                    except Exception as error:
                        logger.warning("Summary unavailable (%s)", type(error).__name__)
                        st.info("The AI summary is unavailable. The computed evidence is shown below.")
                st.session_state["analysis_result"] = (context, request, result, interpretation)
        except ValueError as error:
            # Pydantic diagnostics can include untrusted provider output.
            from pydantic import ValidationError
            st.warning("The question could not be mapped to a supported report." if isinstance(error, ValidationError)
                       else str(error))
        except Exception as error:
            logger.warning("Investigation unavailable (%s)", type(error).__name__)
            st.error("The investigation could not finish. Check your warehouse or model connection and try again.")
    stored = st.session_state.get("analysis_result")
    if not stored or stored[0] != context:
        return
    _, request, result, interpretation = stored
    period = result["scope"]
    filters = ", ".join(f"{DIMENSION_LABELS[field]} = {getattr(period, field)}"
                        for field in DIMENSIONS if getattr(period, field)) or "All segments"
    dates = f"{period.start:%b %d}–{period.end:%b %d, %Y}"
    if prior := result["prior"]:
        dates += f" compared with {prior.start:%b %d}–{prior.end:%b %d, %Y}"
    st.caption(f"{dates} · {filters}")
    if "change" in result:
        change = result["change"]
        st.metric("Purchase conversion", percent(rate(result["counts"]["purchasing_sessions"], result["counts"]["sessions"])),
                  delta=f"{change:+.2f} pp")
        if not result["decline"]:
            st.info("Purchase conversion did not decline in the selected comparison.")
        if step_loss := result.get("largest_step_loss"):
            st.caption(f"Largest step-rate decline · {step_loss[0]} ({step_loss[1]:+.2f} pp)")
        trend(pl.concat([result["old_daily"], result["daily"]]).sort("session_date"))
    if "counts" in result:
        funnel_chart(result["counts"], result.get("old"))
    if "products" in result:
        product_view(result["products"])
    if "segments" in result:
        segment_view(result["segments"])
    if result.get("comparison"):
        st.subheader(f"Contribution by {DIMENSION_LABELS[request.breakdown].lower()}")
        st.dataframe(result["comparison"], hide_index=True,
                     column_config={"Prior rate": PERCENT, "Current rate": PERCENT})
        st.caption("Mix, within-segment, and one-period contributions add up to the change in the overall rate.")
    if interpretation:
        st.subheader("Interpretation")
        st.text(interpretation.takeaway + " (" + ", ".join(interpretation.evidence_ids) + ")")
    hypotheses = interpretation.hypotheses if interpretation and interpretation.hypotheses else suggested_checks(result)
    if hypotheses:
        st.subheader("Hypotheses to check")
        for item in hypotheses:
            st.text(f"{item.possible_explanation} ({item.evidence_id})")
            st.text(item.how_to_check)
    st.subheader("Query evidence")
    for item in result["evidence"]:
        st.text(f'{item["id"]}  {item["description"]}')
    with st.expander("SQL and query parameters"):
        for query in result["queries"]:
            st.code(query.sql, language="sql")
            if query.parameters:
                st.json({key: str(value) for key, value in query.parameters.items()})


def main():
    global warehouse
    default = os.getenv("FUNNEL_MODE", "demo")
    modes = ["demo", "bigquery", "snapshot"]
    if default not in modes:
        default = "demo"
    with st.sidebar:
        st.markdown("### Funnel Intelligence")
        page = st.radio("Report", ["Overview", "Segments & cohorts", "Products", "Anomalies", "Analytics Copilot"])
        mode = st.selectbox("Data source", modes, index=modes.index(default),
                            format_func={"demo": "Synthetic demo", "bigquery": "Google Merchandise Store (live)",
                                         "snapshot": "Google Merchandise Store (local snapshot)"}.get)

    st.title({
        "Overview": "E-commerce conversion", "Segments & cohorts": "Segments and cohorts",
        "Products": "Product opportunities", "Anomalies": "Conversion and session anomalies",
        "Analytics Copilot": "Analytics Copilot",
    }[page])
    try:
        warehouse = Warehouse(mode)
        if mode != "bigquery" and not warehouse.db_path.is_file():
            st.error("The selected local database has not been built. See the README for the build or export command.")
            return
        available = set(report("coverage")["report_date"].to_list())
        if not available:
            st.warning("No dates are available in this warehouse.")
            return
        option_rows = report("options")
        options = {field: sorted(option_rows[field].unique().drop_nulls().to_list()) for field in DIMENSIONS}
        first, last = min(available), max(available)
        source_label = {
            "demo": "Synthetic GA4-shaped events",
            "bigquery": "Google Merchandise Store GA4 sample · live BigQuery",
            "snapshot": "Google Merchandise Store GA4 sample · reporting snapshot",
        }[mode]
        st.caption(f"{source_label} · {first:%b %d, %Y}–{last:%b %d, %Y}")
        with st.sidebar:
            case_start, case_end = date(2020, 12, 14), date(2020, 12, 27)
            if mode != "demo" and has_coverage(Scope(case_start, case_end), available):
                def load_case():
                    st.session_state[f"dates-{mode}"] = (case_start, case_end)
                st.button("Load December mobile case", on_click=load_case)
            selected = st.date_input("Session date", (max(first, last - timedelta(days=13)), last),
                                     min_value=first, max_value=last, key=f"dates-{mode}")
            filters = {
                field: st.selectbox(DIMENSION_LABELS[field], ["", *options[field]], key=f"{mode}-{field}",
                                    format_func=lambda value: value or "All")
                for field in DIMENSIONS
            }
        if len(selected) != 2:
            st.info("Choose a start date and an end date.")
            return
        scope = Scope(*selected, **filters)
        if not has_coverage(scope, available):
            st.warning("Some dates in this selection are missing from the source.")
        if page == "Overview":
            show_overview(scope, available)
        elif page == "Segments & cohorts":
            show_segments(scope, available)
        elif page == "Products":
            minimum = st.number_input("Minimum viewing sessions", min_value=1, value=30, step=10)
            product_view(top_product_opportunities(report("products", scope), minimum))
        elif page == "Anomalies":
            show_anomalies(scope, available)
        else:
            show_copilot(scope, options, available)
    except Exception as error:
        logger.warning("Report unavailable (%s)", type(error).__name__)
        st.error("The report could not load. Check the selected warehouse connection and build status.")


if __name__ == "__main__":
    main()
