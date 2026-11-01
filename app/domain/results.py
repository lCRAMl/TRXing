"""Wie ein Rechenergebnis beschrieben wird.

Status sagt, ob ein Ergebnis taugt. Der Trace sagt, wie es zustande kam - die
Schrittkette einer Rechnung, mitgefuehrt zur Nachvollziehbarkeit
(Spezifikation 39).

Zusammengelegt aus core/result.py und core/trace.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar
import time
from typing import Any


# ---------------------------------------------------------------------------
# result.py
# ---------------------------------------------------------------------------
"""Ergebnis- und Validierungsobjekte, die durch alle Schichten wandern.

Zwei Dinge werden hier getrennt, die gern vermischt werden:

`ValidationIssue` beschreibt ein Problem MIT EINER EINGABE und traegt dazu den
Feldnamen. Nur damit kann die Oberflaeche den Fehler am richtigen Eingabefeld
anzeigen, statt ihn in die Statusleiste zu schieben (Spezifikation 34).

`Result` beschreibt den Ausgang EINER OPERATION: gelungen mit Wert, oder
gescheitert mit Begruendung. Engines werfen fuer echte Ausnahmen weiterhin
Exceptions; Result ist fuer erwartbare Fehlschlaege gedacht, etwa "Paket passt
in keiner Ausrichtung auf die Palette" - ein voellig normales Ergebnis einer
Optimierung, kein Programmfehler.
"""

T = TypeVar("T")


class IssueLevel(Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Ein Befund zu genau einem Eingabefeld.

    field ist der technische Feldname des DTO (etwa "length_mm"), damit die
    Oberflaeche ihn ohne Rateschleife dem Widget zuordnen kann.
    """

    field: str
    message: str
    level: IssueLevel = IssueLevel.ERROR

    @property
    def is_error(self) -> bool:
        return self.level is IssueLevel.ERROR


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Sammlung aller Befunde einer Eingabepruefung."""

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(issue.is_error for issue in self.issues)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.is_error)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if not i.is_error)

    def for_field(self, name: str) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.field == name)

    def merged(self, other: ValidationReport) -> ValidationReport:
        return ValidationReport(self.issues + other.issues)

    def summary(self) -> str:
        if self.ok and not self.issues:
            return "Eingaben gueltig"
        parts = [i.message for i in self.errors] or [i.message for i in self.warnings]
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class Result(Generic[T]):
    """Ausgang einer Operation: Wert oder Begruendung, nie beides."""

    value: T | None = None
    ok: bool = True
    message: str = ""
    warnings: tuple[str, ...] = field(default=())

    @classmethod
    def success(cls, value: T, warnings: tuple[str, ...] = ()) -> Result[T]:
        return cls(value=value, ok=True, warnings=warnings)

    @classmethod
    def failure(cls, message: str, warnings: tuple[str, ...] = ()) -> Result[T]:
        return cls(value=None, ok=False, message=message, warnings=warnings)

    def unwrap(self) -> T:
        """Wert herausgeben. Wirft, wenn die Operation gescheitert ist."""
        if not self.ok or self.value is None:
            raise ValueError(self.message or "Operation ohne Ergebnis")
        return self.value


class Status(Enum):
    """Ampelbewertung eines Rechenergebnisses.

    Die Zuordnung leitet sich immer aus numerischen Grenzwerten der Engine ab,
    nie aus einer Heuristik der Oberflaeche (Spezifikation 23).
    """

    SAFE = "safe"
    MARGINAL = "marginal"
    INSUFFICIENT = "insufficient"

    @property
    def label(self) -> str:
        return {
            Status.SAFE: "Sicher",
            Status.MARGINAL: "Grenzwertig",
            Status.INSUFFICIENT: "Nicht ausreichend",
        }[self]


def classify(actual: float, required: float, marginal_margin_ratio: float = 0.1) -> Status:
    """Ampel aus Ist- und Sollwert.

    SAFE, wenn der Istwert den Sollwert um mehr als marginal_margin_ratio
    uebertrifft; MARGINAL im Band knapp darueber; sonst INSUFFICIENT. Die
    Grenze liegt hier und nicht in der Oberflaeche, damit sie testbar ist.
    """
    if required <= 0.0:
        return Status.SAFE if actual > 0.0 else Status.INSUFFICIENT
    ratio = actual / required
    if ratio >= 1.0 + marginal_margin_ratio:
        return Status.SAFE
    if ratio >= 1.0:
        return Status.MARGINAL
    return Status.INSUFFICIENT


#: Von der besten zur schlechtesten Bewertung. Die Reihenfolge IST die Aussage
#: und steht deshalb hier bei Status und nicht bei einem ihrer Benutzer.
_SCHLECHTER = (Status.SAFE, Status.MARGINAL, Status.INSUFFICIENT)


def worst(*stati: Status) -> Status:
    """Die schlechteste der genannten Bewertungen.

    Ohne Angabe SAFE: auf eine leere Liste von Befunden ist "nichts zu
    beanstanden" die richtige Antwort.

    Gebraucht, wo eine Gesamtbewertung aus Einzelbewertungen entsteht - die
    Vakuumplatte stuft ihr Urteil auf das schlechteste Paket herab. Ein
    Mittelwert waere dort falsch: ein Paket, das faellt, faellt.
    """
    return max(stati, key=_SCHLECHTER.index, default=Status.SAFE)


# ---------------------------------------------------------------------------
# trace.py
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Herkunft eines Ergebnisses
# ---------------------------------------------------------------------------
#
# Fruehere Heimat: dto/common.py.

@dataclass(frozen=True, slots=True)
class CalculationMeta:
    """Herkunftsangaben, die jedes Ergebnis mitfuehrt (Spezifikation 40).

    state_revision ist der Zaehler des Anwendungszustands zum Zeitpunkt der
    Anfrage. Steigt er danach, ist das Ergebnis veraltet - genau daran erkennen
    die Tabs, dass eine Aenderung an den Paketdaten ihre Anzeige
    entwertet hat, ohne dass Signale von Tab zu Tab gereicht werden muessen.
    """

    module_id: str
    algorithm_version: str
    request_id: int = 0
    state_revision: int = 0
    calculation_id: str = ""
    duration_s: float = 0.0
