"""Erzeugt aus den Layoutdateien des Qt Designer die Python-Gegenstuecke.

    app/gui/vacuum/vacuum_tab.ui   ->   app/gui/vacuum/ui_vacuum_tab.py

Aufruf:

    python tools/build_ui.py            alle veralteten neu erzeugen
    python tools/build_ui.py --force    alle neu erzeugen
    python tools/build_ui.py --check    nur pruefen, nichts schreiben

Warum kompiliert und nicht zur Laufzeit geladen: die erzeugte Datei nennt jedes
Widget als Attribut. Der Editor vervollstaendigt sie, ein Tippfehler im
Objektnamen faellt beim Schreiben auf statt beim Oeffnen des Tabs, und die
gepackte Anwendung braucht die XML-Dateien nicht mitzunehmen.

Der Preis ist dieser Zwischenschritt. Damit er nicht vergessen wird, prueft
tests/test_ui_files.py bei jedem Testlauf, ob eine .ui neuer ist als ihre
erzeugte Datei - und AUTOBUILD.py ruft dieses Skript vor dem Paketieren auf.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "app" / "gui"

#: Kopfzeile, die die erzeugten Dateien als solche kennzeichnet.
HEADER = (
    '"""AUTOMATISCH ERZEUGT aus {source} - nicht von Hand aendern.\n'
    "\n"
    "Geaendert wird die .ui-Datei im Qt Designer, danach:\n"
    "\n"
    "    python tools/build_ui.py\n"
    '"""\n'
    "\n"
)


def ui_files() -> list[Path]:
    return sorted(GUI.rglob("*.ui"))


def target_for(source: Path) -> Path:
    return source.with_name("ui_" + source.stem + ".py")


def is_stale(source: Path) -> bool:
    """Zeitmarkenvergleich - billig und im Alltag ausreichend.

    Der inhaltliche Vergleich bleibt tests/test_ui_files.py vorbehalten: er
    kostet je Datei einen Aufruf von pyuic6 und lohnt sich hier nicht, wo im
    Zweifel ohnehin neu erzeugt wird.
    """
    target = target_for(source)
    return not target.is_file() or target.stat().st_mtime < source.stat().st_mtime


def check_source(source: Path) -> list[str]:
    """Sucht Eigenschaften, die pyuic6 nicht uebersetzen kann.

    Die Streckung eines Layouts bietet der Designer im Eigenschaftsfenster als
    "layoutStretch" an, pyuic6 erzeugt daraus aber einen Aufruf
    setStretch("0,1") - und der scheitert zur Laufzeit, weil setStretch zwei
    Zahlen erwartet. Der Fehler faellt erst beim Oeffnen des Tabs auf und ist
    dann schwer zuzuordnen; deshalb wird er hier abgefangen.

    Dasselbe Ergebnis erreicht man mit Groessenrichtlinien: was nicht wachsen
    soll, bekommt waagerecht oder senkrecht "Maximum", der Rest "Preferred"
    oder "Expanding".
    """
    text = source.read_text(encoding="utf-8")
    problems: list[str] = []

    for match in re.finditer(r'<property name="stretch">', text):
        line = text[: match.start()].count("\n") + 1
        problems.append(
            str(line) + ": Eigenschaft 'stretch' an einem Layout. pyuic6 erzeugt daraus "
            "einen ungueltigen Aufruf. Stattdessen Groessenrichtlinien verwenden: "
            "was nicht wachsen soll, bekommt 'Maximum'."
        )
    return problems


def render(source: Path) -> str:
    """Uebersetzt eine .ui-Datei und gibt den fertigen Dateiinhalt zurueck.

    Getrennt von compile_one, damit tests/test_ui_files.py dieselbe Uebersetzung
    ausfuehren und ihr Ergebnis mit der eingecheckten Datei vergleichen kann.
    Ein Vergleich ueber Zeitmarken waere dort wertlos: nach einem frischen
    Auschecken tragen alle Dateien dieselbe Zeit, und eine vergessene
    Neuerzeugung faellt nicht auf.
    """
    result = subprocess.run(
        [sys.executable, "-m", "PyQt6.uic.pyuic", str(source)],
        capture_output=True, text=True, cwd=ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError("pyuic6 ist an " + source.name + " gescheitert:\n" + result.stderr)

    body = result.stdout
    # Die Zeitmarke von pyuic6 aendert sich bei jedem Lauf und macht aus jeder
    # Neuerzeugung eine Aenderung, auch wenn sich nichts geaendert hat.
    body = re.sub(r"^# Created by: .*\n", "", body, flags=re.MULTILINE)
    body = re.sub(r"^# Form implementation generated.*\n", "", body, flags=re.MULTILINE)
    body = re.sub(r"^#\n", "", body, count=1, flags=re.MULTILINE)

    return HEADER.format(source=source.relative_to(ROOT).as_posix()) + body.lstrip("\n")


def compile_one(source: Path) -> None:
    try:
        content = render(source)
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    target_for(source).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Erzeugt ui_*.py aus den .ui-Dateien")
    parser.add_argument("--force", action="store_true", help="Alle neu erzeugen, auch aktuelle")
    parser.add_argument("--check", action="store_true", help="Nur pruefen, nichts schreiben")
    args = parser.parse_args(argv)

    sources = ui_files()
    if not sources:
        print("Keine .ui-Dateien unter " + str(GUI))
        return 0

    problems: list[str] = []
    for source in sources:
        for problem in check_source(source):
            problems.append(source.relative_to(ROOT).as_posix() + ":" + problem)
    if problems:
        print("Unuebersetzbare Eigenschaften gefunden:", file=sys.stderr)
        for problem in problems:
            print("  " + problem, file=sys.stderr)
        return 2

    stale = [s for s in sources if args.force or is_stale(s)]

    if args.check:
        if stale:
            print("Veraltet (bitte 'python tools/build_ui.py' ausfuehren):", file=sys.stderr)
            for source in stale:
                print("  " + source.relative_to(ROOT).as_posix(), file=sys.stderr)
            return 1
        print(str(len(sources)) + " Layoutdatei(en), alle aktuell")
        return 0

    for source in sources:
        if source in stale:
            compile_one(source)
            print("  erzeugt: " + target_for(source).relative_to(ROOT).as_posix())
        else:
            print("  aktuell: " + target_for(source).relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
