"""Kleine Typen der Jobschicht, die bis in die Oberflaeche sichtbar sind.

Die Oberflaeche bekommt von einem Service niemals den Job selbst - sonst haette
sie Zugriff auf dessen Ausfuehrung und koennte an der Serviceschicht vorbei
arbeiten. Sie bekommt einen JobHandle: Auskunft ueber die Anfrage und die
Moeglichkeit, sie abzubrechen. Mehr braucht sie nicht.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.requests import RequestTicket


@dataclass(frozen=True, slots=True)
class JobHandle:
    """Rueckgabewert von calculate_async(). Enthaelt keinen Qt-Typ."""

    job_id: int
    ticket: RequestTicket
    title: str = ""
    _cancel: Callable[[], None] | None = None

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel()

    @property
    def request_id(self) -> int:
        return self.ticket.request_id

    @property
    def channel(self) -> str:
        return self.ticket.channel


#: Kanalnamen. Jeder Kanal zeigt genau ein aktuelles Ergebnis an.
CHANNEL_PALLET = "pallet"
CHANNEL_VACUUM = "vacuum"
