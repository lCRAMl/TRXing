"""Serviceschicht der Palettierung (Spezifikation 29).

Die Oberflaeche kennt weder PalletOptimizer noch die Musterstrategien. Sie ruft
calculate_async mit DTOs und bekommt spaeter ein PalletResult ueber ein Signal.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from app.katalog import SettingsService
from app.fehler import ErrorReporter
from app.nebenlaeufig import RequestGate
from app.paket import PackageSpec
from app.palette.daten import PalletConstraints, PalletSpec, PatternSpec, SharedLayer
from app.palette.rechnung import PalletOptimizer, PalletizingError, build_constraints
from app.nebenlaeufig import JobManager
from app.nebenlaeufig import CHANNEL_PALLET, JobHandle
from app.services.calculation_service import CalculationService


class PalletService(CalculationService):
    """Oeffentliche Schnittstelle des Palettiermoduls."""

    channel = CHANNEL_PALLET
    job_title = "Palettierung"
    pool = "cpu"

    #: Die angezeigte Lage hat gewechselt. Der Vakuumtab rechnet daraufhin neu,
    #: wenn er das Muster der Palettierung uebernimmt.
    layer_published = pyqtSignal(object)

    def __init__(
        self,
        jobs: JobManager,
        gate: RequestGate,
        reporter: ErrorReporter,
        settings: SettingsService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(jobs, gate, reporter, parent)
        self._settings = settings
        self._optimizer = PalletOptimizer()
        self._layer: SharedLayer | None = None

    # Uebergabe an die Vakuumplatte ---------------------------------------------

    def publish_layer(self, layer: SharedLayer | None) -> None:
        """Legt die gerade angezeigte Lage fuer andere Module bereit.

        Der Weg ueber den Service und nicht ueber AppState ist Absicht. AppState
        haelt den gemeinsamen Eingabestand - Paket, Palette, Muster - und wird
        bei jeder Aenderung hochgezaehlt; eine Lage ist aber ein Rechenergebnis
        und hat dort nichts verloren. Der Service, der sie erzeugt hat, ist der
        richtige Besitzer; wer sie braucht, holt sie dort ab.

        Gemeldet wird nur, was sich wirklich geaendert hat. Sonst loeste jeder
        Palettierlauf eine Vakuumrechnung aus, auch wenn dieselbe Lage dabei
        herauskommt.
        """
        if layer == self._layer:
            return
        self._layer = layer
        self.layer_published.emit(layer)

    def published_layer(self) -> SharedLayer | None:
        """Die zuletzt bereitgestellte Lage, oder None."""
        return self._layer

    # Auswahllisten ------------------------------------------------------------

    def available_pallets(self) -> tuple[PalletSpec, ...]:
        return self._settings.get_pallets()

    def available_patterns(self) -> tuple[PatternSpec, ...]:
        return self._settings.get_patterns()

    def solver_available(self) -> bool:
        """Ob die zusaetzliche CP-SAT-Strategie nutzbar ist.

        Die Oberflaeche graut die Option sonst aus, statt sie anzubieten und
        ins Leere laufen zu lassen.
        """
        from app.legemuster import solver_available

        return solver_available()

    def build_constraints(self, pallet: PalletSpec, package: PackageSpec, **overrides) -> PalletConstraints:
        """Fuehrt Palettenvorgaben und Benutzereingaben zusammen."""
        return build_constraints(pallet, package, **overrides)

    # Berechnung ---------------------------------------------------------------

    def calculate_async(
        self,
        package: PackageSpec,
        pallet: PalletSpec,
        pattern: PatternSpec,
        constraints: PalletConstraints,
        state_revision: int = 0,
    ) -> JobHandle:
        """Startet einen Palettierlauf im Hintergrund."""

        def work(token, progress, ticket):
            progress(0, 3, "Muster erzeugen")
            try:
                result = self._optimizer.optimize(
                    package=package,
                    pallet=pallet,
                    pattern=pattern,
                    constraints=constraints,
                    token=token,
                    request_id=ticket.request_id,
                    state_revision=ticket.state_revision,
                )
            except PalletizingError as exc:
                # Ein normales Ergebnis der Aufgabenstellung, kein Programmfehler.
                # Es wird als Fehlschlag der Anfrage gemeldet, damit der Tab die
                # Meldung anzeigen kann - aber ohne Rueckverfolgung im Protokoll.
                raise PalletizingError(str(exc)) from None
            progress(3, 3, "fertig")
            return result

        return self._submit(work, state_revision=state_revision)
