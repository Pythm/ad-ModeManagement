""" Vacuum cleaner control

    Starts robot vacuum cleaners when told to and sends them back to their base when told to.
    Used in two ways:

    * Embedded: ModeManagement creates ``VacuumControl`` itself when it has a ``vacuum:`` setting.
    * Stand-alone: the ``VacuumManager`` app listens for the ``VACUUM_CONTROL`` event
      (``action: start`` or ``action: stop``), so ModeManagement or any Home Assistant
      automation can control the vacuums.

    @Pythm / https://github.com/Pythm
"""
__version__ = "0.1.0"

from typing import Any, Dict, List, Optional

from appdaemon import adbase as ad

from modeManagement_config import Vacuum

DOCKED_STATES = ('docked', 'charging')
# Entity states that carry no information. Shared with modeManagement
UNAVAILABLE_STATES = (None, 'unavailable', 'unknown')


def _as_list(value) -> list:
    """ Wraps a single value in a list. None gives an empty list. Shared with modeManagement. """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


class VacuumControl:
    """ Start and stop robot vacuums. No AppDaemon app, so it can be used by other apps. """

    def __init__(self, ADapi, namespace: str, vacuums: list, global_prevent: Optional[list] = None, min_battery: float = 40) -> None:
        """ Builds the Vacuum models from the app args, reads each state once and listens for docking. """
        self.ADapi = ADapi
        self.namespace = namespace
        self.min_battery = min_battery
        self.vacuums: List[Vacuum] = []
        self._warned_battery: set = set()

        global_prevent = [str(e) for e in _as_list(global_prevent)]
        for item in _as_list(vacuums):
            vacuum_dict: Dict[str, Any]
            if isinstance(item, str):
                vacuum_dict = {'vacuum': item}
            elif isinstance(item, dict):
                vacuum_dict = dict(item)  # Copy, so the app args are not changed
            else:
                self.ADapi.log(
                    f"Vacuum must be defined as a string or a dictionary. vacuum: {item}",
                    level='WARNING'
                )
                continue

            if 'prevent_vacuum' not in vacuum_dict:
                vacuum_dict['prevent_vacuum'] = global_prevent
            else:
                vacuum_dict['prevent_vacuum'] = [str(e) for e in _as_list(vacuum_dict['prevent_vacuum'])]

            try:
                robot = Vacuum(**vacuum_dict)
            except Exception as exc:
                self.ADapi.log(f"Could not create Vacuum instance from {vacuum_dict}. Exception: {exc}", level='ERROR')
                continue

            state = self.ADapi.get_state(robot.vacuum, namespace=self.namespace)
            if state is None:
                self.ADapi.log(f"Vacuum {robot.vacuum} does not exist in Home Assistant", level='WARNING')
            self.vacuums.append(robot)
            self.ADapi.listen_state(self._state_changed, robot.vacuum, namespace=self.namespace, robot=robot)

    def _state_changed(self, entity, attribute, old, new, **kwargs) -> None:
        """ Back on the dock: the next cleaning round starts from a clean slate. """
        if new in DOCKED_STATES:
            robot = kwargs['robot']
            robot.manual_start = False
            robot.started = False

    def stop(self) -> None:
        """ Sends vacuums that the app started (or found cleaning at restart) back to the base. """
        for robot in self.vacuums:
            if robot.manual_start:
                continue
            if self.ADapi.get_state(robot.vacuum, namespace=self.namespace) == 'cleaning':
                self.ADapi.call_service('vacuum/return_to_base',
                    entity_id=robot.vacuum,
                    namespace=self.namespace
                )
            robot.started = False

    def start(self) -> None:
        """ Starts docked vacuums when no prevent entity is on and the battery is high enough. """
        for robot in self.vacuums:
            state = self.ADapi.get_state(robot.vacuum, namespace=self.namespace)
            if state in UNAVAILABLE_STATES:
                continue
            if state not in DOCKED_STATES:
                # Cleaning on its own or started by us earlier
                if not robot.started:
                    robot.manual_start = True
                continue

            robot.manual_start = False
            if self._prevented(robot):
                continue
            if not self._enough_battery(robot):
                continue

            self._start_robot(robot)
            robot.started = True

    def _prevented(self, robot: Vacuum) -> bool:
        """ True if any prevent entity of the robot is on. """
        for item in robot.prevent_vacuum:
            if self.ADapi.get_state(item, namespace=self.namespace) == 'on':
                self.ADapi.log(f"{robot.vacuum} not started. {item} is on", level='DEBUG')
                return True
        return False

    def _start_robot(self, robot: Vacuum) -> None:
        """ Starts by the daily routine entity if provided, else the full program. """
        routine = robot.daily_routine
        if routine is None:
            self.ADapi.call_service('vacuum/start', entity_id=robot.vacuum, namespace=self.namespace)
            return

        domain = routine.split('.')[0]
        if domain in ('button', 'input_button'):
            service = f'{domain}/press'
        elif domain == 'script':
            service = 'script/turn_on'
        else:
            service = 'homeassistant/turn_on'
        try:
            self.ADapi.call_service(service, entity_id=routine, namespace=self.namespace)
        except Exception as exc:
            self.ADapi.log(f"Not able to start {routine} for {robot.vacuum}: {exc}", level='WARNING')

    def _enough_battery(self, robot: Vacuum) -> bool:
        """ True if the battery is above the robot's or the app wide minimum. """
        level = self._battery_level(robot)
        if level is None:
            return True  # Unknown level is logged once, the vacuum itself refuses to start if too low
        limit = robot.min_battery if robot.min_battery is not None else self.min_battery
        if level <= limit:
            self.ADapi.log(f"{robot.vacuum} not started. Battery {level}% is not above {limit}%", level='DEBUG')
            return False
        return True

    def _battery_level(self, robot: Vacuum) -> Optional[float]:
        """ Battery sensor first, then the battery_level attribute. None if not found. """
        sources = []
        if robot.battery is not None:
            sources.append((robot.battery, None))
        sources.append((robot.vacuum, 'battery_level'))
        for entity, attribute in sources:
            value = self.ADapi.get_state(entity, attribute=attribute, namespace=self.namespace) \
                if attribute else self.ADapi.get_state(entity, namespace=self.namespace)
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        if robot.vacuum not in self._warned_battery:
            self._warned_battery.add(robot.vacuum)
            self.ADapi.log(
                f"Not able to get battery level from {robot.vacuum}. "
                "Try defining 'battery: sensor.vacuum_battery' for your robot",
                level='WARNING'
            )
        return None


class VacuumManager(ad.ADBase):
    """ Stand-alone app: controls vacuums from the VACUUM_CONTROL event. """

    def initialize(self) -> None:
        """ Builds the VacuumControl from the app args and listens for the control event. """
        self.ADapi = self.get_ad_api()
        self.HASS_namespace:str = self.args.get('HASS_namespace', 'default')

        self.control = VacuumControl(
            self.ADapi,
            self.HASS_namespace,
            self.args.get('vacuum', []),
            self.args.get('prevent_vacuum', []),
            self.args.get('min_battery', 40),
        )
        if not self.control.vacuums:
            self.ADapi.log(f"{self.name}: No vacuum configured", level='WARNING')

        self.ADapi.listen_event(self._control_event,
            self.args.get('vacuum_event', 'VACUUM_CONTROL'),
            namespace=self.HASS_namespace
        )

    def _control_event(self, event_name, data, **kwargs) -> None:
        """ Event callback: 'action' is start or stop. """
        action = data.get('action')
        if action == 'start':
            self.control.start()
        elif action == 'stop':
            self.control.stop()
        else:
            self.ADapi.log(f"{self.name}: Unknown vacuum action {action}. Use start or stop", level='WARNING')
