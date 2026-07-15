"""Firebase Admin SDK — Firestore for Filofax reminders."""

from __future__ import annotations

import json
import os
from typing import Any

_app: Any = None


def is_enabled() -> bool:
    """True when project id, credentials, and firebase_admin package are available."""
    project = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    if not project:
        return False
    try:
        import firebase_admin  # noqa: F401
    except ImportError:
        return False
    json_raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if json_raw:
        try:
            json.loads(json_raw)
            return True
        except json.JSONDecodeError:
            return False
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    return bool(path and os.path.isfile(path))


def _load_credentials():
    from firebase_admin import credentials

    json_raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if json_raw:
        return credentials.Certificate(json.loads(json_raw))

    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and os.path.isfile(path):
        return credentials.Certificate(path)

    raise RuntimeError(
        "Firebase credentials missing. Set GOOGLE_APPLICATION_CREDENTIALS "
        "or FIREBASE_SERVICE_ACCOUNT_JSON."
    )


def get_app():
    global _app
    if _app is not None:
        return _app
    if not is_enabled():
        raise RuntimeError("Firebase is not configured.")

    import firebase_admin

    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    options: dict[str, Any] = {}
    if project_id:
        options["projectId"] = project_id
    bucket = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
    if bucket:
        options["storageBucket"] = bucket

    _app = firebase_admin.initialize_app(_load_credentials(), options or None)
    return _app


def get_firestore():
    from firebase_admin import firestore

    get_app()
    database_id = os.getenv("FIRESTORE_DATABASE_ID", "(default)").strip() or "(default)"
    return firestore.client(database_id=database_id)


def check_firebase() -> dict[str, Any]:
    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    collection = os.getenv("FIRESTORE_REMINDERS_COLLECTION", "Reminders")
    try:
        import firebase_admin  # noqa: F401
    except ImportError:
        return {
            "ok": False,
            "enabled": False,
            "project_id": project_id or None,
            "collection": collection,
            "error": "firebase-admin not installed — run: pip install firebase-admin",
        }
    if not is_enabled():
        return {
            "ok": False,
            "enabled": False,
            "project_id": project_id or None,
            "collection": collection,
            "error": "Firebase env vars not set — using SQLite fallback",
        }
    try:
        db = get_firestore()
        db.collection("_health").document("filofax").get()
        return {
            "ok": True,
            "enabled": True,
            "project_id": project_id,
            "collection": collection,
        }
    except Exception as exc:
        return {
            "ok": False,
            "enabled": True,
            "project_id": project_id,
            "collection": collection,
            "error": str(exc),
        }
