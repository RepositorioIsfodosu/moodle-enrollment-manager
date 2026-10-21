import pytest
from pydantic import ValidationError

from app.models import JOB_STATES
from app.schemas.jobs import BatchConfiguration
from app.services.job_states import TRANSITIONS, transition


def test_machine_covers_all_persisted_states():
    assert set(TRANSITIONS) == set(JOB_STATES)
    assert all(target in JOB_STATES for targets in TRANSITIONS.values() for target in targets)


@pytest.mark.parametrize("terminal", ["completed", "completed_with_errors", "cancelled", "failed"])
def test_terminal_cannot_restart(terminal):
    with pytest.raises(ValueError):
        transition(terminal, "queued")


def test_cooperative_pause_and_cancel():
    assert transition("running", "pausing") == "pausing"
    assert transition("pausing", "paused") == "paused"
    assert transition("paused", "queued") == "queued"
    assert transition("running", "cancelling") == "cancelling"
    assert transition("cancelling", "cancelled") == "cancelled"
    with pytest.raises(ValueError):
        transition("running", "cancelled")


@pytest.mark.parametrize(
    "configuration",
    [
        {"batch_size": 0},
        {"batch_size": 51},
        {"max_retries": -1},
        {"max_retries": 6},
        {"timeout_seconds": 121},
        {"unknown": 1},
    ],
)
def test_bounded_configuration(configuration):
    with pytest.raises(ValidationError):
        BatchConfiguration(**configuration)
