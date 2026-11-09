"""Small smoke test; run from original project root after copying receipt_feature/."""
from io import BytesIO
from pathlib import Path
import tempfile

from core.db import Database
from receipt_feature.service import attach_receipt, list_receipts, read_receipt, delete_receipt

class Upload:
    name = "test-receipt.pdf"
    def getvalue(self):
        return b"%PDF-1.4\n% test receipt\n%%EOF"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(sqlite_path=Path(tmp) / "test.db")
        db.init_schema()
        migration = Path(__file__).parent / "sql" / "receipt_schema_sqlite.sql"
        with db.connection() as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))
        family_id = db.insert("INSERT INTO families (name, invite_code) VALUES (?, ?)", ("Test family", "ABC123"))
        user_id = db.insert("INSERT INTO users (family_id, full_name, email, password_hash) VALUES (?, ?, ?, ?)", (family_id, "Test User", "test@example.com", "hash"))
        category_id = db.insert("INSERT INTO categories (family_id, name, kind) VALUES (?, ?, ?)", (family_id, "Food", "expense"))
        tx_id = db.insert("INSERT INTO transactions (family_id, user_id, category_id, kind, amount_cents, occurred_on) VALUES (?, ?, ?, ?, ?, ?)", (family_id, user_id, category_id, "expense", 125000, "2026-11-09"))
        actor = {"id": user_id, "family_id": family_id, "role": "member"}
        storage = Path(tmp) / "receipts"
        receipt_id = attach_receipt(db, actor, tx_id, Upload(), storage)
        assert len(list_receipts(db, actor, tx_id)) == 1
        name, mime, content = read_receipt(db, actor, receipt_id, storage)
        assert name == "test-receipt.pdf" and mime == "application/pdf" and content.startswith(b"%PDF-")
        delete_receipt(db, actor, receipt_id, storage)
        assert list_receipts(db, actor, tx_id) == []
        print("PASS: attach, list, read and delete receipt")

if __name__ == "__main__":
    main()
