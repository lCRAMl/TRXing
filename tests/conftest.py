"""Gemeinsame Testvorrichtungen.

Die Oberflaechentests brauchen eine QApplication. Unter Windows ohne
angemeldete Sitzung - etwa in einem Dienst oder einer Pipeline - gibt es keinen
Bildschirm; dann springt die Offscreen-Plattform ein. Das muss vor dem ersten
Qt-Import passieren, deshalb steht es hier und nicht in einer Testdatei.

QT_API legt die Qt-Anbindung fuer qtpy fest. Auf diesem Rechner ist neben PyQt6
auch PySide6 installiert; ohne diese Vorgabe laedt qtpy PySide6 und der
anschliessende Import von PyQt6 scheitert am DLL-Konflikt. Dieselbe Vorgabe
steht in pytest.ini - die hier wirkt zusaetzlich fuer Werkzeuge, die die
Testdatei direkt importieren.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_API", "pyqt6")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if not os.environ.get("DISPLAY") and sys.platform not in ("win32", "darwin"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def reporter():
    from app.core.errors import ErrorReporter

    return ErrorReporter()


@pytest.fixture
def settings(reporter, tmp_path):
    """SettingsService auf den mitgelieferten Konfigurationsdateien."""
    from app.config.settings_service import SettingsService

    service = SettingsService(ROOT / "config", reporter)
    service.load()
    return service


@pytest.fixture
def package():
    from app.dto.package import PackageSpec

    return PackageSpec(length_mm=400.0, width_mm=300.0, height_mm=200.0, weight_kg=5.0, max_stack_load_kg=60.0)


@pytest.fixture
def euro_pallet(settings):
    return settings.get_pallet("euro_1200x800")


@pytest.fixture
def cup_spb2_30(settings):
    return settings.get_suction_cup("spb2_30")


@pytest.fixture(scope="session")
def qt_app():
    """Eine QApplication fuer die ganze Sitzung. Qt vertraegt nur eine."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
