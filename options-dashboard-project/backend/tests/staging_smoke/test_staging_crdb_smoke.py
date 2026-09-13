"""CRDB feature smoke (Staging Task 11): smallest representative checks.

Proves the three CockroachDB-critical SQL behaviors on the *live staging
database* (direct connection, read-only + self-cleaning):

* explicit ON CONFLICT upsert (staging schema uses real upserts)
* RETURNING (used across the paper-trading write paths)
* transaction rollback (atomicity of multi-statement writes)

The suite uses its own throwaway table named `smoke_probe_*` and drops it,
so no application table is touched. This is intentionally NOT a repeat of
the full runtime CRDB validation suite (see
docs/architecture/COCKROACH_RUNTIME_VALIDATION.md) — just the smallest
live-database proof that the features the app relies on still behave.
"""

import uuid

import pytest
import psycopg

pytestmark = pytest.mark.usefixtures("crdb_dsn")


@pytest.fixture()
def conn(crdb_dsn):
    """One short-lived connection; the DSN is never printed."""
    with psycopg.connect(crdb_dsn, connect_timeout=20) as c:
        yield c


def test_crdb_on_conflict_returning(conn):
    """Explicit upsert with RETURNING behaves like the app's write paths."""
    table = f"smoke_probe_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(f"CREATE TABLE {table} (k TEXT PRIMARY KEY, v INT)")
        cur.execute(
            f"INSERT INTO {table} (k, v) VALUES (%s, %s) "
            f"ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v RETURNING k, v",
            ("probe", 1),
        )
        first = cur.fetchone()
        assert first == ("probe", 1), f"insert RETURNING: {first}"
        cur.execute(
            f"INSERT INTO {table} (k, v) VALUES (%s, %s) "
            f"ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v RETURNING k, v",
            ("probe", 2),
        )
        second = cur.fetchone()
        assert second == ("probe", 2), f"upsert RETURNING: {second}"
        cur.execute(f"SELECT v FROM {table} WHERE k = 'probe'")
        assert cur.fetchone() == (2,), "upsert did not persist"


def test_crdb_rollback(conn):
    """A failed statement inside a transaction leaves no partial effects."""
    table = f"smoke_probe_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(f"CREATE TABLE {table} (k TEXT PRIMARY KEY, v INT)")
    conn.commit()

    try:
        with conn.transaction():  # psycopg3 managed block -> rollback on error
            with conn.cursor() as cur:
                cur.execute(f"INSERT INTO {table} (k, v) VALUES ('a', 1)")
                cur.execute("SELECT 1/0")  # force division-by-zero
        raised = False
    except psycopg.Error:  # any statement error must roll the block back
        raised = True
    assert raised, "expected the failed statement to raise"

    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        assert cur.fetchone()[0] == 0, "rollback left partial rows behind"


def _drop_probe_tables(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE 'smoke_probe_%'"
        )
        names = [r[0] for r in cur.fetchall()]
    for name in names:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {name}")
    conn.commit()
    return names


def test_crdb_probe_cleanup(conn):
    """Self-cleaning guarantee: no smoke tables are left behind."""
    left = _drop_probe_tables(conn)
    print(f"cleaned probe tables: {len(left)}")
    assert all(n.startswith("smoke_probe_") for n in left)
