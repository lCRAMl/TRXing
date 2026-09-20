"""AUTOBUILD - Version festschreiben und die Anwendung paketieren.

Ein Aufruf, drei Schritte:

    python AUTOBUILD.py

  1. Version bestimmen (aus Git, sonst aus app/__init__.py) und in
     `build_version.py` schreiben. Die Anwendung liest diese Datei beim Start
     und zeigt die Version in der Titelzeile.
  2. Mit PyInstaller eine einzelne .exe bauen, deren Dateiname die Version
     traegt.
  3. Die Konfigurationsdateien danebenlegen und den Bauplatz aufraeumen.

**Die Falle dieses Rechners:** PyQt6 und PySide6 liegen in derselben
Python-Installation und bringen gleichnamige Qt6-DLLs mit. Sammelt PyInstaller
PySide6 mit ein, gewinnt beim Start die falsche DLL, und die fertige .exe stirbt
beim Import von QtCore. PySide6 wird deshalb ausdruecklich ausgeschlossen - das
ist die wichtigste Zeile in dieser Datei. Derselbe Konflikt trifft im
Quelltextbetrieb die Tests; dort loest ihn `qt_api = pyqt6` in pytest.ini.

**Die Konfiguration wird NICHT eingebettet.** Sie liegt als Ordner neben der
.exe. Nur so laesst sie sich nach der Auslieferung anpassen - eingebettet
muesste fuer jeden neuen Saugertyp neu gebaut werden. app/core/paths.py sucht
sie zuerst neben der Programmdatei.

Ohne Git funktioniert der Lauf ebenfalls: dann liefert app/__init__.py die
Version, und Commit-Angaben bleiben leer. Beides ist ein gueltiger Zustand -
der Bau darf nicht davon abhaengen, ob gerade ein Repository danebenliegt.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import APP_NAME, APP_SLUG, __version__ as SOURCE_VERSION  # noqa: E402

# =========================
# Konfiguration
# =========================

ENTRY_POINT = "main.py"
VERSION_FILE = ROOT / "build_version.py"
OUTPUT_DIR = ROOT / "output"
BUILD_DIR = ROOT / "pyinstaller_build"
CONFIG_DIR = ROOT / "config"

#: Was NICHT eingesammelt werden darf. PySide6 und shiboken6 kollidieren mit
#: PyQt6; die uebrigen sind Testwerkzeuge, die im Paket nichts verloren haben.
#:
#: qtpy steht hier ausdruecklich NICHT: pyvistaqt spricht ausschliesslich ueber
#: qtpy mit Qt. Wird es ausgeschlossen, findet PyInstaller pyvista und
#: pyvistaqt zwar im Paket, der Import von QtInteractor stirbt aber mit
#: "No module named qtpy" - und der Palettentab zeigt statt der Szene den
#: Hinweis aus MissingBackendScene. Welche Anbindung qtpy waehlt, legt
#: app/visualization/pallet_3d.py ueber QT_API fest.
EXCLUDED = ("PySide6", "shiboken6", "PyQt5", "pytest", "_pytest", "pytestqt")

#: Pakete, deren Daten PyInstaller nicht von allein findet. VTK und PyVista
#: bringen Datendateien mit, ohne die die 3D-Ansicht im Paket nicht startet.
#: qtpy gehoert dazu, weil es seine Anbindung erst zur Laufzeit zusammensucht -
#: statisch sieht PyInstaller dort nichts zum Mitnehmen. Die Liste dient
#: zugleich als Gegenstueck fuer --no-3d: ohne 3D faellt alles hier weg.
COLLECT_ALL = ("pyvista", "vtkmodules", "pyvistaqt", "qtpy")

#: Mitzunehmende Dateien, die kein Python sind: Quelle -> Ziel im Paket, beides
#: relativ zur Projektwurzel. PyInstaller sammelt nur Module ein; eine .qss und
#: die Bildchen daneben findet es nicht von allein.
#:
#: Das Ziel ist derselbe relative Pfad wie in der Quelle. Nur so findet
#: app/gui/theme.py den Ordner in beiden Betriebsarten ueber __file__ - im
#: Quelltextbaum wie im entpackten Paket.
DATA_FILES = (
    ("app/gui/darkstyle", "app/gui/darkstyle"),
    ("app/gui/icons", "app/gui/icons"),
)

#: Symbol der fertigen Programmdatei. Dieselbe Datei, die die Anwendung zur
#: Laufzeit als Fenstersymbol setzt - siehe app/gui/icons/__init__.py.
ICON_FILE = ROOT / "app" / "gui" / "icons" / "pallet.ico"


# =========================
# Version
# =========================


def _git(*args: str) -> str | None:
    try:
        output = subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    return output.decode(errors="replace").strip() or None


def get_version() -> tuple[str, str]:
    """(Version, Commit).

    Git ist die bessere Quelle, weil sie den Stand des Arbeitsverzeichnisses
    mitzaehlt. Fehlt Git oder ist das Projekt kein Repository, gilt die Version
    aus app/__init__.py - der Bau soll daran nicht scheitern.
    """
    described = _git("describe", "--tags", "--long", "--dirty")
    commit = _git("rev-parse", "--short", "HEAD") or ""
    return described or SOURCE_VERSION, commit


def write_version_file(version: str, build_time: str, commit: str) -> None:
    VERSION_FILE.write_text(
        '"""AUTOMATISCH ERZEUGT von AUTOBUILD.py - nicht von Hand aendern."""\n\n'
        'APP_NAME = "' + APP_NAME + '"\n'
        'VERSION = "' + version + '"\n'
        'BUILD_TIME = "' + build_time + '"\n'
        'COMMIT = "' + commit + '"\n',
        encoding="utf-8",
    )
    print("  Versionsdatei geschrieben: " + VERSION_FILE.name)


# =========================
# Bauen
# =========================


def build(exe_name: str, with_3d: bool) -> None:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name=" + exe_name,
        "--distpath=" + str(OUTPUT_DIR),
        "--workpath=" + str(BUILD_DIR),
        "--specpath=" + str(BUILD_DIR),
    ]

    # Fehlt die Datei, wird ohne Symbol gebaut statt gar nicht: ein fehlendes
    # Bildchen darf die Auslieferung nicht aufhalten.
    if ICON_FILE.is_file():
        command.append("--icon=" + str(ICON_FILE))
    else:
        print("  Hinweis: " + ICON_FILE.name + " fehlt - die .exe bekommt kein Symbol")

    for module in EXCLUDED:
        command.append("--exclude-module=" + module)

    for source, target in DATA_FILES:
        command.append("--add-data=" + str(ROOT / source) + os.pathsep + target)

    if with_3d:
        for package in COLLECT_ALL:
            command.append("--collect-all=" + package)
    else:
        # Ohne 3D wird das Paket erheblich kleiner. Die Anwendung zeigt dann im
        # Palettentab einen Hinweis statt der Szene und laeuft sonst vollstaendig.
        for package in COLLECT_ALL:
            command.append("--exclude-module=" + package)

    command.append(str(ROOT / ENTRY_POINT))

    print("\n  " + " ".join(command[2:]) + "\n")
    subprocess.run(command, check=True, cwd=ROOT)


def compile_layouts() -> None:
    """Erzeugt die ui_*.py-Dateien aus den Layoutdateien des Qt Designer.

    Steht vor dem Paketieren, weil PyInstaller die .ui-Dateien nicht mitnimmt:
    im Paket gibt es nur die uebersetzten Python-Dateien. Wer eine .ui-Datei
    geaendert und den Zwischenschritt vergessen hat, bekaeme sonst ein Paket
    mit dem alten Layout - ohne Fehlermeldung.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_ui.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(result.stdout.rstrip())
    if result.returncode != 0:
        print(result.stderr.rstrip(), file=sys.stderr)
        raise SystemExit("Die Layoutdateien liessen sich nicht uebersetzen.")


def copy_configuration() -> None:
    """Legt config/ neben die Programmdatei - dort wird zuerst gesucht."""
    target = OUTPUT_DIR / "config"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(CONFIG_DIR, target)
    print("  Konfiguration kopiert: " + str(target))


def clean() -> None:
    shutil.rmtree(BUILD_DIR, ignore_errors=True)


# =========================
# Ablauf
# =========================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baut " + APP_NAME + " als .exe")
    parser.add_argument("--version-only", action="store_true",
                        help="Nur build_version.py schreiben, nicht paketieren")
    parser.add_argument("--no-3d", action="store_true",
                        help="Ohne PyVista/VTK bauen - deutlich kleineres Paket")
    parser.add_argument("--keep-build", action="store_true",
                        help="Bauverzeichnis nicht loeschen (zur Fehlersuche)")
    args = parser.parse_args(argv)

    version, commit = get_version()
    build_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("Bau von " + APP_NAME)
    print("  Version    : " + version
          + ("" if commit else "   (kein Git, Version aus app/__init__.py)"))
    if commit:
        print("  Commit     : " + commit)
    print("  Zeitpunkt  : " + build_time)
    print("  3D-Ansicht : " + ("nein" if args.no_3d else "ja"))

    write_version_file(version, build_time, commit)
    if args.version_only:
        return 0

    safe_version = version.replace("+", "_").replace(" ", "_").replace("/", "-")
    exe_name = APP_SLUG + "_" + safe_version

    OUTPUT_DIR.mkdir(exist_ok=True)
    print("\nLayoutdateien:")
    compile_layouts()
    build(exe_name, with_3d=not args.no_3d)
    copy_configuration()
    if not args.keep_build:
        clean()

    exe_path = OUTPUT_DIR / (exe_name + ".exe")
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print("\nFertig: " + str(exe_path) + "  (" + format(size_mb, ".1f") + " MB)")
        print("Zum Ausliefern beides mitnehmen: die .exe und den Ordner config/")
        return 0

    print("\nFehlgeschlagen: " + str(exe_path) + " wurde nicht erzeugt", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
