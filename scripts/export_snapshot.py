"""Copy the public sample's reporting tables into a local, credential-free DuckDB snapshot."""

import os
import sys
import tempfile
from pathlib import Path

import duckdb
from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from funnel.warehouse import TABLES, Warehouse


def main():
    source = Warehouse("bigquery")
    target = Warehouse("snapshot").db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    client = bigquery.Client(project=source.project, location="US")
    limit = int(os.getenv("FUNNEL_SNAPSHOT_MAX_BYTES", str(1024**3)))

    with tempfile.TemporaryDirectory(dir=target.parent) as temp:
        staged = Path(temp) / "snapshot.duckdb"
        with duckdb.connect(str(staged)) as db:
            db.execute("create schema analytics")
            for table in sorted(set(TABLES.values())):
                relation = f"`{source.project}.{source.dataset}.{table}`"
                columns = "*"
                if table in {"mart_session_anomalies", "mart_journey_events"}:
                    columns = "* replace (to_hex(sha256(session_key)) as session_key)"
                sql = f"select {columns} from {relation}"
                dry_run = client.query(
                    sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False), timeout=20
                )
                if dry_run.total_bytes_processed is None or dry_run.total_bytes_processed > limit:
                    raise RuntimeError(f"Snapshot scan limit exceeded for {table}.")
                job = client.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=limit), timeout=20)
                rows = job.result(timeout=60)
                db.register("export_rows", rows.to_arrow(create_bqstorage_client=False))
                db.execute(f"create table analytics.{table} as select * from export_rows")
                count = db.execute(f"select count(*) from analytics.{table}").fetchall()[0][0]
                db.unregister("export_rows")
                print(f"{table}: {count:,} rows", flush=True)
        staged.replace(target)
    print(f"Reporting snapshot ready: {target.name}", flush=True)


if __name__ == "__main__":
    main()
