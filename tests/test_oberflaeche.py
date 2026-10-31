"""Die beiden Helfer der Oberflaeche, die kein Bedienelement sind.

Die Entprellung sammelt schnelle Aenderungen, der Fensterzustand merkt sich
Groessen und Teilerstellungen. Beide lagen kurzzeitig in qt_controls_pyrs und
sind am 2026-10-31 zurueckgekommen: eine Widget-Sammlung bestimmt das
Aussehen, sie haelt keinen Zustand und bremst keine Signale.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QLineEdit, QSplitter

from app import APP_SLUG
from app.oberflaeche.entprellung import Debouncer
from app.oberflaeche import fensterzustand


# Entprellung ------------------------------------------------------------------

def test_die_entprellung_sammelt_schnelle_aenderungen(qtbot):
    """Ohne sie startet jeder Tastendruck einen eigenen Rechenlauf.

    Aus "100", "1000", "10000" wuerden drei Optimierungen, von denen zwei
    sofort wieder verworfen werden (Spezifikation 32).
    """
    aufrufe = []
    bremse = Debouncer(lambda: aufrufe.append(1), delay_ms=50)

    bremse.trigger()
    bremse.trigger()
    bremse.trigger()
    assert bremse.pending
    assert aufrufe == []

    qtbot.wait(150)
    assert aufrufe == [1], "drei Aenderungen muessen einen Aufruf ergeben"
    assert not bremse.pending


def test_abbrechen_verwirft_was_aussteht(qtbot):
    aufrufe = []
    bremse = Debouncer(lambda: aufrufe.append(1), delay_ms=50)
    bremse.trigger()
    bremse.cancel()
    qtbot.wait(150)
    assert aufrufe == []


def test_sofort_ausloesen_holt_die_letzte_eingabe(qtbot):
    """Fuer den Moment, in dem ein Tab verlassen wird."""
    aufrufe = []
    bremse = Debouncer(lambda: aufrufe.append(1), delay_ms=5000)
    bremse.trigger()
    bremse.flush()
    assert aufrufe == [1], "ohne flush() waere die letzte Eingabe verloren"
    assert not bremse.pending

    # Ohne etwas Ausstehendes passiert nichts - flush() ist kein Ausloeser.
    bremse.flush()
    assert aufrufe == [1]


# Fensterzustand ---------------------------------------------------------------

def test_der_ablageort_traegt_den_namen_der_anwendung():
    """Unter einem anderen Namen faende niemand seine Einstellungen wieder.

    In der Bibliotheksfassung stand hier eine modulweite Variable und eine
    set_application()-Funktion, die jemand haette vergessen koennen. Hier ist
    es schlicht APP_SLUG.
    """
    ablage = fensterzustand.store("Probe")
    assert isinstance(ablage, QSettings)
    assert APP_SLUG in ablage.fileName() or ablage.organizationName() == APP_SLUG


@pytest.fixture
def teiler(qtbot):
    def bauen():
        s = QSplitter()
        s.addWidget(QLineEdit())
        s.addWidget(QLineEdit())
        qtbot.addWidget(s)
        s.resize(400, 50)
        return s
    return bauen


def test_eine_gemerkte_teilung_kommt_zurueck(teiler, tmp_path, monkeypatch):
    """Gespeichert wird der Zustand, nicht zwei Zahlen."""
    monkeypatch.setenv("HOME", str(tmp_path))
    abschnitt = "ProbeGemerkt"
    fensterzustand.store(abschnitt).clear()

    erster = teiler()
    erster.setSizes([300, 100])
    fensterzustand.save_splitter(erster, abschnitt)

    zweiter = teiler()
    fensterzustand.restore_splitter(zweiter, abschnitt, fallback=[50, 350])

    links, rechts = zweiter.sizes()
    assert links > rechts, "die Vorgabe darf nicht gewonnen haben"
    fensterzustand.store(abschnitt).clear()


def test_ohne_gemerkte_teilung_gilt_die_vorgabe(teiler):
    """Geprueft wird das Verhaeltnis, nicht der Bildpunkt.

    Qt rechnet die Breite des Griffs von der verfuegbaren Breite ab: aus
    120/280 werden bei 400 Bildpunkten 119/277. Auf genaue Zahlen zu pruefen
    hiesse, die Griffbreite mitzupruefen - und die gehoert zum Stil.
    """
    abschnitt = "ProbeNochNieBenutzt"
    fensterzustand.store(abschnitt).clear()

    s = teiler()
    fensterzustand.restore_splitter(s, abschnitt, fallback=[120, 280])

    links, rechts = s.sizes()
    assert links + rechts >= 390, "die Breite muss vollstaendig verteilt sein"
    assert rechts / links == pytest.approx(280 / 120, rel=0.05)
