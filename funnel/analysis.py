"""Metrics shared by dashboard reports and Copilot investigations."""

from dataclasses import replace
from datetime import timedelta

import polars as pl

from funnel.warehouse import COUNTS, Scope

STAGES = ("sessions", "views", "adds", "checkouts", "ordered_purchases")
STAGE_LABELS = ("Traffic", "Product view", "Add to cart", "Checkout", "Purchase")


def rate(numerator, denominator):
    return numerator / denominator if denominator else None


def percent(value):
    return "—" if value is None else f"{value:.1%}"


def total(daily):
    return {name: int(daily[name].sum() or 0) for name in COUNTS}


def funnel_rows(counts):
    rows = []
    for index, (field, label) in enumerate(zip(STAGES, STAGE_LABELS)):
        count = counts[field]
        prior = counts[STAGES[index - 1]] if index else count
        completion = rate(count, prior)
        rows.append({
            "Stage": label, "Sessions": count, "Step rate": completion,
            "Lost sessions": (prior - count) if index else None,
        })
    return rows


def previous(scope):
    length = scope.end - scope.start + timedelta(days=1)
    return replace(scope, start=scope.start - length, end=scope.end - length)


def last_full_week(anchor):
    sunday = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
    return sunday - timedelta(days=6), sunday


def has_coverage(scope: Scope, available: set):
    return all(scope.start + timedelta(days=i) in available for i in range((scope.end - scope.start).days + 1))


def add_conversion(frame, numerator="purchasing_sessions", denominator="sessions"):
    return frame.with_columns(
        pl.when(pl.col(denominator) > 0).then(pl.col(numerator) / pl.col(denominator))
        .otherwise(None).alias("Conversion")
    )


def top_product_opportunities(frame, min_views=30):
    supported = add_conversion(frame, "purchases", "views").filter(pl.col("views") >= min_views)
    return supported.sort(["Conversion", "views"], descending=[False, True])


def compare_segments(current, prior, minimum=50):
    """Symmetric rate/mix decomposition, including an explicit one-period effect."""
    new = {row["segment"]: row for row in current.iter_rows(named=True)}
    old = {row["segment"]: row for row in prior.iter_rows(named=True)}
    current_n = sum(row["sessions"] for row in new.values())
    prior_n = sum(row["sessions"] for row in old.values())
    if not current_n or not prior_n:
        return []
    rows = []
    for label in sorted(new.keys() | old.keys()):
        n1 = new.get(label, {}).get("sessions", 0)
        n0 = old.get(label, {}).get("sessions", 0)
        r1 = rate(new.get(label, {}).get("purchasing_sessions", 0), n1)
        r0 = rate(old.get(label, {}).get("purchasing_sessions", 0), n0)
        w1, w0 = n1 / current_n, n0 / prior_n
        mix = performance = one_period = 0.0
        if r1 is None or r0 is None:
            one_period = w1 * (r1 or 0.0) - w0 * (r0 or 0.0)
        else:
            mix = (w1 - w0) * (r1 + r0) / 2
            performance = (r1 - r0) * (w1 + w0) / 2
        rows.append({
            "Segment": label, "Prior sessions": n0, "Current sessions": n1,
            "Prior rate": r0, "Current rate": r1, "Mix (pp)": 100 * mix,
            "Within (pp)": 100 * performance, "One-period only (pp)": 100 * one_period,
            "Total (pp)": 100 * (mix + performance + one_period), "Low volume": min(n0, n1) < minimum,
        })
    return sorted(rows, key=lambda row: abs(row["Total (pp)"]), reverse=True)


def daily_alerts(daily, minimum=75, min_pp=0.025):
    """Compare each day to the earlier available matching weekdays in this view."""
    by_weekday = {}
    alerts = []
    for row in daily.sort("session_date").iter_rows(named=True):
        weekday = row["session_date"].weekday()
        comparable = by_weekday.setdefault(weekday, [])
        if row["sessions"] >= minimum and len(comparable) >= 2:
            baseline_n = sum(day["sessions"] for day in comparable)
            baseline = sum(day["purchasing_sessions"] for day in comparable) / baseline_n
            observed = row["purchasing_sessions"] / row["sessions"]
            if abs(observed - baseline) >= min_pp:
                alerts.append({"Date": row["session_date"], "Sessions": row["sessions"],
                               "Conversion": observed, "Baseline": baseline,
                               "Prior matching days": len(comparable), "Change (pp)": (observed - baseline) * 100})
        if row["sessions"] >= minimum:
            comparable.append(row)
    return alerts
