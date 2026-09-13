"""Serviceschicht der Vakuumplatte (Spezifikation 29).

Die Oberflaeche kennt weder VacuumCalculator noch LeakageModel oder ForceModel.
Sie stellt einen VacuumInput zusammen und bekommt ein VacuumResult zurueck.

Die Rueckwaertsrechnung aus Spezifikation 24 - welche Saugerzahl braucht ein
gegebenes Gewicht - steckt im Ergebnis und zusaetzlich in einer eigenen,
synchronen Abfrage: sie ist eine Formelauswertung ohne Geometrie und braucht
keinen Hintergrundjob.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject

from app.config.schema import VacuumDefaults
from app.config.settings_service import SettingsService
from app.core.errors import ErrorReporter
from app.core.requests import RequestGate
from app.dto.suction import SuctionCupSpec
from app.dto.vacuum import GripDirection, VacuumInput
from app.engines.vacuum.calculator import VacuumCalculator, VacuumError
from app.engines.vacuum.force import (
    holding_force_per_cup_n,
    max_mass_kg,
    required_cup_count,
)
from app.engines.vacuum.layout import SuctionLayoutEngine
from app.jobs.job_manager import JobManager
from app.jobs.job_types import CHANNEL_VACUUM, JobHandle
from app.services.calculation_service import CalculationService


class VacuumService(CalculationService):
    """Oeffentliche Schnittstelle des Vakuummoduls."""

    channel = CHANNEL_VACUUM
    job_title = "Vakuumplatte"

    #: Die Vakuumrechnung ist kurz - sie gehoert in den interaktiven Pool,
    #: damit sie nicht hinter einem langen Palettierlauf wartet.
    pool = "interactive"

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
        self._calculator = VacuumCalculator()
        self._layout_engine = SuctionLayoutEngine()

    # Auswahllisten ------------------------------------------------------------

    def available_cups(self) -> tuple[SuctionCupSpec, ...]:
        return self._settings.get_suction_cups()

    def defaults(self) -> VacuumDefaults:
        return self._settings.get_vacuum_defaults()

    def max_cup_count(self, cup: SuctionCupSpec, plate, arrangement_id: str = "grid_spread") -> int:
        """Hoechstzahl der Sauger fuer dieses Muster auf dieser Platte.

        Wird gebraucht, um die Obergrenze des Eingabefelds zu setzen, bevor
        gerechnet wird - sonst kann der Benutzer eine Zahl eintragen, die die
        Platte nie aufnimmt. Die Zahl haengt vom Muster ab: die dichteste
        Packung nimmt rund fuenfzehn Prozent mehr auf als ein Quadratraster.
        """
        return self._layout_engine.capacity(cup, plate, arrangement_id)

    def available_arrangements(self) -> tuple[tuple[str, str, str], ...]:
        """Die waehlbaren Saugermuster als (Kennung, Beschriftung, Erklaerung).

        Die Oberflaeche fuellt daraus ihr Auswahlfeld, ohne die Muster einzeln
        zu kennen - ein neues Muster erscheint allein durch seine Anmeldung in
        app/engines/vacuum/arrangements.py.
        """
        from app.engines.vacuum import arrangements

        return tuple(
            (strategy_id, arrangements.label_of(strategy_id), arrangements.description_of(strategy_id))
            for strategy_id in arrangements.available()
        )

    # Berechnung ---------------------------------------------------------------

    def calculate_async(self, request: VacuumInput, state_revision: int = 0) -> JobHandle:
        """Startet eine Vakuumrechnung im Hintergrund."""

        def work(token, progress, ticket):
            progress(0, 2, "Sauger verteilen")
            try:
                result = self._calculator.calculate(
                    request, token=token,
                    request_id=ticket.request_id, state_revision=ticket.state_revision,
                )
            except VacuumError as exc:
                raise VacuumError(str(exc)) from None
            progress(2, 2, "fertig")
            return result

        return self._submit(work, state_revision=state_revision)

    # Rueckwaertsrechnung ------------------------------------------------------

    def cups_needed_for(
        self,
        mass_kg: float,
        cup: SuctionCupSpec,
        vacuum_pa: float,
        safety_factor: float,
        acceleration_ms2: float = 0.0,
        grip: GripDirection = GripDirection.HORIZONTAL,
        friction_factor: float = 0.5,
    ) -> int:
        """Wie viele wirksame Sauger dieses Gewicht braucht (Spezifikation 24)."""
        return required_cup_count(
            mass_kg, cup, vacuum_pa, safety_factor, acceleration_ms2,
            grip=grip, friction_factor=friction_factor,
        )

    def mass_for_cups(
        self,
        cup_count: int,
        cup: SuctionCupSpec,
        vacuum_pa: float,
        safety_factor: float,
        acceleration_ms2: float = 0.0,
        grip: GripDirection = GripDirection.HORIZONTAL,
        friction_factor: float = 0.5,
    ) -> float:
        """Welches Gewicht diese Saugerzahl traegt - die Gegenrichtung.

        Rein rechnerisch und ohne Geometrie: sie beantwortet die Frage "was
        traegt eine vollstaendig aufliegende Platte", waehrend die vollstaendige
        Berechnung zusaetzlich prueft, welche Sauger ueberhaupt aufliegen.
        """
        total = holding_force_per_cup_n(cup, vacuum_pa) * max(0, cup_count)
        return max_mass_kg(total, safety_factor, acceleration_ms2, grip=grip, friction_factor=friction_factor)
