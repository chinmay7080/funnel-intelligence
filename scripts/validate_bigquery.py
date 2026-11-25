"""Build the seven-day validation dataset and reconcile it with raw GA4 counts."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from funnel.warehouse import Warehouse


def query_one(client, sql, scan_limit):
    dry = client.query(
        sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False), timeout=15,
    )
    if dry.total_bytes_processed is None or dry.total_bytes_processed > scan_limit:
        raise RuntimeError("The query exceeds the validation scan limit.")
    job = client.query(
        sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=scan_limit, job_timeout_ms=60_000),
        timeout=15,
    )
    rows = list(job.result(timeout=65))
    if len(rows) != 1:
        raise RuntimeError("Expected exactly one reconciliation row.")
    return dict(rows[0])


def reporting_query(project, dataset):
    return f"""
        with quality as (
            select count(*) as dates,
                coalesce(sum(event_count), 0) as events,
                coalesce(sum(unassigned_events), 0) as unassigned_events,
                coalesce(sum(purchase_events), 0) as purchase_events,
                coalesce(sum(unassigned_purchases), 0) as unassigned_purchases,
                coalesce(sum(orders), 0) as orders
            from `{project}.{dataset}.mart_data_quality`
            where report_date between date '2021-01-04' and date '2021-01-10'
        ),
        funnel as (
            select coalesce(sum(sessions), 0) as sessions,
                coalesce(sum(purchasing_sessions), 0) as purchasing_sessions
            from `{project}.{dataset}.mart_daily_funnel`
            where session_date between date '2021-01-04' and date '2021-01-10'
        )
        select * from quality cross join funnel
    """


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="Check a previously built validation dataset.")
    args = parser.parse_args()
    os.environ.setdefault("FUNNEL_BQ_DATASET", "funnel_validation")
    warehouse = Warehouse("bigquery")
    if not args.validate_only and warehouse.dataset == "funnel_analytics":
        parser.error("Use a separate validation dataset so the slice cannot replace a full-history build.")
    client = bigquery.Client(project=warehouse.project, location="US")
    scan_limit = int(os.environ.get("FUNNEL_VALIDATION_MAX_BYTES", str(2 * 1024**3)))
    source = ROOT / "warehouse/audits/reconcile_validation_slice.sql"
    expected = query_one(client, source.read_text(), scan_limit)
    if expected["dates"] != 7 or not expected["sessions"]:
        raise RuntimeError("The source did not return seven days with eligible sessions.")

    if not args.validate_only:
        subprocess.run(
            [str(Path(sys.executable).with_name("dbt")), "build", "--project-dir", "warehouse",
             "--profiles-dir", "warehouse", "--target", "bigquery",
             "--vars", '{source_start: "2021-01-04", source_end: "2021-01-10"}'],
            cwd=ROOT, env={**os.environ, "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}, check=True,
        )

    reported = query_one(client, reporting_query(warehouse.project, warehouse.dataset), scan_limit)
    print(f'{"Metric":26} {"Raw GA4":>15} {"Reporting models":>17}')
    for metric, value in expected.items():
        print(f"{metric:26} {value:15,} {reported[metric]:17,}")
    if expected != reported:
        raise SystemExit("Source and reporting totals differ.")
    print(f'Purchase conversion {reported["purchasing_sessions"] / reported["sessions"]:.2%}')


if __name__ == "__main__":
    main()
