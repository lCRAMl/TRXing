"""Fenster mit der Rechenwegdokumentation.

Kein modaler Dialog: man liest die Erklaerung, waehrend man die zugehoerigen
Werte im Tab danebenstehen hat. Ein modales Fenster wuerde genau das
verhindern.

Aufbau links Kapitelliste, rechts Text - bei sieben Kapiteln mit Formeln ist
eine reine Scrollflaeche nicht mehr zu ueberblicken. Dazu eine Suche, weil man
in so einem Text meist einen bestimmten Begriff sucht und nicht ein Kapitel.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QTextDocument
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.gui.help.content import full_document, sections
from app.gui.theme import PALETTE


class FormulaHelpDialog(QDialog):
    """Erklaert jede Rechnung der Anwendung - mathematisch und im Quelltext."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rechenwege und Formeln")
        self.setModal(False)
        self.resize(1060, 780)

        self._sections = sections()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        layout.addLayout(self._build_search())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_index())
        splitter.addWidget(self._build_view())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 810])
        layout.addWidget(splitter, stretch=1)

        # Qt liefert die Beschriftung seiner Standardknoepfe aus eigenen
        # Uebersetzungsdateien, die die Anwendung nicht mitnimmt - ohne diese
        # Zeile steht in einem sonst deutschen Fenster "Close".
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Schliessen")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        QShortcut(QKeySequence.StandardKey.Find, self, self._focus_search)
        self._index.setCurrentRow(0)

    # Aufbau -------------------------------------------------------------------

    def _build_search(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Suchen"))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Begriff eingeben, Eingabetaste fuer den naechsten Treffer")
        self._search.returnPressed.connect(self._find_next)
        self._search.textChanged.connect(self._on_search_changed)
        row.addWidget(self._search, stretch=1)

        next_button = QPushButton("Weiter")
        next_button.clicked.connect(self._find_next)
        row.addWidget(next_button)

        self._search_state = QLabel("")
        self._search_state.setStyleSheet("color: " + PALETTE.text_muted + ";")
        self._search_state.setMinimumWidth(150)
        row.addWidget(self._search_state)
        return row

    def _build_index(self) -> QWidget:
        self._index = QListWidget()
        self._index.addItems([section.title for section in self._sections])
        self._index.currentRowChanged.connect(self._on_section_selected)
        return self._index

    def _build_view(self) -> QWidget:
        self._view = QTextBrowser()
        self._view.setOpenExternalLinks(False)
        self._view.setHtml(full_document())
        return self._view

    # Bedienung ----------------------------------------------------------------

    def _on_section_selected(self, row: int) -> None:
        if 0 <= row < len(self._sections):
            self._view.scrollToAnchor(self._sections[row].anchor)

    def _focus_search(self) -> None:
        self._search.setFocus()
        self._search.selectAll()

    def _on_search_changed(self, text: str) -> None:
        """Bei jeder Eingabe von vorn suchen.

        Ohne das Zuruecksetzen der Schreibmarke sucht Qt ab der aktuellen
        Stelle weiter, und ein neuer Begriff wird im Text darueber nicht
        gefunden - was aussieht, als gaebe es ihn nicht.
        """
        self._search_state.setText("")
        if not text:
            return
        cursor = self._view.textCursor()
        cursor.setPosition(0)
        self._view.setTextCursor(cursor)
        self._find_next()

    def _find_next(self) -> None:
        text = self._search.text().strip()
        if not text:
            return
        if self._view.find(text):
            self._search_state.setText("")
            return

        # Nichts mehr ab der aktuellen Stelle: von vorn versuchen, bevor
        # "nicht gefunden" gemeldet wird.
        cursor = self._view.textCursor()
        cursor.setPosition(0)
        self._view.setTextCursor(cursor)
        if self._view.find(text):
            self._search_state.setText("wieder von vorn")
        else:
            self._search_state.setText("nicht gefunden")

    def show_section(self, anchor: str) -> None:
        """Ein bestimmtes Kapitel aufschlagen - fuer einen spaeteren
        Direkteinstieg aus einem Tab heraus."""
        for row, section in enumerate(self._sections):
            if section.anchor == anchor:
                self._index.setCurrentRow(row)
                return

    def find_in_document(self, text: str) -> bool:
        """Suche von aussen anstossen. Gibt zurueck, ob etwas gefunden wurde."""
        document = self._view.document()
        return not document.find(text, 0, QTextDocument.FindFlag(0)).isNull()
