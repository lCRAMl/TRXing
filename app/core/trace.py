"""Nachvollziehbarer Rechenweg (Spezifikation 40 und 41).

Jede Berechnung fuehrt einen Trace mit: welche Schritte lief sie, was ging
hinein, was kam heraus, welche Annahme wurde getroffen. Das Ergebnis-DTO traegt
den Trace mit, ein spaeterer Analysemodus kann ihn anzeigen, ohne dass an der
Engine etwas geaendert werden muss.

Zwei Regeln, die den Trace brauchbar halten:

* Keine vollstaendigen Objektabbilder. Ein Trace, der 4000 Platzierungen
  abbildet, wird weder gelesen noch geloggt - er kostet nur Speicher. Schritte
  tragen Zahlen und kurze Texte.
* Annahmen werden ausdruecklich vermerkt. Spezifikation 25 verbietet, erfundene
  Kennwerte als exaktes Ergebnis auszugeben. `assumption()` ist der Weg, eine
  Naeherung sichtbar zu machen; die Oberflaeche zeigt diese Liste an.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TraceStep:
    """Ein Schritt im Rechenweg."""

    name: str
    detail: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0


@dataclass(frozen=True, slots=True)
class Assumption:
    """Eine bewusst getroffene Vereinfachung oder ein nicht belegter Kennwert.

    source unterscheidet, woher der Wert stammt:
        "datasheet"   aus dem Herstellerdatenblatt uebernommen
        "config"      vom Benutzer oder aus der Konfiguration gesetzt
        "model"       Annahme des Rechenmodells, im Datenblatt nicht enthalten
    """

    name: str
    description: str
    source: str = "model"
    value: Any = None


@dataclass
class CalculationTrace:
    """Sammelt Schritte und Annahmen einer Berechnung. Veraenderlich waehrend
    der Rechnung, wird danach eingefroren an das Ergebnis-DTO gehaengt."""

    calculation_id: str
    module_id: str
    algorithm_version: str
    request_id: int = 0
    started_at: float = field(default_factory=time.time)
    steps: list[TraceStep] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    _last_mark: float = field(default_factory=time.perf_counter, repr=False)

    def step(self, name: str, detail: str = "", **values: Any) -> None:
        now = time.perf_counter()
        self.steps.append(
            TraceStep(name=name, detail=detail, values=dict(values), elapsed_s=now - self._last_mark)
        )
        self._last_mark = now

    def assumption(self, name: str, description: str, *, source: str = "model", value: Any = None) -> None:
        self.assumptions.append(Assumption(name=name, description=description, source=source, value=value))

    def summary(self) -> str:
        """Einzeiler fuer das Protokoll - Schrittnamen, keine Datenmengen."""
        return (
            self.module_id + " v" + self.algorithm_version
            + " req=" + str(self.request_id)
            + " [" + " -> ".join(s.name for s in self.steps) + "]"
        )

    def freeze(self) -> FrozenTrace:
        return FrozenTrace(
            calculation_id=self.calculation_id,
            module_id=self.module_id,
            algorithm_version=self.algorithm_version,
            request_id=self.request_id,
            started_at=self.started_at,
            steps=tuple(self.steps),
            assumptions=tuple(self.assumptions),
        )


@dataclass(frozen=True, slots=True)
class FrozenTrace:
    """Unveraenderliche Fassung, die an Ergebnis-DTOs haengt."""

    calculation_id: str
    module_id: str
    algorithm_version: str
    request_id: int
    started_at: float
    steps: tuple[TraceStep, ...] = ()
    assumptions: tuple[Assumption, ...] = ()

    @property
    def total_elapsed_s(self) -> float:
        return sum(s.elapsed_s for s in self.steps)

    def model_assumptions(self) -> tuple[Assumption, ...]:
        """Nur die Annahmen, die nicht aus Datenblatt oder Konfiguration stammen."""
        return tuple(a for a in self.assumptions if a.source == "model")


def new_trace(module_id: str, algorithm_version: str, request_id: int = 0) -> CalculationTrace:
    """Erzeugt einen Trace mit einer je Aufruf eindeutigen Kennung."""
    calculation_id = module_id + "-" + format(int(time.time() * 1000) % 100_000_000, "08d")
    return CalculationTrace(
        calculation_id=calculation_id,
        module_id=module_id,
        algorithm_version=algorithm_version,
        request_id=request_id,
    )
