from __future__ import annotations

from typing import Optional, List, Dict, Literal, Union

from pydantic import BaseModel, Field, validator

Role = Literal['adult', 'kid', 'tenant', 'housekeeper', 'family']


class Person(BaseModel):
    """A lightweight representation of a person used for presence tracking.

    Attributes
    ----------
    person_id:
        The entity ID of the person's presence sensor.
    role:
        The role of the person. Defaults to ``"adult"``.
    outside_switch:
        Optional entity ID of a switch that indicates if the person is outside.
    lock_user:
        Optional user ID for door lock/unlock tracking.
    state:
        Current presence state – either ``"home"`` or ``"away"``. ``None`` means unknown.
    last_lock:
        ``True`` if the person has last locked the door; ``False`` otherwise.
    """

    person_id: str = Field(alias="person")
    role: Role = 'adult'
    outside_switch: Optional[str] = Field(
        None,
        alias="outside_switch",          # the official name
        alias_priority=("outside", "outside_switch")  # accept both
    )
    outside_activated: bool = False
    lock_user: Optional[Union[str, int]] = None
    #state: Optional[str] = None
    home: bool = True
    last_lock: bool = False

    stopMorning: bool = False

    class Config:
        allow_population_by_field_name = True
        use_enum_values = True
        frozen = False

    # ---------------------------------------------------------------------
    # Convenience methods
    # ---------------------------------------------------------------------
    def is_home(self) -> bool:
        """Return ``True`` if the person is ``"home"``."""
        if self.outside_activated:
            return False
        return self.home

    def update_is_outside(self, is_outside: bool) -> None:

        self.outside_activated = is_outside

    def update_state(self, is_home: bool) -> None:

        self.home = is_home

    def update_last_lock(self, locked: bool) -> None:

        self.last_lock = locked

    @property
    def role_count(self) -> int:
        """Return the numeric count for the person's role.

        Historically each person counted as ``1`` toward the aggregate of their role.  The
        property is provided for completeness and mirrors the legacy ``get_role_count``.
        """
        return 1

    @property
    def role_type(self) -> str:
        """Return the role value as a plain string.

        The legacy code used ``get_role_type`` to obtain the role; the Pydantic model keeps
        the same behaviour but returns a plain string instead of the Enum instance.
        """
        return self.role.value

    # ---------------------------------------------------------------------
    # Representation helpers
    # ---------------------------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"Person(person_id='{self.person_id}', role='{self.role}', "
            f"state='{self.state}', last_lock={self.last_lock})"
        )


class Vacuum(BaseModel):
    vacuum: str                        # name / entity_id of the robot
    battery: Optional[str] = None      # optional sensor that reports battery level
    daily_routine: Optional[str] = None # button / switch that starts a routine
    prevent_vacuum: Optional[List[str]] = Field(default_factory=list)
    manual_start: bool = False

    class Config:
        arbitrary_types_allowed = True
