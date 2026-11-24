"""Callback data of every card button: ``q:<action>:<batch>[:<item>[:<number>]]``."""

from __future__ import annotations

from dataclasses import dataclass

PREFIX = "q"

CANCEL = "x"  # stop the batch
RETRY_FAILED = "r"  # requeue the batch's failed and unmatched items
SUMMARY = "s"  # show the batch summary
LIST = "l"  # show the track list (number = page)
ITEM = "i"  # show one track
PICKER = "p"  # show the copies found for a track (number = page)
GET = "g"  # fetch a chosen copy (number = index)
UNDO = "u"  # remove a saved track from the library
SEND = "f"  # send the saved file to the chat
AGAIN = "a"  # fetch again, skipping the owned check
RETRY = "t"  # run one track through the queue again
SKIP = "k"  # leave a track that waits for a decision
KEEP = "o"  # keep a saved copy the audio check doubts
TOUR = "w"  # go through the tracks waiting for a pick, one picker after another
SKIP_ALL = "z"  # let go of every track still waiting for a pick


@dataclass(frozen=True)
class Action:
    name: str
    batch_id: int
    item_id: int = 0
    number: int = 0


def encode(name: str, batch_id: int, item_id: int = 0, number: int = 0) -> str:
    return f"{PREFIX}:{name}:{batch_id}:{item_id}:{number}"


def decode(data: str) -> Action | None:
    parts = data.split(":")
    if len(parts) != 5 or parts[0] != PREFIX:
        return None
    try:
        return Action(parts[1], int(parts[2]), int(parts[3]), int(parts[4]))
    except ValueError:
        return None
