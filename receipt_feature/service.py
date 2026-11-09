"""Receipt attachment helpers for Team 38 Family Budget Tracker.

Designed for the project's core.db Database wrapper (SQLite and PostgreSQL).
Files are stored on disk; only safe metadata is stored in the database.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import re

MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {
    ".jpg": ("image/jpeg",),
    ".jpeg": ("image/jpeg",),
    ".png": ("image/png",),
    ".pdf": ("application/pdf",),
}

class ReceiptError(ValueError):
    pass


def _check_file(filename: str, data: bytes) -> tuple[str, str]:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        raise ReceiptError("Only JPG, PNG and PDF receipts are allowed.")
    if not data:
        raise ReceiptError("The selected file is empty.")
    if len(data) > MAX_BYTES:
        raise ReceiptError("The receipt must be 10 MB or smaller.")
    # Check file signatures instead of trusting the browser-provided MIME type.
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        raise ReceiptError("This file does not look like a valid PDF.")
    if ext in (".jpg", ".jpeg") and not data.startswith(b"\xff\xd8\xff"):
        raise ReceiptError("This file does not look like a valid JPEG image.")
    if ext == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ReceiptError("This file does not look like a valid PNG image.")
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf"}[ext]
    return ext, mime


def _transaction_for_actor(db, actor: dict, transaction_id: int) -> dict:
    row = db.query_one(
        "SELECT id, family_id, user_id, kind FROM transactions WHERE id = ? AND family_id = ?",
        (int(transaction_id), int(actor["family_id"])),
    )
    if not row:
        raise ReceiptError("Transaction not found in your family workspace.")
    if row["kind"] != "expense":
        raise ReceiptError("A receipt can only be attached to an expense.")
    if actor.get("role") != "admin" and int(row["user_id"]) != int(actor["id"]):
        raise ReceiptError("You can attach a receipt only to your own expense.")
    return row


def attach_receipt(db, actor: dict, transaction_id: int, uploaded_file, storage_dir: str | Path = "data/receipts") -> int:
    """Save a Streamlit UploadedFile (or file-like object) to an expense."""
    _transaction_for_actor(db, actor, transaction_id)
    filename = Path(getattr(uploaded_file, "name", "receipt")).name
    data = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    data = bytes(data)
    ext, mime = _check_file(filename, data)
    stored_name = f"{uuid4().hex}{ext}"
    folder = Path(storage_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / stored_name
    target.write_bytes(data)
    try:
        receipt_id = db.insert(
            "INSERT INTO receipts (transaction_id, family_id, uploaded_by, original_name, stored_name, content_type, file_size) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(transaction_id), int(actor["family_id"]), int(actor["id"]), filename[:255], stored_name, mime, len(data)),
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return receipt_id


def list_receipts(db, actor: dict, transaction_id: int) -> list[dict]:
    _transaction_for_actor(db, actor, transaction_id)
    return db.query(
        "SELECT id, transaction_id, original_name, content_type, file_size, created_at "
        "FROM receipts WHERE transaction_id = ? AND family_id = ? ORDER BY id DESC",
        (int(transaction_id), int(actor["family_id"])),
    )


def read_receipt(db, actor: dict, receipt_id: int, storage_dir: str | Path = "data/receipts") -> tuple[str, str, bytes]:
    row = db.query_one(
        "SELECT r.transaction_id, r.original_name, r.stored_name, r.content_type "
        "FROM receipts r JOIN transactions t ON t.id = r.transaction_id AND t.family_id = r.family_id "
        "WHERE r.id = ? AND r.family_id = ?",
        (int(receipt_id), int(actor["family_id"])),
    )
    if not row:
        raise ReceiptError("Receipt not found.")
    _transaction_for_actor(db, actor, row["transaction_id"])
    path = Path(storage_dir) / Path(row["stored_name"]).name
    if not path.is_file():
        raise ReceiptError("Receipt file is missing from storage.")
    return row["original_name"], row["content_type"], path.read_bytes()


def delete_receipt(db, actor: dict, receipt_id: int, storage_dir: str | Path = "data/receipts") -> None:
    row = db.query_one(
        "SELECT id, transaction_id, stored_name FROM receipts WHERE id = ? AND family_id = ?",
        (int(receipt_id), int(actor["family_id"])),
    )
    if not row:
        raise ReceiptError("Receipt not found.")
    _transaction_for_actor(db, actor, row["transaction_id"])
    db.execute("DELETE FROM receipts WHERE id = ? AND family_id = ?", (int(receipt_id), int(actor["family_id"])))
    (Path(storage_dir) / Path(row["stored_name"]).name).unlink(missing_ok=True)
