"""Build a reproducible local warehouse from synthetic GA4-shaped events."""

import json
import os
import random
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
START = date(2021, 1, 4)
END = date(2021, 1, 31)
PRODUCTS = [
    ("P01", "Canvas Tote", "Accessories"),
    ("P02", "Everyday Bottle", "Accessories"),
    ("P03", "Cloud Crewneck", "Apparel"),
    ("P04", "Classic Tee", "Apparel"),
    ("P05", "Studio Notebook", "Stationery"),
    ("P06", "Travel Mug", "Accessories"),
]
CHANNELS = [
    ("google", "organic"),
    ("(direct)", "(none)"),
    ("google", "cpc"),
    ("newsletter", "email"),
    ("partner", "referral"),
]


def event(at, name, user, sid, session_number, device, channel, items=(), order=None, revenue=None):
    return {
        "event_date": at.strftime("%Y%m%d"),
        "event_timestamp": int(at.timestamp() * 1_000_000),
        "event_name": name,
        "user_pseudo_id": user,
        "event_params": [
            {"key": key, "value": {"int_value": value}}
            for key, value in [("ga_session_id", sid), ("ga_session_number", session_number)]
        ],
        "device": {"category": device},
        "traffic_source": dict(zip(("source", "medium"), channel)),
        "ecommerce": {"transaction_id": order, "purchase_revenue_in_usd": revenue},
        "items": [dict(zip(("item_id", "item_name", "item_category"), item)) for item in items],
    }


def generate_events():
    rng = random.Random(42)
    people = {}
    next_user = 0
    for offset in range((END - START).days + 1):
        day = START + timedelta(days=offset)
        for index in range(195 + rng.randrange(45)):
            if people and rng.random() < 0.34:
                user = rng.choice(list(people))
                channel, device, visits = people[user]
            else:
                next_user += 1
                user = f"visitor-{next_user}"
                channel = rng.choices(CHANNELS, [38, 25, 20, 12, 5])[0]
                device = rng.choices(["mobile", "desktop", "tablet"], [59, 36, 5])[0]
                visits = 0
            people[user] = (channel, device, visits + 1)
            at = datetime.combine(day, time(8), UTC) + timedelta(seconds=index * 170)
            sid = int(at.timestamp())
            item = rng.choices(PRODUCTS, [25, 18, 17, 16, 14, 10])[0]

            if index != 22:
                yield event(at, "session_start", user, sid, visits + 1, device, channel)
            if visits == 0:
                yield event(at + timedelta(seconds=1), "first_visit", user, sid, 1, device, channel)

            stages = [("page_view", 2, ())]
            if rng.random() < 0.82:
                stages.append(("view_item", 9, (item,)))
                cart_rate = 0.19 if item[0] == "P01" else 0.41
                if rng.random() < cart_rate:
                    stages.append(("add_to_cart", 20, (item,)))
                    if rng.random() < 0.73:
                        stages.append(("begin_checkout", 45, (item,)))
                        checkout_rate = 0.37 if device == "mobile" and offset >= 21 else 0.69
                        if rng.random() < checkout_rate:
                            stages.append(("purchase", 75, (item,)))
                if index % 101 == 0:  # One valid same-session purchase can skip checkout.
                    stages.append(("purchase", 88, (item,)))
            if index == 13:  # High event count fixture.
                stages.extend(("page_view", 100 + i, ()) for i in range(25))
            if index == 51:  # Longer than a typical observed event sequence.
                stages.append(("page_view", 9500, ()))
            for name, seconds, items in stages:
                order = f"order-{offset}-{index}" if name == "purchase" else None
                row = event(at + timedelta(seconds=seconds), name, user, sid, visits + 1,
                            device, channel, items, order, 24.99 + index % 37 if order else None)
                yield row
                if order and index % 31 == 0:
                    yield row

    at = datetime.combine(START, time(23, 59, 51), UTC)
    sid = int(at.timestamp())
    for name, seconds, item_index in [
        ("session_start", 0, None), ("view_item", 5, 0), ("add_to_cart", 5, 0),
        ("add_to_cart", 7, 0), ("begin_checkout", 12, 0), ("purchase", 13, 1),
    ]:
        yield event(at + timedelta(seconds=seconds), name, "fixture-midnight", sid, 1, "mobile",
                    CHANNELS[0], (PRODUCTS[item_index],) if item_index is not None else (),
                    "fixture-order" if name == "purchase" else None, 35 if name == "purchase" else None)
    yield event(at, "purchase", None, None, None, "mobile", CHANNELS[0], order="<Other>")


def main():
    path = Path(os.environ.get("FUNNEL_DB_PATH", ROOT / ".data/funnel.duckdb")).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as temp:
        working_db = Path(temp) / "funnel.duckdb"
        events_path = Path(temp) / "events.jsonl"
        with events_path.open("w") as stream:
            for row in generate_events():
                stream.write(json.dumps(row) + "\n")
        with duckdb.connect(str(working_db)) as conn:
            conn.execute("create schema raw")
            conn.execute("""
                create table raw.events as select * from read_json(?, format = 'newline_delimited',
                    columns = {
                        event_date: 'VARCHAR', event_timestamp: 'BIGINT', event_name: 'VARCHAR',
                        user_pseudo_id: 'VARCHAR', event_params: 'STRUCT(key VARCHAR, value STRUCT(int_value BIGINT))[]',
                        device: 'STRUCT(category VARCHAR)', traffic_source: 'STRUCT(source VARCHAR, medium VARCHAR)',
                        ecommerce: 'STRUCT(transaction_id VARCHAR, purchase_revenue_in_usd DOUBLE)',
                        items: 'STRUCT(item_id VARCHAR, item_name VARCHAR, item_category VARCHAR)[]'
                    })
            """, [str(events_path)])
        subprocess.run(
            [str(Path(sys.executable).with_name("dbt")), "build", "--project-dir", "warehouse",
             "--profiles-dir", "warehouse", "--target", "demo"],
            cwd=ROOT, env={**os.environ, "FUNNEL_DB_PATH": str(working_db), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"},
            check=True,
        )
        working_db.replace(path)


if __name__ == "__main__":
    main()
