"""Generate bounded report SQL and execute it against the selected warehouse."""

import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import monotonic

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS = ("device", "channel", "visitor")
DIMENSION_LABELS = {"device": "Device", "channel": "First acquisition channel", "visitor": "Visitor status"}
COUNTS = ("sessions", "views", "adds", "checkouts", "ordered_purchases", "purchasing_sessions")
TABLES = {
    "coverage": "mart_data_quality",
    "options": "mart_daily_funnel",
    "daily": "mart_daily_funnel",
    "segments": "mart_daily_funnel",
    "products": "mart_daily_products",
    "cohorts": "mart_weekly_cohorts",
    "anomalies": "mart_session_anomalies",
    "journey": "mart_journey_events",
    "quality": "mart_data_quality",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Scope:
    start: date
    end: date
    device: str = ""
    channel: str = ""
    visitor: str = ""

    def __post_init__(self):
        if self.start > self.end or (self.end - self.start).days >= 92:
            raise ValueError("Choose an ordered date range of up to 92 days.")


@dataclass(frozen=True)
class Query:
    sql: str
    parameters: dict


class Warehouse:
    def __init__(self, mode="demo"):
        if mode not in {"demo", "snapshot", "bigquery"}:
            raise ValueError("Unknown warehouse mode.")
        self.mode = mode
        if mode == "snapshot":
            self.db_path = Path(os.getenv("FUNNEL_SNAPSHOT_PATH", ROOT / ".data/ga4_snapshot.duckdb"))
        else:
            self.db_path = Path(os.getenv("FUNNEL_DB_PATH", ROOT / ".data/funnel.duckdb"))
        self.project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
        self.dataset = os.getenv("FUNNEL_BQ_DATASET", "funnel_analytics")
        if mode == "bigquery" and (
            not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", self.project)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,1023}", self.dataset)
        ):
            raise ValueError("Set GOOGLE_CLOUD_PROJECT and a valid FUNNEL_BQ_DATASET.")

    def compile(self, report, scope=None, dimension=None, session_key=None):
        name = TABLES[report]
        table = f"`{self.project}.{self.dataset}.{name}`" if self.mode == "bigquery" else f"analytics.{name}"
        token = "@" if self.mode == "bigquery" else "$"
        if report == "coverage":
            return Query(f"select report_date from {table} order by report_date limit 92", {})
        if report == "options":
            return Query(f"select distinct device, channel, visitor from {table} limit 1000", {})
        if scope is None:
            raise ValueError("A report date range is required.")
        params = {"start_date": scope.start, "end_date": scope.end}
        date_column = {
            "quality": "report_date", "cohorts": "cohort_week", "journey": "observed_date"
        }.get(report, "session_date")
        where = f"{date_column} between {token}start_date and {token}end_date"
        if report in {"daily", "segments", "products", "anomalies"}:
            for field in DIMENSIONS:
                value = getattr(scope, field)
                if value:
                    where += f" and {field} = {token}{field}"
                    params[field] = value

        counts = ", ".join(f"cast(sum({column}) as bigint) as {column}" for column in COUNTS)
        if report == "daily":
            sql = f"select session_date, {counts} from {table} where {where} group by session_date order by session_date"
        elif report == "segments":
            if dimension not in DIMENSIONS:
                raise ValueError("Unsupported breakdown.")
            sql = f"""select {dimension} as segment, {counts}
                      from {table} where {where} group by {dimension} order by sessions desc, segment limit 100"""
        elif report == "products":
            sql = f"""select item_id, item_name, category, cast(sum(views) as bigint) as views,
                      cast(sum(adds) as bigint) as adds, cast(sum(purchases) as bigint) as purchases
                      from {table} where {where} group by item_id, item_name, category
                      order by views desc, item_id limit 200"""
        elif report == "anomalies":
            sql = f"""select * from {table} where {where}
                      order by repeated_purchase desc, purchase_without_checkout desc,
                          unusual_duration desc, events desc, session_key limit 100"""
        elif report == "journey":
            if not session_key:
                raise ValueError("Select a session from the review queue.")
            params["session_key"] = session_key
            sql = f"""select observed_date, event_us, event_name,
                          (event_us - lag(event_us) over (order by event_us, event_name)) / 1000000.0
                              as seconds_since_previous_event
                      from {table}
                      where {where} and session_key = {token}session_key
                      order by event_us, event_name limit 200"""
        elif report == "cohorts":
            sql = f"""select * from {table} where {where}
                      and activity_week <= {token}end_date order by cohort_week, week_number limit 200"""
        else:
            sql = f"select * from {table} where {where} order by report_date limit 92"
        return Query(sql, params)

    def run(self, query):
        if self.mode != "bigquery":
            import duckdb

            with duckdb.connect(str(self.db_path), read_only=True) as connection:
                return pl.from_arrow(connection.sql(query.sql, params=query.parameters).to_arrow_table())

        from google.cloud import bigquery

        client = bigquery.Client(project=self.project, location="US")
        parameters = [
            bigquery.ScalarQueryParameter(key, "DATE" if isinstance(value, date) else "STRING", value)
            for key, value in query.parameters.items()
        ]
        limit = int(os.getenv("FUNNEL_MAX_BYTES", str(256 * 1024 * 1024)))
        started = monotonic()
        dry = client.query(
            query.sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False,
                                                       query_parameters=parameters), timeout=10,
        )
        if dry.total_bytes_processed is None or dry.total_bytes_processed > limit:
            raise ValueError("This report exceeds the configured BigQuery scan limit.")
        job = client.query(query.sql, job_config=bigquery.QueryJobConfig(
            query_parameters=parameters, maximum_bytes_billed=limit, job_timeout_ms=25000,
        ), timeout=10)
        try:
            rows = job.result(timeout=25, max_results=1001)
            return pl.from_arrow(rows.to_arrow(create_bqstorage_client=False))
        except TimeoutError:
            job.cancel(timeout=5)
            raise
        finally:
            logger.info("BigQuery job %s, estimated bytes %s, elapsed %.2fs",
                        job.job_id, dry.total_bytes_processed, monotonic() - started)
