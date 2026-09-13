"""Schutz vor veralteten Ergebnissen (Spezifikation 08).

Das Problem: bei aktivem Debounce laufen mehrere Berechnungen zeitlich
ueberlappend. Sie kommen nicht zwangslaeufig in der Reihenfolge zurueck, in der
sie gestartet wurden - eine kleine Palette rechnet schneller als die grosse
davor. Ohne Gegenmassnahme ueberschreibt das Ergebnis der aelteren Anfrage die
Anzeige der neueren, und der Benutzer sieht Zahlen zu Eingaben, die er laengst
geaendert hat.

Die Loesung besteht aus zwei Teilen, die zusammengehoeren:

    CancellationToken   bricht ab, was noch laeuft
    RequestGate         verwirft, was schon fertig ist, aber ueberholt wurde

Der Abbruch allein genuegt nicht: zwischen "abgebrochen" und "Ergebnis liegt
bereits im Signalpuffer" gibt es ein Zeitfenster, das sich nicht schliessen
laesst. Die Torpruefung beim Empfang schliesst es.

Bewusst Qt-frei und ohne Threadbezug, damit die Regel ohne QApplication
pruefbar ist.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestTicket:
    """Ausweis einer Anfrage. Wandert mit dem Auftrag in den Worker und mit dem
    Ergebnis zurueck."""

    channel: str
    request_id: int
    state_revision: int = 0


class RequestGate:
    """Vergibt aufsteigende Nummern je Kanal und prueft zurueckkommende.

    Ein Kanal ist eine Anzeige, die genau ein aktuelles Ergebnis zeigt - etwa
    "pallet" oder "vacuum". Verschiedene Kanaele stoeren sich nicht.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._issued: dict[str, int] = {}
        self._accepted: dict[str, int] = {}

    def issue(self, channel: str, state_revision: int = 0) -> RequestTicket:
        """Neue, hoehere Nummer fuer diesen Kanal."""
        with self._lock:
            next_id = self._issued.get(channel, 0) + 1
            self._issued[channel] = next_id
            return RequestTicket(channel=channel, request_id=next_id, state_revision=state_revision)

    def is_current(self, ticket: RequestTicket) -> bool:
        """Ob dieses Ergebnis noch das juengste seines Kanals ist."""
        with self._lock:
            return self._issued.get(ticket.channel, 0) == ticket.request_id

    def accept(self, ticket: RequestTicket) -> bool:
        """Ergebnis annehmen, wenn es aktuell ist.

        Merkt sich zusaetzlich die zuletzt angenommene Nummer: trifft ein noch
        aelteres Ergebnis nachtraeglich ein, wird auch das verworfen, selbst
        wenn zwischenzeitlich keine neue Anfrage mehr gestellt wurde.
        """
        with self._lock:
            if self._issued.get(ticket.channel, 0) != ticket.request_id:
                return False
            if ticket.request_id <= self._accepted.get(ticket.channel, 0):
                return False
            self._accepted[ticket.channel] = ticket.request_id
            return True

    def latest(self, channel: str) -> int:
        with self._lock:
            return self._issued.get(channel, 0)

    def invalidate(self, channel: str) -> None:
        """Alle laufenden Anfragen dieses Kanals entwerten, ohne eine neue zu
        starten. Wird gebraucht, wenn die Eingabe ungueltig wird."""
        with self._lock:
            self._issued[channel] = self._issued.get(channel, 0) + 1
