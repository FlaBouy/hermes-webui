"""Durable synchronous review turns, stored with their owner transcript row.

Call run_sync_review with the existing per-session execution lock held. Live
ownership is process-local; persisted pending rows alone never imply a worker
survived a restart. Interrupted requests are not automatically re-executed.
"""
import copy
import threading
import time
import uuid

_LIVE = set()
_LOCK = threading.Lock()


class ReviewTurnError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def sync_turn_status(session):
    if getattr(session, "is_streaming", False) or getattr(session, "active_stream_id", None):
        return None  # Native governed stream/journal retains ownership.
    owners = [m for m in (getattr(session, "messages", None) or [])
              if isinstance(m, dict) and m.get("review_turn_state")]
    if not owners:
        return None
    owner = owners[-1]
    # A later governed owner row belongs to the native stream/journal instead.
    rows = session.messages
    index = next(i for i in range(len(rows) - 1, -1, -1) if rows[i] is owner)
    if any(m.get("role") == "user" for m in rows[index + 1:] if isinstance(m, dict)):
        return None
    state = owner["review_turn_state"]
    with _LOCK:
        live = (session.session_id, owner["review_request_id"]) in _LIVE
    if state == "pending" and not live:
        state = "interrupted"
    text = {
        "pending": "Smedley is working… This calculation or reply cannot be cancelled in flight.",
        "failed": "Smedley's reply failed. Your request was saved. Send again to start a new attempt.",
        "interrupted": "Smedley's reply was interrupted. Your request was saved; it was not automatically rerun. Send again to retry.",
    }.get(state, "")
    return {"request_id": owner["review_request_id"], "status": state,
            "status_message": text, "is_streaming": state == "pending",
            "cancel_stream_id": None, "cancel_recommended": False}


def run_sync_review(session, *, message, request_id, lane, execute, metadata=None):
    """Accept once, save before execute, then durably settle exactly one reply."""
    request_id = request_id or uuid.uuid4().hex
    rows = session.messages
    existing = next((m for m in rows if m.get("role") == "user"
                     and m.get("review_request_id") == request_id), None)
    if existing is not None:
        if existing.get("content") != "Owner message: " + message:
            raise ReviewTurnError("request_id already belongs to a different message", 409)
        if existing.get("review_turn_state") == "completed":
            return copy.deepcopy(existing["review_result"])
        raise ReviewTurnError("Previous request is pending, failed, or interrupted; inspect the saved dialog before starting a new request.", 409)
    owner = {"role": "user", "content": "Owner message: " + message,
             "timestamp": time.time(), "source": "project_review",
             "review_request_id": request_id, "review_turn_state": "pending",
             "review_lane": lane}
    key = (session.session_id, request_id)
    with _LOCK:
        _LIVE.add(key)
    rows.append(owner)
    try:
        try:
            session.save()
        except Exception as exc:
            rows.remove(owner)
            raise ReviewTurnError("Request could not be saved; execution was not started.") from exc
        try:
            result = execute()
            reply = str(result.get("reply") or "").strip()
            if not reply:
                raise ValueError("empty review reply")
        except Exception as exc:
            owner["review_turn_state"] = "failed"
            session.save()
            raise ReviewTurnError("Smedley dialogue reply failed; your request was saved. Heavy extraction was not started.") from exc
        assistant = {"role": "assistant", "content": reply, "timestamp": time.time(),
                     "assistant_identity": "smedley", "review_request_id": request_id,
                     "project_review_fast_route": lane == "fast",
                     "project_review_status_route": lane == "status",
                     "electrical_inputs": result.get("electrical_inputs"),
                     "electrical_result": result.get("electrical_result"),
                     "voice_model": str(result.get("model") or ""), **(metadata or {})}
        rows.append(assistant)
        owner["review_turn_state"] = "completed"
        owner["review_result"] = copy.deepcopy(result)
        try:
            session.save()
        except Exception as exc:
            # Never serve a memory-only success on a retry after failed save.
            rows.remove(assistant)
            owner.pop("review_result", None)
            owner["review_turn_state"] = "failed"
            raise ReviewTurnError("Reply could not be saved. Inspect the saved request before retrying.") from exc
        return result
    finally:
        with _LOCK:
            _LIVE.discard(key)
