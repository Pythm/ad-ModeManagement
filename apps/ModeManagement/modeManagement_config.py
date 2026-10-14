""" Pydantic models for the ModeManagement app config.

    Person is one entry in the ``presence`` list, Vacuum one entry in the ``vacuum`` list.
    Unknown YAML keys are ignored, so a typo in a key is silently dropped.
"""
from __future__ import annotations
from typing import Optional, List, Literal, Union
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# 'family' (extended family) behaves like 'adult', except that the optional 'family'
# light mode is the normal mode when family is home without an adult.
# See MAIN_HOUSE_ROLES and ADULT_ROLES in modeManagement.
Role = Literal['adult', 'kid', 'tenant', 'housekeeper', 'family']


class Person(BaseModel):
    """A lightweight representation of a person used for presence tracking.

    Attributes
    ----------
    person_id:
        The entity ID of the person (or device tracker). YAML key ``person``.
    role:
        The role of the person. Defaults to ``"adult"``.
    outside_switch:
        Optional entity ID of a switch that marks the person as outside.
        YAML key ``outside_switch`` or ``outside``.
    outside_activated:
        ``True`` while the outside switch is on.
    lock_user:
        Optional user ID for door lock/unlock tracking.
    home:
        ``True`` when the tracker says ``home``.
    stopMorning:
        If ``True`` the morning mode ends when this person leaves and someone else is home.
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    person_id: str = Field(alias="person")
    role: Role = 'adult'

    # Both ``outside_switch`` and the old ``outside`` are accepted in YAML
    outside_switch: Optional[str] = Field(None, validation_alias=AliasChoices('outside_switch', 'outside'))

    outside_activated: bool = False
    lock_user: Optional[Union[str, int]] = None
    home: bool = True

    stopMorning: bool = False

    # ---------------------------------------------------------------------
    # Convenience methods
    # ---------------------------------------------------------------------
    def is_home(self) -> bool:
        """Return ``True`` if the person is home and not marked as outside."""
        if self.outside_activated:
            return False
        return self.home

    def update_is_outside(self, is_outside: bool) -> None:
        """Set by the outside switch listener."""
        self.outside_activated = is_outside

    def update_state(self, is_home: bool) -> None:
        """Set by the tracker listener. ``True`` only when the tracker says ``home``."""
        self.home = is_home

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"Person(person_id='{self.person_id}', role='{self.role}', "
            f"home={self.home}, outside={self.outside_activated})"
        )


class Vacuum(BaseModel):
    """One robot vacuum cleaner."""

    model_config = ConfigDict(extra='ignore')

    vacuum: str                                   # entity_id of the robot
    battery: Optional[str] = None                 # optional sensor that reports battery level
    daily_routine: Optional[str] = None           # button / switch / script that starts a routine
    min_battery: Optional[float] = None           # overrides the app wide minimum battery level
    prevent_vacuum: List[str] = Field(default_factory=list)

    # Runtime state, not configuration
    manual_start: bool = False                    # Cleaning was not started by the app
    started: bool = False                         # Started by the app and not yet docked
