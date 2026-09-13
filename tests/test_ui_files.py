"""Wacht ueber die Layoutdateien des Qt Designer.

Seit die Anordnung der Tabs in .ui-Dateien steht, gibt es einen Zwischenschritt
zwischen Bearbeiten und Ausfuehren:

    app/gui/vacuum/vacuum_tab.ui          im Designer bearbeitet
       |  python tools/build_ui.py
       v
    app/gui/vacuum/ui_vacuum_tab.py       erzeugt, nicht von Hand aendern
       |
       v
    app/gui/vacuum/vacuum_tab.py          Verhalten

Vergisst jemand den Zwischenschritt, laeuft die Anwendung weiter - mit dem
alten Layout. Der Fehler ist heimtueckisch, weil nichts abstuerzt und die
.ui-Datei richtig aussieht. Deshalb uebersetzt der erste Test hier jede
Layoutdatei neu und vergleicht das Ergebnis mit der eingecheckten Datei.

Die uebrigen Tests sichern Eigenschaften, die im Designer mit einem Klick
verschwinden und deren Fehlen man erst am fertigen Fenster sieht: eine
Mindestbreite an einem umbrechenden Hinweis, die Groessenbegrenzung eines
Auswahlfeldes, den Rahmen, der nicht mitwachsen soll.
"""

from __future__ import annotations

import ast
import pathlib
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUI = ROOT / "app" / "gui"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tools"))
import build_ui  # noqa: E402  - liegt in tools/, deshalb erst nach der Pfadergaenzung


def _ui_files() -> list[pathlib.Path]:
    return sorted(GUI.rglob("*.ui"))


def _ids() -> list[str]:
    return [p.stem for p in _ui_files()]


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _widgets(source: pathlib.Path):
    """Alle <widget>-Knoten einer Layoutdatei."""
    return ET.parse(source).getroot().iter("widget")


def _property(node, name: str):
    for prop in node.findall("property"):
        if prop.get("name") == name:
            return prop
    return None


# Es gibt ueberhaupt Layoutdateien ---------------------------------------------

def test_every_tab_has_a_layout_file() -> None:
    """Jeder Tab bringt seine Anordnung in einer eigenen .ui-Datei mit."""
    tabs = sorted(p.stem for p in GUI.rglob("*_tab.py") if not p.name.startswith("ui_"))
    layouts = sorted(p.stem for p in _ui_files())
    missing = [stem for stem in tabs if stem not in layouts]
    assert not missing, "Tab ohne Layoutdatei: " + ", ".join(missing)


def test_every_layout_file_belongs_to_a_module() -> None:
    """Und umgekehrt: zu jeder Layoutdatei gehoert ein Modul gleichen Namens.

    Nicht jede Anordnung ist ein Tab. Die Paketdaten sind ein Formular, das im
    Kopf der Palettierung haengt (package_form.ui) und trotzdem derselben
    Trennung von Anordnung und Verhalten unterliegt. Eine Layoutdatei ohne
    Gegenstueck waere dagegen eine, die niemand mehr benutzt.
    """
    orphans = [
        _relative(source) for source in _ui_files()
        if not source.with_suffix(".py").is_file()
    ]
    assert not orphans, "Layoutdatei ohne Modul: " + ", ".join(orphans)


# Erzeugte Dateien sind aktuell -------------------------------------------------

@pytest.mark.parametrize("source", _ui_files(), ids=_ids())
def test_generated_file_matches_its_layout(source: pathlib.Path) -> None:
    """Die erzeugte Datei ist genau das, was pyuic6 aus der .ui-Datei macht.

    Verglichen wird der Inhalt, nicht die Zeitmarke: nach einem frischen
    Auschecken tragen alle Dateien dieselbe Zeit, und eine vergessene
    Neuerzeugung faellt dann nicht mehr auf.
    """
    target = build_ui.target_for(source)
    assert target.is_file(), (
        _relative(target) + " fehlt. Bitte 'python tools/build_ui.py' ausfuehren."
    )
    assert target.read_text(encoding="utf-8") == build_ui.render(source), (
        _relative(target) + " passt nicht mehr zu " + _relative(source) + ".\n"
        "Bitte 'python tools/build_ui.py' ausfuehren."
    )


@pytest.mark.parametrize("source", _ui_files(), ids=_ids())
def test_generated_file_says_that_it_is_generated(source: pathlib.Path) -> None:
    """Die erzeugte Datei weist sich im Kopf als erzeugt aus.

    Sie sieht aus wie gewoehnlicher Quelltext, und eine Aenderung darin haelt
    genau bis zum naechsten Aufruf von tools/build_ui.py. Der Hinweis steht
    deshalb in der ersten Zeile, wo er beim Oeffnen nicht zu uebersehen ist.
    """
    head = build_ui.target_for(source).read_text(encoding="utf-8")[:400]
    assert "AUTOMATISCH ERZEUGT" in head
    assert "tools/build_ui.py" in head
    assert _relative(source) in head, "Der Kopf nennt die Quelldatei nicht"


@pytest.mark.parametrize("source", _ui_files(), ids=_ids())
def test_layout_uses_only_translatable_properties(source: pathlib.Path) -> None:
    """Keine Eigenschaft, an der pyuic6 scheitert oder Unsinn erzeugt.

    Die Streckung eines Layouts ist der bekannte Fall: der Designer bietet sie
    an, pyuic6 macht daraus einen Aufruf setStretch("0,1"), und der scheitert
    erst beim Oeffnen des Tabs. Siehe tools/build_ui.py.
    """
    problems = build_ui.check_source(source)
    assert not problems, _relative(source) + ":\n  " + "\n  ".join(problems)


# Eigenschaften, die im Designer leicht verlorengehen ---------------------------

def test_wrapping_notes_keep_their_minimum_width() -> None:
    """Ein umbrechender Hinweis braucht eine Mindestbreite.

    Ohne sie schaetzt Qt die noetige Hoehe fuer eine Breite von einem Bildpunkt:
    rechnerisch bricht der Text nach jedem Wort um, das Formular reserviert
    mehrere hundert Bildpunkte Hoehe, und zwischen den Eingabefeldern klafft
    eine handbreite Luecke. Siehe NOTE_WRAP_WIDTH in app/gui/common/widgets.py.
    """
    from app.gui.common.widgets import NOTE_WRAP_WIDTH

    violations: list[str] = []
    for source in _ui_files():
        for node in _widgets(source):
            role = _property(node, "role")
            if role is None or (role.findtext("string") or "") != "note":
                continue
            minimum = _property(node, "minimumSize")
            width = int(minimum.find("size").findtext("width")) if minimum is not None else 0
            if width < NOTE_WRAP_WIDTH:
                violations.append(
                    _relative(source) + ": " + str(node.get("name")) + " hat minimumSize "
                    + str(width) + ", noetig sind " + str(NOTE_WRAP_WIDTH)
                )
    assert not violations, "Hinweis ohne Mindestbreite:\n  " + "\n  ".join(violations)


def test_wrapping_notes_actually_wrap() -> None:
    """Ein Hinweis mit Mindestbreite, aber ohne Umbruch, zieht die Spalte auf."""
    violations: list[str] = []
    for source in _ui_files():
        for node in _widgets(source):
            role = _property(node, "role")
            if role is None or (role.findtext("string") or "") != "note":
                continue
            wrap = _property(node, "wordWrap")
            if wrap is None or (wrap.findtext("bool") or "") != "true":
                violations.append(_relative(source) + ": " + str(node.get("name")))
    assert not violations, "Hinweis ohne wordWrap:\n  " + "\n  ".join(violations)


def test_combo_boxes_are_width_limited() -> None:
    """Ein Auswahlfeld meldet die Breite seines laengsten Eintrags.

    Ein Eintrag wie "Rueckschlagventil (schliesst bei offenem Sauger)" macht
    damit die ganze Bedienspalte so breit, dass sie neben der Zeichenflaeche
    nicht mehr Platz hat. Die Begrenzung auf eine feste Zeichenzahl verhindert
    das; der vollstaendige Text bleibt beim Aufklappen sichtbar.
    """
    violations: list[str] = []
    for source in _ui_files():
        for node in _widgets(source):
            if node.get("class") != "QComboBox":
                continue
            # Das Ebenenfeld der Palettierung sitzt in einer Werkzeugleiste und
            # traegt kurze, erzeugte Eintraege ("Ebene 3  (8)"). Es hat eine
            # feste Mindestbreite statt einer Begrenzung.
            if _property(node, "minimumSize") is not None:
                continue
            policy = _property(node, "sizeAdjustPolicy")
            length = _property(node, "minimumContentsLength")
            if policy is None or length is None:
                violations.append(_relative(source) + ": " + str(node.get("name")))
    assert not violations, (
        "Auswahlfeld ohne Breitenbegrenzung (sizeAdjustPolicy und "
        "minimumContentsLength):\n  " + "\n  ".join(violations)
    )


def test_group_boxes_do_not_grow_vertically() -> None:
    """Ein Gruppenrahmen darf nicht hoeher werden, als sein Inhalt braucht.

    Ein QVBoxLayout verteilt uebrigen Platz zuerst an wachsende Widgets und
    erst danach an einen Abstandhalter am Ende. In einer Bedienspalte, die
    hoeher ist als ihr Inhalt, zieht das die Formulare auseinander. Mit
    "Maximum" sammelt sich der Leerraum dort, wo er hingehoert: unten.
    """
    violations: list[str] = []
    for source in _ui_files():
        for node in _widgets(source):
            if node.get("class") not in ("QGroupBox", "ResultGrid"):
                continue
            policy = _property(node, "sizePolicy")
            vertical = policy.find("sizepolicy").get("vsizetype") if policy is not None else None
            if vertical != "Maximum":
                violations.append(
                    _relative(source) + ": " + str(node.get("name")) + " hat vsizetype "
                    + str(vertical)
                )
    assert not violations, "Gruppenrahmen ohne 'Maximum':\n  " + "\n  ".join(violations)


# Benutzerdefinierte Widgets ----------------------------------------------------

@pytest.mark.parametrize("source", _ui_files(), ids=_ids())
def test_custom_widgets_can_be_imported(source: pathlib.Path) -> None:
    """Jede hochgestufte Klasse gibt es wirklich - und zwar unter dem Namen,
    der in der .ui-Datei steht.

    Ein Tippfehler im Kopfzeilenfeld des Designers faellt sonst erst auf, wenn
    jemand den Tab oeffnet: setupUi scheitert dann mit einem ImportError
    mitten im Aufbau des Fensters.
    """
    import importlib

    root = ET.parse(source).getroot()
    for custom in root.iter("customwidget"):
        header = custom.findtext("header") or ""
        name = custom.findtext("class") or ""
        module = importlib.import_module(header)
        assert hasattr(module, name), header + " kennt keine Klasse " + name


# Verhalten bleibt im Quelltext, Anordnung in der Layoutdatei --------------------

#: Klassen, die eine Anordnung herstellen. Wer sie in einem Tabmodul aufruft,
#: baut Layout im Quelltext - genau das soll die .ui-Datei uebernehmen.
LAYOUT_CLASSES = {
    "QVBoxLayout", "QHBoxLayout", "QFormLayout", "QGridLayout", "QStackedLayout",
    "QGroupBox", "QSplitter", "QScrollArea", "QStackedWidget", "QTabWidget",
}


def _tab_modules() -> list[pathlib.Path]:
    """Jedes Modul mit eigener Layoutdatei - Tabs wie Formulare."""
    return sorted(source.with_suffix(".py") for source in _ui_files())


@pytest.mark.parametrize("path", _tab_modules(), ids=lambda p: p.stem)
def test_tab_modules_build_no_layout_in_code(path: pathlib.Path) -> None:
    """Ein Modul mit Layoutdatei stellt keine Anordnung mehr her.

    Die Trennung ist nur so viel wert, wie sie eingehalten wird: sobald ein Tab
    wieder eine Zeile "layout.addWidget(...)" bekommt, steht die Anordnung an
    zwei Stellen und die .ui-Datei zeigt nicht mehr, was der Benutzer sieht.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = sorted({
        node.func.id + " (Zeile " + str(node.lineno) + ")"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in LAYOUT_CLASSES
    })
    assert not found, (
        _relative(path) + " baut Layout im Quelltext: " + ", ".join(found)
        + "\nDie Anordnung gehoert in " + path.stem + ".ui."
    )


@pytest.mark.parametrize("path", _tab_modules(), ids=lambda p: p.stem)
def test_tab_modules_use_their_generated_class(path: pathlib.Path) -> None:
    """Und zwar ueber Zusammensetzung, nicht ueber Mehrfachvererbung.

    Beide Wege sind ueblich. Die Zusammensetzung gewinnt hier, weil die
    erzeugten Namen unter self.ui buendig beieinander liegen: sie koennen
    weder mit denen von QWidget noch mit eigenen kollidieren, und beim Lesen
    ist sofort erkennbar, was aus dem Designer stammt.
    """
    source = path.read_text(encoding="utf-8")
    expected = "Ui_" + "".join(part.capitalize() for part in path.stem.split("_"))
    assert expected in source, path.stem + ".py verwendet " + expected + " nicht"
    assert "self.ui = " + expected in source, (
        path.stem + ".py soll " + expected + " als self.ui halten, nicht davon erben"
    )
