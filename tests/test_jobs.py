"""Tests des Job-Systems.

Geprueft wird, was Spezifikation 07 und 08 fordern: Jobs laufen im Hintergrund,
lassen sich abbrechen, melden Fehler statt sie zu verschlucken, und ein
ueberholtes Ergebnis darf die aktuelle Anzeige nicht ueberschreiben.
"""

from __future__ import annotations

import time

import pytest

from app.core.cancellation import CancellationToken
from app.core.errors import Severity
from app.core.requests import RequestGate
from app.jobs.job import FunctionJob, Job, JobState
from app.jobs.job_manager import JobManager, PoolConfig

pytestmark = pytest.mark.usefixtures("qt_app")


def _drain(app, manager: JobManager, timeout_s: float = 5.0) -> None:
    """Wartet auf alle Jobs und stellt die Signale zu.

    processEvents ist noetig, weil die Signale als QueuedConnection zugestellt
    werden - ohne laufende Ereignisschleife kommen sie nie an.
    """
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        app.processEvents()
        if manager.active_count == 0:
            break
        time.sleep(0.005)
    manager.wait_for_done(int(timeout_s * 1000))
    app.processEvents()


@pytest.fixture
def manager(reporter):
    return JobManager(reporter, PoolConfig(interactive=2, cpu=2))


def test_pools_are_separated(manager):
    sizes = manager.pool_sizes()
    assert set(sizes) == {"interactive", "cpu"}
    assert all(v >= 1 for v in sizes.values())


def test_job_runs_and_delivers_its_result(qt_app, manager, reporter):
    gate = RequestGate()
    ticket = gate.issue("test")
    received: list = []

    job = FunctionJob(reporter, ticket, lambda token, progress: 6 * 7, title="Rechnen")
    job.signals.result.connect(lambda job_id, t, payload: received.append(payload))
    manager.submit(job)
    _drain(qt_app, manager)

    assert received == [42]
    assert job.state is JobState.DONE
    assert manager.counters()["fertig"] == 1


def test_progress_reaches_the_listener(qt_app, manager, reporter):
    gate = RequestGate()
    steps: list[tuple[int, int]] = []

    def work(token, progress):
        for i in range(1, 4):
            progress(i, 3, "Schritt " + str(i))
        return "fertig"

    job = FunctionJob(reporter, gate.issue("test"), work)
    job.signals.progress.connect(lambda job_id, c, t, text: steps.append((c, t)))
    manager.submit(job)
    _drain(qt_app, manager)

    assert steps == [(1, 3), (2, 3), (3, 3)]


def test_exception_is_reported_and_signalled(qt_app, manager, reporter):
    gate = RequestGate()
    failures: list[str] = []

    def boom(token, progress):
        raise ValueError("Paket passt nicht")

    job = FunctionJob(reporter, gate.issue("pallet"), boom, title="Palettierung")
    job.signals.failed.connect(lambda job_id, t, message: failures.append(message))
    manager.submit(job)
    _drain(qt_app, manager)

    assert failures == ["Paket passt nicht"]
    assert job.state is JobState.FAILED
    assert reporter.problems.count(Severity.ERROR) == 1
    assert manager.counters()["fehlgeschlagen"] == 1


def test_failing_job_does_not_stop_the_pool(qt_app, manager, reporter):
    """Spezifikation 09: ein Fehler darf den Worker-Pool nicht toeten."""
    gate = RequestGate()
    results: list = []

    def boom(token, progress):
        raise RuntimeError("kaputt")

    manager.submit(FunctionJob(reporter, gate.issue("a"), boom), group="a")
    _drain(qt_app, manager)

    good = FunctionJob(reporter, gate.issue("b"), lambda token, progress: "geht noch")
    good.signals.result.connect(lambda job_id, t, payload: results.append(payload))
    manager.submit(good, group="b")
    _drain(qt_app, manager)

    assert results == ["geht noch"]


def test_cancelled_job_delivers_no_result(qt_app, manager, reporter):
    gate = RequestGate()
    results: list = []
    token = CancellationToken()

    def slow(token, progress):
        for _ in range(200):
            token.raise_if_cancelled()
            time.sleep(0.005)
        return "sollte nie ankommen"

    job = FunctionJob(reporter, gate.issue("test"), slow, token=token)
    job.signals.result.connect(lambda job_id, t, payload: results.append(payload))
    manager.submit(job)
    time.sleep(0.05)
    token.cancel()
    _drain(qt_app, manager)

    assert results == []
    assert job.state is JobState.CANCELLED
    assert manager.counters()["abgebrochen"] == 1


def test_job_cancelled_before_start_does_not_run(qt_app, manager, reporter):
    gate = RequestGate()
    ran: list[int] = []
    token = CancellationToken()
    token.cancel()

    job = FunctionJob(reporter, gate.issue("test"), lambda token, progress: ran.append(1), token=token)
    manager.submit(job)
    _drain(qt_app, manager)

    assert ran == []
    assert job.state is JobState.CANCELLED


def test_new_request_cancels_the_previous_one_of_the_same_group(qt_app, manager, reporter):
    gate = RequestGate()
    results: list = []

    def slow(token, progress):
        for _ in range(200):
            token.raise_if_cancelled()
            time.sleep(0.005)
        return "alt"

    first = FunctionJob(reporter, gate.issue("pallet"), slow)
    first.signals.result.connect(lambda job_id, t, payload: results.append(payload))
    manager.submit(first, group="pallet")
    time.sleep(0.05)

    second = FunctionJob(reporter, gate.issue("pallet"), lambda token, progress: "neu")
    second.signals.result.connect(lambda job_id, t, payload: results.append(payload))
    manager.submit(second, group="pallet")
    _drain(qt_app, manager)

    assert results == ["neu"]
    assert first.state is JobState.CANCELLED


def test_stale_result_is_discarded_by_the_gate(qt_app, manager, reporter):
    """Der Kern von Spezifikation 08, hier im Zusammenspiel mit echten Jobs.

    Der langsame Job wird bewusst NICHT abgebrochen - er laeuft zu Ende und
    liefert ein Ergebnis. Die Torpruefung muss es trotzdem verwerfen, weil
    inzwischen eine neuere Anfrage gestellt wurde.
    """
    gate = RequestGate()
    shown: list = []

    def deliver(job_id, ticket, payload):
        if gate.accept(ticket):
            shown.append(payload)

    slow_ticket = gate.issue("pallet")
    slow = FunctionJob(reporter, slow_ticket, lambda token, progress: (time.sleep(0.15), "alt")[1])
    slow.signals.result.connect(deliver)
    manager.submit(slow, group="pallet", cancel_group=False)

    fast_ticket = gate.issue("pallet")
    fast = FunctionJob(reporter, fast_ticket, lambda token, progress: "neu")
    fast.signals.result.connect(deliver)
    manager.submit(fast, group="pallet", cancel_group=False)

    _drain(qt_app, manager)

    assert shown == ["neu"], "Das ueberholte Ergebnis darf die Anzeige nicht erreichen"


def test_cancel_group_leaves_other_groups_alone(qt_app, manager, reporter):
    gate = RequestGate()
    results: list = []

    def slow(token, progress):
        for _ in range(100):
            token.raise_if_cancelled()
            time.sleep(0.005)
        return "vakuum fertig"

    vacuum = FunctionJob(reporter, gate.issue("vacuum"), slow)
    vacuum.signals.result.connect(lambda job_id, t, payload: results.append(payload))
    manager.submit(vacuum, group="vacuum")

    manager.cancel_group("pallet")
    _drain(qt_app, manager)

    assert results == ["vakuum fertig"]


def test_activity_signal_returns_to_idle(qt_app, manager, reporter):
    gate = RequestGate()
    activity: list[int] = []
    manager.activity_changed.connect(lambda count, text: activity.append(count))

    manager.submit(FunctionJob(reporter, gate.issue("test"), lambda token, progress: 1))
    _drain(qt_app, manager)

    assert activity, "Es muss mindestens eine Aktivitaetsmeldung geben"
    assert activity[-1] == 0


def test_job_ids_are_unique_across_threads(reporter):
    gate = RequestGate()
    jobs = [FunctionJob(reporter, gate.issue("test"), lambda token, progress: None) for _ in range(50)]
    assert len({job.job_id for job in jobs}) == 50


def test_subclass_contract(qt_app, manager, reporter):
    """Eigene Jobklassen sind moeglich, nicht nur FunctionJob."""

    class CountingJob(Job):
        title = "Zaehlen"
        pool = "interactive"

        def run_job(self):
            return sum(range(10))

    gate = RequestGate()
    results: list = []
    job = CountingJob(reporter, gate.issue("test"))
    job.signals.result.connect(lambda job_id, t, payload: results.append(payload))
    manager.submit(job)
    _drain(qt_app, manager)

    assert results == [45]


def test_base_job_without_implementation_fails_cleanly(qt_app, manager, reporter):
    gate = RequestGate()
    job = Job(reporter, gate.issue("test"))
    manager.submit(job)
    _drain(qt_app, manager)

    assert job.state is JobState.FAILED
    assert reporter.problems.count(Severity.ERROR) == 1
