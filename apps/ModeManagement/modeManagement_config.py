""" Pydantic models for the ModeManagement app config.

    Person is one entry in the ``presence`` list, Vacuum one entry in the ``vacuum`` list,
    AlarmMedia one entry in the ``alarm_media`` list.
    Unknown YAML keys are ignored, so a typo in a key is silently dropped.
"""
from __future__ import annotations
from typing import Optional, List, Literal, Union
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

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
    # False until the tracker has been read in _setup_presence. A missing tracker
    # must not count as somebody home, that would silence the alarm and block away
    home: bool = False

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


class AlarmMedia(BaseModel):
    """One player to start when an alarm sensor is triggered (entry in ``alarm_media``)."""

    model_config = ConfigDict(extra='ignore')

    player: str                                   # media_player that plays the playlist
    playlist: str                                 # media_content_id, played as 'music'
    amp: Optional[str] = None                     # media_player for source and volume
    source: Optional[str] = None                  # select_source on amp before playback
    volume: Optional[float] = None                # volume_level on amp before playback
    normal_volume: Optional[float] = None         # volume_level on amp set back after the alarm

    @model_validator(mode='after')
    def _amp_required(self) -> 'AlarmMedia':
        """source, volume and normal_volume are all sent to amp, so they are useless without it."""
        needs_amp = [
            key for key in ('source', 'volume', 'normal_volume')
            if getattr(self, key) is not None
        ]
        if needs_amp and self.amp is None:
            raise ValueError(f"{', '.join(needs_amp)} need 'amp' to be set")
        return self
