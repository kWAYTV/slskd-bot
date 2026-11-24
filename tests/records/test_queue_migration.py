"""A database written before queue items stored their pick gains the column on open."""

import sqlite3

from slskd_importer.queue.store import QueueRepository
from slskd_importer.records.database import Database
from slskd_importer.sources.tracklist import Entry


def test_v8_queue_items_gain_the_pick_column(tmp_path):
    path = str(tmp_path / "old.db")
    Database(path).close()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE queue_items DROP COLUMN pick")
    conn.execute("PRAGMA user_version = 8")
    conn.commit()
    conn.close()

    store = QueueRepository(Database(path))
    batch = store.create_batch(1, 1, "Set", "list", [Entry(query="A - B")])
    assert store.items(batch.id)[0].pick == ""
