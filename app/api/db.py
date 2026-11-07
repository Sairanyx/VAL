"""Local TimescaleDB: telemetry over time, and scene changes that survive a restart.

    make db                 # start the database and load the Excel telemetry

Telemetry keeps a `source`, so simulated readings can never be mistaken for the Excel pack's.
"""

import argparse
import json
import os

import psycopg
from psycopg.types.json import Jsonb

EXCEL_SOURCE = "excel_sample"
CONNECT_TIMEOUT = 2

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE TABLE IF NOT EXISTS telemetry (
    time TIMESTAMPTZ NOT NULL,
    asset_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    source TEXT NOT NULL,
    metrics JSONB NOT NULL,
    UNIQUE (asset_id, source, time)
);
SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);
CREATE TABLE IF NOT EXISTS scene_changes (
    change_id BIGSERIAL PRIMARY KEY,
    scene_id TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    op TEXT NOT NULL,
    object_id TEXT NOT NULL,
    position JSONB
);
"""


class Database:
    def __init__(self, url: str):
        self.conn = psycopg.connect(url, autocommit=True, connect_timeout=CONNECT_TIMEOUT)
        self.conn.execute(SCHEMA)

    def save_change(self, scene_id: str, change: dict) -> None:
        self.conn.execute(
            "INSERT INTO scene_changes (scene_id, op, object_id, position) VALUES (%s, %s, %s, %s)",
            (scene_id, change["op"], change["object_id"], Jsonb(change["position"])),
        )

    def load_changes(self, scene_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT op, object_id, position FROM scene_changes "
            "WHERE scene_id = %s ORDER BY change_id",
            (scene_id,),
        ).fetchall()
        return [{"op": op, "object_id": obj, "position": pos} for op, obj, pos in rows]

    def clear_changes(self, scene_id: str) -> None:
        self.conn.execute("DELETE FROM scene_changes WHERE scene_id = %s", (scene_id,))

    def add_telemetry(self, rows: list[tuple[str, str, str, str, dict]]) -> None:
        """Add (time, asset_id, tag, source, metrics) rows, skipping any already stored."""
        with self.conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO telemetry (time, asset_id, tag, source, metrics) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [(time, asset, tag, source, Jsonb(m)) for time, asset, tag, source, m in rows],
            )

    def telemetry(self, asset_id: str, limit: int = 20) -> list[dict]:
        """Return an asset's latest readings, newest first, each saying where it came from."""
        rows = self.conn.execute(
            "SELECT time, tag, source, metrics FROM telemetry "
            "WHERE asset_id = %s ORDER BY time DESC LIMIT %s",
            (asset_id, limit),
        ).fetchall()
        return [
            {
                "timestamp": time.isoformat(),
                "asset_id": asset_id,
                "tag": tag,
                "source": source,
                "metrics": metrics,
            }
            for time, tag, source, metrics in rows
        ]

    def telemetry_count(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT source, count(*) FROM telemetry GROUP BY source")
        return dict(rows.fetchall())


def open_database(url: str | None = None) -> Database | None:
    """Connect if a database is set up. Without one, the API runs from memory instead."""
    url = url or os.getenv("DATABASE_URL")
    if not url:
        return None
    try:
        return Database(url)
    except psycopg.Error as error:
        print(f"Database unavailable, so changes won't survive a restart: {error}")
        return None


def load_excel_telemetry(database: Database, store) -> int:
    """Copy the Excel pack's telemetry into the database, marked with its source."""
    rows = [
        (point.timestamp + "+00:00", point.asset_id, point.tag, EXCEL_SOURCE, point.metrics)
        for points in store.telemetry_by_id.values()
        for point in points
    ]
    database.add_telemetry(rows)
    return len(rows)


def main() -> None:
    from app.copilot.store import DataStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()
    database = Database(args.url)
    load_excel_telemetry(database, DataStore.load())
    print(json.dumps(database.telemetry_count()))


if __name__ == "__main__":
    main()
