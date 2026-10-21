"""Explicit job state machine; terminal jobs cannot be restarted implicitly."""

TRANSITIONS = {
    "draft": {"validating", "ready", "cancelled"},
    "validating": {"ready", "failed", "cancelling"},
    "ready": {"queued", "cancelled"},
    "queued": {"running", "paused", "cancelled"},
    "running": {"pausing", "cancelling", "completed", "completed_with_errors", "failed"},
    "pausing": {"paused", "cancelling", "failed"},
    "paused": {"queued", "cancelled"},
    "cancelling": {"cancelled", "failed"},
    "completed": set(),
    "completed_with_errors": set(),
    "cancelled": set(),
    "failed": set(),
}


def transition(current: str, target: str) -> str:
    if target not in TRANSITIONS.get(current, set()):
        raise ValueError("Transición de estado no permitida")
    return target
