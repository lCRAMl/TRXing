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

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

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
