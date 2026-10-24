"""SQLite schema. The integrity rules that matter live HERE as triggers, so they hold even if application code is wrong:

* audit is append-only (UPDATE / DELETE abort)
* items.state can only change if the audit row written immediately before it records exactly that move
* vendor bank details can only change right after an applied 'bank_change' audit row for that vendor
* a payment row can only exist for an item with an applied 'post' audit row; one payment per item
* payments / bank history are append-only too
"""
import os, sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
  vendor_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT NOT NULL,
  typical_amount REAL NOT NULL,
  bank_name TEXT, bank_routing TEXT, bank_account TEXT,
  phone TEXT, split TEXT
);
CREATE TABLE IF NOT EXISTS payment_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_id TEXT NOT NULL, voucher TEXT, po TEXT, fiscal_year INTEGER, po_date TEXT,
  amount REAL, name_as_paid TEXT, department TEXT
);
CREATE INDEX IF NOT EXISTS ix_hist_vendor ON payment_history(vendor_id);
-- agent-readable context loaded from dataset v2 (never contains truth or provenance)
CREATE TABLE IF NOT EXISTS vendor_profile (vendor_id TEXT PRIMARY KEY, profile TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS email_history (id TEXT PRIMARY KEY, vendor_id TEXT NOT NULL, sent_at TEXT, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_emailhist_vendor ON email_history(vendor_id);
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN ('NEW','PROPOSED','NEEDS_INFO','APPROVED','REJECTED','POSTED')),
  vendor_id TEXT NOT NULL REFERENCES vendors(vendor_id),
  email TEXT NOT NULL, claim TEXT NOT NULL,
  verdict TEXT, evidence TEXT NOT NULL DEFAULT '[]',
  question TEXT, answer TEXT, answered_by TEXT, approved_by TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_items_state ON items(state);
-- ground truth for evaluation only; never exposed by the API or to agents
CREATE TABLE IF NOT EXISTS truth (item_id TEXT PRIMARY KEY, split TEXT, truth TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  item_id TEXT, vendor_id TEXT,
  actor TEXT NOT NULL, actor_id TEXT,
  action TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('applied','denied','error')),
  deny_code TEXT,
  from_state TEXT, to_state TEXT,
  reason TEXT, evidence TEXT, before TEXT, after TEXT,
  prev_hash TEXT NOT NULL, row_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_item ON audit(item_id);
CREATE INDEX IF NOT EXISTS ix_audit_vendor ON audit(vendor_id);
CREATE TABLE IF NOT EXISTS payments (
  payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id TEXT NOT NULL UNIQUE, vendor_id TEXT NOT NULL,
  amount REAL NOT NULL, bank_routing TEXT, bank_account TEXT,
  rail TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, released_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS items_insert_needs_audit BEFORE INSERT ON items
WHEN NOT EXISTS (SELECT 1 FROM audit WHERE id=(SELECT MAX(id) FROM audit)
                 AND item_id=NEW.id AND action='ingest' AND outcome='applied')
BEGIN SELECT RAISE(ABORT, 'item created without audit row'); END;

CREATE TRIGGER IF NOT EXISTS items_state_needs_audit BEFORE UPDATE OF state ON items
WHEN NEW.state != OLD.state AND NOT EXISTS (
  SELECT 1 FROM audit WHERE id=(SELECT MAX(id) FROM audit)
  AND item_id=OLD.id AND outcome='applied' AND from_state IS OLD.state AND to_state=NEW.state)
BEGIN SELECT RAISE(ABORT, 'state change without matching audit row'); END;

CREATE TRIGGER IF NOT EXISTS items_no_delete BEFORE DELETE ON items
BEGIN SELECT RAISE(ABORT, 'items cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS vendors_bank_needs_audit BEFORE UPDATE ON vendors
WHEN (NEW.bank_routing IS NOT OLD.bank_routing OR NEW.bank_account IS NOT OLD.bank_account OR NEW.bank_name IS NOT OLD.bank_name)
 AND NOT EXISTS (SELECT 1 FROM audit WHERE id=(SELECT MAX(id) FROM audit)
                 AND vendor_id=OLD.vendor_id AND action='bank_change' AND outcome='applied')
BEGIN SELECT RAISE(ABORT, 'bank details changed without audit row'); END;
CREATE TRIGGER IF NOT EXISTS vendors_no_delete BEFORE DELETE ON vendors
BEGIN SELECT RAISE(ABORT, 'vendors cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS payments_needs_post BEFORE INSERT ON payments
WHEN NOT EXISTS (SELECT 1 FROM audit WHERE item_id=NEW.item_id AND action='post' AND outcome='applied')
BEGIN SELECT RAISE(ABORT, 'payment without applied post'); END;
CREATE TRIGGER IF NOT EXISTS payments_no_update BEFORE UPDATE ON payments
BEGIN SELECT RAISE(ABORT, 'payments are append-only'); END;
CREATE TRIGGER IF NOT EXISTS payments_no_delete BEFORE DELETE ON payments
BEGIN SELECT RAISE(ABORT, 'payments are append-only'); END;
"""


def connect(path):
    """New connection per unit of work. Autocommit mode: core.transition manages BEGIN/COMMIT itself."""
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # WAL needs shared memory and does not work reliably on network file systems; on an Azure Files (SMB) mount set
    # VOUCH_SQLITE_JOURNAL=DELETE. Local disk keeps the WAL default.
    mode = os.environ.get("VOUCH_SQLITE_JOURNAL", "WAL").upper()
    if mode not in ("WAL", "DELETE", "TRUNCATE"):
        raise ValueError("VOUCH_SQLITE_JOURNAL must be WAL, DELETE or TRUNCATE")
    conn.execute(f"PRAGMA journal_mode={mode}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(path):
    conn = connect(path)
    conn.executescript(SCHEMA)
    return conn
