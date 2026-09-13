"""Tests der Querschnittsschicht: Fehler, Abbruch, Anfragenummern, Trace."""

from __future__ import annotations

import threading

import pytest

from app.core.cancellation import CancellationToken, CancelledError
from app.core.errors import AppError, CallbackSink, Severity
from app.core.requests import RequestGate
from app.core.result import Status, ValidationIssue, ValidationReport, classify
from app.core.trace import new_trace
from app.core.units import force_from_pressure, lpm_to_m3s, m3s_to_lpm, mbar_to_pa


# Fehler -----------------------------------------------------------------------

def test_severity_labels_are_german():
    assert Severity.WARNING.label == "Warnung"
    assert Severity.CRITICAL.label == "Kritisch"


def test_error_from_exception_keeps_type_and_traceback():
    try:
        raise ValueError("kaputt")
    except ValueError as exc:
        error = AppError.from_exception(exc, source="test")
    assert error.exception_type == "ValueError"
    assert "ValueError" in (error.technical_message or "")
    assert error.severity is Severity.ERROR


def test_message_key_groups_identical_messages(reporter):
    for _ in range(5):
        reporter.warning("engine", "Paket passt nicht")
    entries = reporter.problems.entries()
    assert len(entries) == 1
    assert entries[0][1] == 5


def test_broken_sink_does_not_stop_the_others(reporter):
    """Spezifikation 09: ein defekter Ausgang darf die uebrigen nicht zerstoeren."""

    class Broken:
        def handle(self, error):
            raise RuntimeError("Senke defekt")

    seen: list[AppError] = []
    reporter.add_sink(Broken())
    reporter.add_sink(CallbackSink(seen.append))

    reporter.error("test", "erste")
    reporter.error("test", "zweite")

    assert len(seen) == 2
    assert reporter.problems.count(Severity.ERROR) == 2


def test_problem_store_respects_its_limit():
    from app.core.errors import ProblemStore

    store = ProblemStore(limit=3)
    for i in range(10):
        store.handle(AppError(Severity.INFO, "test", "meldung " + str(i)))
    assert len(store.entries()) == 3


# Abbruch ----------------------------------------------------------------------

def test_token_starts_uncancelled():
    assert CancellationToken().cancelled is False


def test_cancel_propagates_to_children():
    parent = CancellationToken()
    child = parent.child()
    grandchild = child.child()
    parent.cancel()
    assert child.cancelled and grandchild.cancelled


def test_child_created_after_cancel_is_already_cancelled():
    parent = CancellationToken()
    parent.cancel()
    assert parent.child().cancelled


def test_raise_if_cancelled_raises():
    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        token.raise_if_cancelled()


def test_cancel_is_visible_across_threads():
    token = CancellationToken()
    seen: list[bool] = []

    def worker():
        token.wait(timeout=2.0)
        seen.append(token.cancelled)

    thread = threading.Thread(target=worker)
    thread.start()
    token.cancel()
    thread.join(timeout=3.0)
    assert seen == [True]


# Anfragenummern ---------------------------------------------------------------

def test_gate_numbers_rise_per_channel():
    gate = RequestGate()
    first = gate.issue("pallet")
    second = gate.issue("pallet")
    other = gate.issue("vacuum")
    assert (first.request_id, second.request_id, other.request_id) == (1, 2, 1)


def test_gate_discards_overtaken_result():
    """Spezifikation 08: Anfrage 41 endet nach 42 - ihr Ergebnis wird verworfen."""
    gate = RequestGate()
    ticket_41 = gate.issue("pallet")
    ticket_42 = gate.issue("pallet")

    assert gate.accept(ticket_41) is False
    assert gate.accept(ticket_42) is True


def test_gate_rejects_a_second_arrival_of_the_same_ticket():
    gate = RequestGate()
    ticket = gate.issue("pallet")
    assert gate.accept(ticket) is True
    assert gate.accept(ticket) is False


def test_invalidate_entwertet_laufende_anfragen():
    gate = RequestGate()
    ticket = gate.issue("vacuum")
    gate.invalidate("vacuum")
    assert gate.is_current(ticket) is False
    assert gate.accept(ticket) is False


def test_channels_do_not_interfere():
    gate = RequestGate()
    pallet = gate.issue("pallet")
    gate.issue("vacuum")
    gate.issue("vacuum")
    assert gate.accept(pallet) is True


# Validierung ------------------------------------------------------------------

def test_report_separates_errors_and_warnings():
    from app.core.result import IssueLevel

    report = ValidationReport((
        ValidationIssue("length_mm", "zu klein"),
        ValidationIssue("weight_kg", "grenzwertig", IssueLevel.WARNING),
    ))
    assert report.ok is False
    assert len(report.errors) == 1
    assert len(report.warnings) == 1
    assert report.for_field("length_mm")[0].message == "zu klein"


def test_classify_uses_numeric_thresholds():
    assert classify(actual=120.0, required=100.0) is Status.SAFE
    assert classify(actual=105.0, required=100.0) is Status.MARGINAL
    assert classify(actual=99.0, required=100.0) is Status.INSUFFICIENT


# Einheiten und Trace ----------------------------------------------------------

def test_unit_round_trip():
    assert mbar_to_pa(600) == 60000.0
    assert m3s_to_lpm(lpm_to_m3s(500.0)) == pytest.approx(500.0)


def test_force_from_pressure_matches_datasheet_spb2_20():
    """d2 = 12,0 mm bei -0,6 bar ergibt die Datenblattkraft 6,8 N."""
    import math

    area = math.pi / 4 * 12.0 ** 2
    assert force_from_pressure(60000.0, area) == pytest.approx(6.8, abs=0.02)


def test_trace_records_steps_and_assumptions():
    trace = new_trace("pallet", "1.0", request_id=7)
    trace.step("kandidaten", "3 Muster", count=3)
    trace.step("bestes", "brick")
    trace.assumption("cell_size", "Quadratische Zelle bei rechteckigem Paket", source="model")
    frozen = trace.freeze()

    assert [s.name for s in frozen.steps] == ["kandidaten", "bestes"]
    assert len(frozen.model_assumptions()) == 1
    assert "req=7" in frozen.summary() if hasattr(frozen, "summary") else True
    assert frozen.request_id == 7


# Farbschema des Betriebssystems -----------------------------------------------

def test_theme_override_wins_over_the_system(monkeypatch):
    """TRXING_THEME sticht die Einstellung von Windows.

    Ohne diesen Weg liesse sich die dunkle Fassung nur pruefen, indem der Test
    die Registry des Benutzers umstellt.
    """
    from app.core import os_theme

    monkeypatch.setenv(os_theme.ENV_NAME, "dark")
    assert os_theme.prefers_dark() is True

    monkeypatch.setenv(os_theme.ENV_NAME, "light")
    assert os_theme.prefers_dark() is False


def test_theme_falls_back_to_the_system_setting(monkeypatch):
    """Ohne Vorgabe und bei unbekannter Vorgabe zaehlt Windows."""
    from app.core import os_theme

    monkeypatch.setattr(os_theme, "windows_prefers_dark", lambda: True)

    monkeypatch.delenv(os_theme.ENV_NAME, raising=False)
    assert os_theme.prefers_dark() is True

    monkeypatch.setenv(os_theme.ENV_NAME, "auto")
    assert os_theme.prefers_dark() is True


def test_unreadable_registry_means_light(monkeypatch):
    """Ein Lesefehler darf den Start nicht aufhalten - dann eben hell."""
    import builtins

    from app.core import os_theme

    real_import = builtins.__import__

    def without_winreg(name, *args, **kwargs):
        if name == "winreg":
            raise ImportError("kein Windows")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_winreg)
    assert os_theme.windows_prefers_dark() is False
