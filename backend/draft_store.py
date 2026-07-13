"""In-memory create-flow drafts keyed by user_id (survives lost client pending)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_DRAFTS: dict[str, dict[str, Any]] = {}


def get_draft(user_id: str) -> dict[str, Any] | None:
    draft = _DRAFTS.get(user_id)
    return deepcopy(draft) if draft else None


def save_draft(user_id: str, event: dict[str, Any] | None) -> None:
    if not event:
        clear_draft(user_id)
        return
    _DRAFTS[user_id] = deepcopy(event)


def clear_draft(user_id: str) -> None:
    _DRAFTS.pop(user_id, None)


def merge_client_pending(
    user_id: str,
    client_pending: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Prefer non-empty client fields; fill gaps from server-stored draft."""
    from backend.validators import merge_pending_event

    server = get_draft(user_id)
    if not server and not client_pending:
        return None
    if not server:
        return dict(client_pending or {})
    if not client_pending:
        return server
    # Client non-null values win; server fills gaps
    return merge_pending_event(server, client_pending)
