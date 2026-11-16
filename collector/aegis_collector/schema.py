"""Telemetry event schema.

Every event the game server emits is one JSON object per line (JSONL).
The ``type`` field selects the event kind. Unknown fields are rejected so a
buggy or malicious sender can't smuggle extra data into storage.

Conventions
-----------
- ``ts``       server time in milliseconds since the match started
- ``match_id`` opaque id chosen by the server for one match
- ``cn``       AssaultCube "client number" — the player's slot on the server
- ``yaw``      horizontal view angle in degrees, [0, 360)
- ``pitch``    vertical view angle in degrees, [-90, 90]
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Vec3(_Strict):
    x: float
    y: float
    z: float


class _Event(_Strict):
    ts: float = Field(ge=0)
    match_id: str = Field(min_length=1, max_length=64)


class PlayerJoin(_Event):
    type: Literal["player_join"]
    cn: int = Field(ge=0, le=255)
    name: str = Field(min_length=1, max_length=32)


class PlayerLeave(_Event):
    type: Literal["player_leave"]
    cn: int = Field(ge=0, le=255)


class Spawn(_Event):
    type: Literal["spawn"]
    cn: int = Field(ge=0, le=255)
    pos: Vec3


class Tick(_Event):
    """Periodic player state: where they are and where they're looking."""

    type: Literal["tick"]
    cn: int = Field(ge=0, le=255)
    pos: Vec3
    yaw: float = Field(ge=0, lt=360)
    pitch: float = Field(ge=-90, le=90)
    alive: bool = True


class Shot(_Event):
    """A weapon was fired. ``target`` is the point the shot travelled to."""

    type: Literal["shot"]
    cn: int = Field(ge=0, le=255)
    weapon: str = Field(min_length=1, max_length=16)
    origin: Vec3
    target: Vec3


class Damage(_Event):
    type: Literal["damage"]
    attacker: int = Field(ge=0, le=255)
    target: int = Field(ge=0, le=255)
    weapon: str = Field(min_length=1, max_length=16)
    amount: int = Field(ge=0, le=1000)
    headshot: bool = False


class Kill(_Event):
    type: Literal["kill"]
    attacker: int = Field(ge=0, le=255)
    victim: int = Field(ge=0, le=255)
    weapon: str = Field(min_length=1, max_length=16)
    headshot: bool = False


Event = Annotated[
    Union[PlayerJoin, PlayerLeave, Spawn, Tick, Shot, Damage, Kill],
    Field(discriminator="type"),
]

EventAdapter: TypeAdapter[Event] = TypeAdapter(Event)


def actor_of(event: Event) -> int | None:
    """The player who *did* the thing — used for indexing."""
    for attr in ("cn", "attacker"):
        value = getattr(event, attr, None)
        if value is not None:
            return value
    return None
