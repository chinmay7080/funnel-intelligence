"""Compile the BigQuery dbt target without Google credentials and parse its GoogleSQL."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import sqlglot
from dbt.cli.main import dbtRunner
from google.auth.credentials import AnonymousCredentials


def main():
    root = Path(__file__).resolve().parents[1]
    warehouse = str(root / "warehouse")
    os.environ["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
    os.environ["GOOGLE_CLOUD_PROJECT"] = "ga4-offline-validation"
    with tempfile.TemporaryDirectory() as output:
        # Anonymous credentials allow local compilation. Introspection and cache loading are disabled.
        with patch("google.auth.default", return_value=(AnonymousCredentials(), "ga4-offline-validation")):
            result = dbtRunner().invoke([
                "compile", "--project-dir", warehouse, "--profiles-dir", warehouse, "--target", "bigquery",
                "--no-introspect", "--no-populate-cache", "--target-path", output,
            ])
        if not result.success:
            raise SystemExit(1)
        paths = list((Path(output) / "compiled").rglob("*.sql"))
        if not paths:
            raise RuntimeError("dbt did not produce compiled SQL.")
        for path in paths:
            sqlglot.parse_one(path.read_text(), read="bigquery")
        print(f"Parsed {len(paths)} compiled GoogleSQL models and tests.")


if __name__ == "__main__":
    main()
