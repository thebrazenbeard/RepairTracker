from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from .model import EventLog, RepairEvent, canonical_json


class StaleHeadError(RuntimeError):
    pass


class LedgerIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AppendReceipt:
    repair_id: str
    event_id: str
    event_digest: str
    generation: int


class SQLiteEventStore:
    """Durable V0 repair-event ledger.

    Writes are serialized with BEGIN IMMEDIATE. Every append must name the
    exact currently observed predecessor digest, so a stale worker cannot
    silently append onto a newer repair history.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS repair_events (
                    event_id TEXT PRIMARY KEY,
                    repair_id TEXT NOT NULL,
                    generation INTEGER NOT NULL CHECK (generation > 0),
                    predecessor_digest TEXT,
                    event_digest TEXT NOT NULL UNIQUE,
                    body_json TEXT NOT NULL,
                    UNIQUE (repair_id, generation)
                );

                CREATE TABLE IF NOT EXISTS repair_heads (
                    repair_id TEXT PRIMARY KEY,
                    head_digest TEXT NOT NULL,
                    generation INTEGER NOT NULL CHECK (generation > 0)
                );
                """
            )

    def head(self, repair_id: str) -> tuple[str | None, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT head_digest, generation FROM repair_heads WHERE repair_id = ?",
                (repair_id,),
            ).fetchone()
        if row is None:
            return None, 0
        return str(row["head_digest"]), int(row["generation"])

    def append(self, event: RepairEvent) -> AppendReceipt:
        body_json = canonical_json(event.body())
        digest = event.digest
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT head_digest, generation FROM repair_heads WHERE repair_id = ?",
                (event.repair_id,),
            ).fetchone()

            current_head = None if row is None else str(row["head_digest"])
            current_generation = 0 if row is None else int(row["generation"])

            if event.predecessor_digest != current_head:
                raise StaleHeadError(
                    f"stale repair head for {event.repair_id}: "
                    f"expected predecessor {current_head!r}, "
                    f"event carries {event.predecessor_digest!r}"
                )

            generation = current_generation + 1
            connection.execute(
                """
                INSERT INTO repair_events (
                    event_id, repair_id, generation, predecessor_digest,
                    event_digest, body_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.repair_id,
                    generation,
                    event.predecessor_digest,
                    digest,
                    body_json,
                ),
            )

            if row is None:
                connection.execute(
                    """
                    INSERT INTO repair_heads (repair_id, head_digest, generation)
                    VALUES (?, ?, ?)
                    """,
                    (event.repair_id, digest, generation),
                )
            else:
                result = connection.execute(
                    """
                    UPDATE repair_heads
                    SET head_digest = ?, generation = ?
                    WHERE repair_id = ? AND generation = ? AND head_digest = ?
                    """,
                    (
                        digest,
                        generation,
                        event.repair_id,
                        current_generation,
                        current_head,
                    ),
                )
                if result.rowcount != 1:
                    raise StaleHeadError(
                        f"repair head moved while appending {event.event_id}"
                    )

            connection.commit()

            readback = connection.execute(
                """
                SELECT event_digest, body_json, generation
                FROM repair_events
                WHERE event_id = ?
                """,
                (event.event_id,),
            ).fetchone()
            if (
                readback is None
                or str(readback["event_digest"]) != digest
                or str(readback["body_json"]) != body_json
                or int(readback["generation"]) != generation
            ):
                raise LedgerIntegrityError(
                    f"post-write readback mismatch for {event.event_id}"
                )

            return AppendReceipt(
                repair_id=event.repair_id,
                event_id=event.event_id,
                event_digest=digest,
                generation=generation,
            )
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def load(self, repair_id: str) -> EventLog:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT generation, event_digest, body_json
                FROM repair_events
                WHERE repair_id = ?
                ORDER BY generation
                """,
                (repair_id,),
            ).fetchall()
            head_row = connection.execute(
                "SELECT head_digest, generation FROM repair_heads WHERE repair_id = ?",
                (repair_id,),
            ).fetchone()

        events: list[RepairEvent] = []
        for expected_generation, row in enumerate(rows, start=1):
            if int(row["generation"]) != expected_generation:
                raise LedgerIntegrityError(
                    f"non-contiguous generation for {repair_id}: "
                    f"expected {expected_generation}, got {row['generation']}"
                )
            body = json.loads(str(row["body_json"]))
            event = RepairEvent.from_body(body)
            if event.digest != str(row["event_digest"]):
                raise LedgerIntegrityError(
                    f"event digest mismatch for {event.event_id}"
                )
            events.append(event)

        log = EventLog(events)

        if not events:
            if head_row is not None:
                raise LedgerIntegrityError(
                    f"head exists without events for {repair_id}"
                )
            return log

        if head_row is None:
            raise LedgerIntegrityError(f"events exist without head for {repair_id}")
        if int(head_row["generation"]) != len(events):
            raise LedgerIntegrityError(
                f"head generation mismatch for {repair_id}"
            )
        if str(head_row["head_digest"]) != log.head_digest:
            raise LedgerIntegrityError(f"head digest mismatch for {repair_id}")

        return log
