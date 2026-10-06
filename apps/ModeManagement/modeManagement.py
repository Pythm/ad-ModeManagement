""" Mode Event Management

    Presence and time based house modes. Works together with Lightwand.

    @Pythm / https://github.com/Pythm
"""
__version__ = "0.3.1"

import json
from typing import Any, Dict, List, Optional, Tuple

from appdaemon import adbase as ad

from translations_lightmodes import translations

from modeManagement_config import Person
from vacuum_manager import VacuumControl

UNAVAILABLE_STATES = (None, 'unavailable', 'unknown')
# States of a triggered alarm sensor: binary sensors, switches and covers/doors
ALARM_STATES = ('on', 'open', 'opening')
ALARM_NOTIFICATION_PAUSE = 600  # seconds between alarm notifications


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _parse_mode_and_room(mode: str) -> Tuple[str, Optional[str]]:
    """ Splits 'off_livingroom' into ('off', 'livingroom'). """
    if '_' not in mode:
        return mode, None
    modename, roomname = mode.split('_', 1)
    return modename, roomname


class ModeManagement(ad.ADBase):

    def initialize(self):
        self.ADapi = self.get_ad_api()

        # Namespaces for HASS and MQTT
        self.HASS_namespace:str = self.args.get('HASS_namespace', 'default')
        self.MQTT_namespace:str = self.args.get('MQTT_namespace', 'mqtt')

        # Set up notification
        self.notify_receiver:list = _as_list(self.args.get('notify_receiver', []))
        self.notify_app_name = self.args.get('notify_app', None)
        self.notify_on_alarm:bool = True
        self.media_on_alarm:bool = True
        self._alarm_reset_timer = None
        self._media_reset_timer = None

        # Times
        self.morning_runtime:str = self._time_arg('morning_start_listen_time', '06:00:00')
        self.execute_morning:str = self._time_arg('execute_morning_at', '10:00:00')
        self.night_runtime:str = self._time_arg('night_start_listen_time', '22:00:00')
        self.execute_night:str = self._time_arg('execute_night_at', '02:00:00')
        self.vacuum_earliest:str = self._time_arg('vacuum_earliest_start', self.morning_runtime)
        self.vacuum_latest:str = self._time_arg('vacuum_latest_start', '18:00:00')

        # Vacation switch from Home Assistant
        self.vacation:bool = False
        vacation_entity = self.args.get('away_state', None) # Old name for vacation
        if vacation_entity is None:
            vacation_entity = self.args.get('vacation', None)
        if vacation_entity is None:
            # Default entity if it exists
            if self.ADapi.get_state('input_boolean.vacation', namespace = self.HASS_namespace) is not None:
                vacation_entity = 'input_boolean.vacation'
        if vacation_entity is not None:
            state = self.ADapi.get_state(vacation_entity, namespace = self.HASS_namespace)
            if state is None:
                self.ADapi.log(f"{self.name}: vacation entity {vacation_entity} does not exist", level = 'WARNING')
            self.vacation = state == 'on'
            self.ADapi.listen_state(self._vacation_changed, vacation_entity,
                namespace = self.HASS_namespace
            )

        # Holidays. Only loaded when country_code is set
        self.holidays = None
        country_code = self.args.get('country_code', None)
        if country_code:
            try:
                import holidays as holidays_lib
                self.holidays = holidays_lib.country_holidays(str(country_code).upper())
            except ImportError:
                self.ADapi.log(
                    f"{self.name}: Python package 'holidays' is not installed. Will fire morning every day.",
                    level = 'WARNING'
                )
            except Exception as exc:
                self.ADapi.log(
                    f"{self.name}: Could not find holidays for {country_code}. Will fire morning every day. {exc}",
                    level = 'WARNING'
                )

        # Presence detection and HA switch for manual override
        self.presence: List[Person] = []
        for entry in _as_list(self.args.get('presence', [])):
            try:
                person = entry if isinstance(entry, Person) else Person(**entry)
            except Exception as exc:
                self.ADapi.log(f"{self.name}: Could not use presence entry {entry}. {exc}", level = 'ERROR')
                continue
            self.presence.append(person)

        self._person_by_entity:Dict[str, Person] = {}
        self._person_by_switch:Dict[str, Person] = {}
        for person in self.presence:
            self._person_by_entity[person.person_id] = person
            tracker_state = self.ADapi.get_state(person.person_id, namespace = self.HASS_namespace)
            if tracker_state is None:
                self.ADapi.log(f"{self.name}: {person.person_id} does not exist", level = 'WARNING')
            person.update_state(is_home = tracker_state == 'home')
            self.ADapi.listen_state(self._presenceChange, person.person_id, namespace = self.HASS_namespace)

            if person.outside_switch is not None:
                self._person_by_switch[person.outside_switch] = person
                switch_state = self.ADapi.get_state(person.outside_switch, namespace = self.HASS_namespace)
                if switch_state is None:
                    self.ADapi.log(f"{self.name}: {person.outside_switch} does not exist", level = 'WARNING')
                person.update_is_outside(is_outside = switch_state == 'on')
                self.ADapi.listen_state(self._outsideChange, person.outside_switch, namespace = self.HASS_namespace)

        self.keep_mode_when_outside = self.args.get('keep_mode_when_outside', None)
        self.delay_before_setting_away = self.args.get('delay_before_setting_away', 0)
        self.away_handler = None

        # Set up notification if sensor is activated when no one is home
        self.alarmsensors:List[str] = []
        self.alarm_cameras:Dict[str, str] = {}
        self.alarm_no_media:set = set() # Sensors that only notify, without alarm_media
        default_camera = self.args.get('alarm_camera', None)
        for item in _as_list(self.args.get('alarmsensors', [])):
            if isinstance(item, dict):
                sensor = item.get('sensor', None)
                camera = item.get('camera', default_camera)
                if not item.get('play_media', True):
                    self.alarm_no_media.add(sensor)
            else:
                sensor = item
                camera = default_camera
            if not sensor:
                self.ADapi.log(f"{self.name}: alarmsensors entry {item} has no sensor", level = 'WARNING')
                continue
            self.alarmsensors.append(sensor)
            if camera:
                self.alarm_cameras[sensor] = camera
        self.sensor_handle:list = []
        self.alarm_active:bool = False
        self.alarm_media = _as_list(self.args.get('alarm_media', []))

        # Optional: save snapshots to a folder with utils_apps from Pythm_AppdaemonApps
        # Without it the camera picture is fetched by the mobile app from the camera entity.
        self.snapshot_directory = self.args.get('snapshot_directory', None)
        self.snapshot_keep_days = self.args.get('snapshot_keep_days', None)
        self._save_image = None
        if self.snapshot_directory:
            try:
                from utils_apps import save_image_with_timestamp
                self._save_image = save_image_with_timestamp
            except ImportError:
                self.ADapi.log(
                    f"{self.name}: snapshot_directory is set, but utils_apps from Pythm_AppdaemonApps "
                    "is not installed. Using the camera proxy instead.",
                    level = 'WARNING'
                )

        # Vacuum robots. Either handled here or by the VacuumManager app through an event
        self.vacuum_control:Optional[VacuumControl] = None
        if self.args.get('vacuum', None):
            self.vacuum_control = VacuumControl(
                self.ADapi,
                self.HASS_namespace,
                self.args['vacuum'],
                self.args.get('prevent_vacuum', []),
                self.args.get('vacuum_min_battery', 40),
            )
        self.vacuum_event = self.args.get('vacuum_event', None)

        # MQTT Door lock
        self.MQTT_door_lock:list = _as_list(self.args.get('MQTT_door_lock', []))
        self.unlock_door_when_home:bool = bool(self.args.get('unlock_door_when_home', False))
        self.mqtt = None
        self._lock_timer = None
        self._unlock_timer = None
        if self.MQTT_door_lock:
            self.mqtt = self.get_plugin_api("MQTT")
            if self.mqtt is None:
                self.ADapi.log(f"{self.name}: MQTT plugin not found. Door lock is disabled.", level = 'WARNING')
                self.MQTT_door_lock = []
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_subscribe(door)
            self.mqtt.listen_event(self.MQTT_doorlock_event, "MQTT_MESSAGE",
                topic = door,
                namespace = self.MQTT_namespace
            )

        # Update current mode to a Home Assistant input_text
        self.haLightModeText = self.args.get('HALightModeText', None)

        # Setting data
        self.current_MODE:str = self._initial_mode()
        if self.current_MODE == translations.away:
            self.start_alarm()

        # Morning routine
        self.morning_handler:list = []
        self.morning_sensors = _as_list(self.args.get('morning_sensors', []))
        self.turn_on_in_the_morning = _as_list(self.args.get('turn_on_in_the_morning', []))

        self.ADapi.run_daily(self._waiting_for_morning, self.morning_runtime)
        if (
            self.ADapi.now_is_between(self.morning_runtime, self.execute_morning)
            and self.current_MODE.startswith(translations.night)
        ):
            self._waiting_for_morning()
        self.ADapi.run_daily(self._good_day_now, self.execute_morning)

        self.morning_to_day:str = self.execute_morning
        if self.args.get('morning_to_normal', None) is not None:
            morning_to_normal = self._time_arg('morning_to_normal', self.execute_morning)
            self.morning_to_day = morning_to_normal
            self.ADapi.run_daily(self._changeMorningToDay, morning_to_normal)

        # Night routine
        self.night_handler:list = []
        self.turn_off_at_night = _as_list(self.args.get('turn_off_at_night', []))
        self.night_sensors = _as_list(self.args.get('night_sensors', []))

        self.ADapi.run_daily(self._waiting_for_night, self.night_runtime)
        if (
            self.ADapi.now_is_between(self.night_runtime, self.execute_night)
            and self.current_MODE != translations.night
        ):
            self._waiting_for_night()
        self.ADapi.run_daily(self._good_night_now, self.execute_night)

        # Listens for mode events
        self.ADapi.listen_event(self.mode_event, translations.MODE_CHANGE, namespace = self.HASS_namespace)

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------
    def _time_arg(self, key:str, default:str) -> str:
        """ Returns the time from args if AppDaemon can parse it, else the default. """
        value = self.args.get(key, default)
        try:
            self.ADapi.parse_time(value)
        except Exception as exc:
            self.ADapi.log(
                f"{self.name}: Not able to convert {key}: {value}. Using {default}. Error: {exc}",
                level = 'WARNING'
            )
            return default
        return value

    def _initial_mode(self) -> str:
        """ Mode at startup. Vacation is away, then the input_text, else the time of day. """
        if self.vacation:
            return translations.away
        if self.haLightModeText:
            text = self.ADapi.get_state(self.haLightModeText, namespace = self.HASS_namespace)
            if text not in UNAVAILABLE_STATES and text != '' and text != translations.fire:
                return str(text)
        if self.ADapi.now_is_between(self.execute_night, self.morning_runtime):
            return translations.night
        return translations.automagical

    # ------------------------------------------------------------------
    # Presence helpers. Counted from the persons, so the numbers cannot drift
    # ------------------------------------------------------------------
    def _count(self, *roles:str) -> int:
        return sum(1 for person in self.presence if person.role in roles and person.is_home())

    def _anyone_at_main_house_home(self) -> bool:
        return self._count('adult', 'kid', 'family') > 0

    def _cancel_timer(self, handle) -> None:
        if handle is not None and self.ADapi.timer_running(handle):
            self.ADapi.cancel_timer(handle, silent = True)

    def _notify(self, **kwargs) -> None:
        """ Sends notification with the notify app from args or Home Assistant notify. """
        if self.notify_app_name is not None:
            notify_app = self.ADapi.get_app(self.notify_app_name)
            if notify_app is not None:
                notify_app.send_notification(**kwargs)
                return
            self.ADapi.log(
                f"{self.name}: notify_app {self.notify_app_name} not found. Using Home Assistant notify.",
                level = 'WARNING'
            )
        message_title = kwargs.get('message_title', 'Home Assistant')
        data = kwargs.get('data', {'clickAction' : 'noAction'})
        for receiver in _as_list(kwargs.get('message_recipient', self.notify_receiver)):
            self.ADapi.call_service(f'notify/{receiver}',
                title = message_title,
                message = kwargs['message'],
                data = data,
                namespace = self.HASS_namespace
            )

    def _fire_mode(self, mode:str) -> None:
        self.ADapi.fire_event(translations.MODE_CHANGE, mode = mode, namespace = self.HASS_namespace)

    # ------------------------------------------------------------------
    # Mode events
    # ------------------------------------------------------------------
    def mode_event(self, event_name, data, **kwargs) -> None:
        """ Listens to mode events and reacts on night, morning, normal.
            Also updates the input_text with mode.
        """
        mode = data.get('mode', None)
        if not isinstance(mode, str) or not mode:
            return
        modename, roomname = _parse_mode_and_room(mode)

        ## Turning off one room during morning ## Do Nothing
        if (
            self.current_MODE == translations.morning
            and self.ADapi.now_is_between(self.morning_runtime, self.execute_morning)
            and modename == translations.off
            and roomname is not None
        ):
            return

        ## Transition from night to morning ##
        if (
            self.current_MODE.startswith(translations.night)
            and self.ADapi.now_is_between(self.morning_runtime, self.execute_morning)
            and (modename == translations.automagical
            or modename == translations.morning)
        ):
            for item in self.turn_on_in_the_morning:
                if self.ADapi.get_state(item, namespace = self.HASS_namespace) == 'off':
                    self.ADapi.call_service('homeassistant/turn_on',
                        entity_id = item,
                        namespace = self.HASS_namespace
                    )
            self._cancel_listening_for_morning()
            self.disableRelockDoor()

        ## Transition to main "Night" mode ##
        if (
            roomname is None
            and modename.startswith(translations.night)
            and self.ADapi.now_is_between(self.night_runtime, self.execute_night)
        ):
            for item in self.turn_off_at_night:
                if self.ADapi.get_state(item, namespace = self.HASS_namespace) == 'on':
                    self.ADapi.call_service('homeassistant/turn_off',
                        entity_id = item,
                        namespace = self.HASS_namespace
                    )

            self._cancel_listening_for_night()

            self.enableRelockDoor()

        ## Main "Away" mode ##
        if mode == translations.away:
            self.start_alarm()

            self.enableRelockDoor()

        ## False alarm from your fire detection app ##
        elif mode == translations.false_alarm:
            self._fire_mode(self.current_MODE)

        ## Fire detected from your fire detection app ##
        ## Updates input_text but not the current_MODE so it can go back to previous if false alarm
        elif mode == translations.fire:
            if self.haLightModeText:
                self.ADapi.call_service('input_text/set_value',
                    value = translations.fire,
                    entity_id = self.haLightModeText,
                    namespace = self.HASS_namespace
                )
            return

        # Store mode to current_MODE
        if roomname is None:
            if modename == translations.reset:
                self.current_MODE = translations.automagical
            else:
                self.current_MODE = modename

            # Update input_text do display in GUI
            if self.haLightModeText:
                self.ADapi.call_service('input_text/set_value',
                    value = self.current_MODE,
                    entity_id = self.haLightModeText,
                    namespace = self.HASS_namespace
                )

    # ------------------------------------------------------------------
    # Morning and Night handling
    # ------------------------------------------------------------------
    def _cancel_handles(self, handles:list) -> None:
        for handle in handles:
            try:
                self.ADapi.cancel_listen_state(handle, silent = True)
            except Exception as exc:
                self.ADapi.log(f"Not possible to stop {handle}. Exception: {exc}", level = 'DEBUG')

    def _cancel_listening_for_morning(self) -> None:
        """ Cancels the listen for morning handler. """
        self._cancel_handles(self.morning_handler)
        self.morning_handler = []

    def _cancel_listening_for_night(self) -> None:
        """ Cancels the listen for night handler. """
        self._cancel_handles(self.night_handler)
        self.night_handler = []

    def _waiting_for_morning(self, **kwargs) -> None:
        """ Starts listening for sensors activating morning/normal mode. """
        if self.current_MODE != translations.away:
            if self.keep_mode_when_outside is not None:
                self.ADapi.call_service('homeassistant/turn_off',
                    entity_id = self.keep_mode_when_outside,
                    namespace = self.HASS_namespace
                )

            self._cancel_listening_for_morning()
            for sensor in self.morning_sensors:
                handler = self.ADapi.listen_state(self._waking_up, sensor,
                    new = 'on',
                    namespace = self.HASS_namespace
                )
                self.morning_handler.append(handler)

    def _waiting_for_night(self, **kwargs) -> None:
        """ Starts listening for sensors activating night. """
        self._cancel_listening_for_night()
        for sensor in self.night_sensors:
            handler = self.ADapi.listen_state(self._going_to_bed, sensor,
                new = 'on',
                namespace = self.HASS_namespace
            )
            self.night_handler.append(handler)

    def _changeMorningToDay(self, **kwargs) -> None:
        """ Changes mode from morning to normal at given time. """
        if self.current_MODE == translations.morning:
            self._fire_mode(translations.automagical)

    def _waking_up(self, entity, attribute, old, new, **kwargs) -> None:
        """ Reacts to morning sensors """
        if (
            self.ADapi.now_is_between(self.morning_runtime, self.morning_to_day)
            and not self._is_holiday()
        ):
            self._fire_mode(translations.morning)
        else:
            self._fire_mode(translations.automagical)
        self._cancel_listening_for_morning()

    def _going_to_bed(self, entity, attribute, old, new, **kwargs) -> None:
        """ Reacts to night sensors """
        if self.current_MODE != translations.away:
            self._fire_mode(translations.night)
        self._cancel_listening_for_night()

    def _good_day_now(self, **kwargs) -> None:
        """ Change to normal day light at this time if mode is night or morning. """
        if (
            self.current_MODE.startswith(translations.night)
            or self.current_MODE == translations.morning
        ):
            self._fire_mode(translations.automagical)
        self._cancel_listening_for_morning()

    def _good_night_now(self, **kwargs) -> None:
        """ Change to night at the given time. """
        if (
            self.current_MODE != translations.away
            and self.current_MODE != translations.night
        ):
            self._fire_mode(translations.night)
        self._cancel_listening_for_night()

    def _is_holiday(self) -> bool:
        """ True on holidays and weekends. Always False without country_code. """
        if self.holidays is None:
            return False
        today = self.ADapi.get_now().date()
        return today in self.holidays or today.weekday() > 4

    # ------------------------------------------------------------------
    # Door functions
    # ------------------------------------------------------------------
    def enableRelockDoor(self) -> None:
        """ Enables auto relock and locks the door after a few seconds. """
        if not self.MQTT_door_lock:
            return
        self._cancel_timer(self._unlock_timer)
        self._unlock_timer = None
        if self._lock_timer is not None and self.ADapi.timer_running(self._lock_timer):
            return # Already on its way
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set/auto_relock",
                payload = "true",
                namespace = self.MQTT_namespace
            )
        self._lock_timer = self.ADapi.run_in(self.lockDoor, 10)

    def lockDoor(self, **kwargs) -> None:
        """ Locks the MQTT door. """
        self._lock_timer = None
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set",
                payload = "LOCK",
                namespace = self.MQTT_namespace
            )

    def disableRelockDoor(self) -> None:
        """ Disables auto relock and unlocks the door. Only with unlock_door_when_home. """
        if not self.MQTT_door_lock or not self.unlock_door_when_home:
            return
        self._cancel_timer(self._lock_timer)
        self._lock_timer = None
        if self._unlock_timer is not None and self.ADapi.timer_running(self._unlock_timer):
            return # Already on its way
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set/auto_relock",
                payload = "false",
                namespace = self.MQTT_namespace
            )
        self._unlock_timer = self.ADapi.run_in(self.unlockDoor, 3)

    def unlockDoor(self, **kwargs) -> None:
        """ Unlocks the MQTT door. """
        self._unlock_timer = None
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set",
                payload = "UNLOCK",
                namespace = self.MQTT_namespace
            )

    def MQTT_doorlock_event(self, event_name, data, **kwargs) -> None:
        """ Listens to MQTT door events. """
        try:
            payload = json.loads(data['payload'])
        except Exception as e:
            self.ADapi.log(f"Could not get payload from topic for {data}. Exception: {e}", level = 'DEBUG')
            return
        if not isinstance(payload, dict):
            return
        if (
            payload.get('state') == 'UNLOCK'
            and payload.get('last_unlock_source') != 'self'
        ):
            unlock_user = payload.get('last_unlock_user', None)

            for person in self.presence:
                if (
                    person.lock_user is not None
                    and unlock_user is not None
                    and str(unlock_user) == str(person.lock_user)
                ):
                    if (
                        person.role == 'housekeeper'
                        and self.current_MODE == translations.away
                    ):
                        self.current_MODE = translations.wash
                        self._fire_mode(translations.wash)
                    self._notify(
                        message = f"{person.person_id} unlocked the door",
                        message_title = "Door unlock",
                        message_recipient = self.notify_receiver,
                        also_if_not_home = True,
                        data = {'tag' : 'last_unlock_user'}
                    )
                    break

            if not self._anyone_at_main_house_home():
                self._pause_alarm_notification(20)

    # ------------------------------------------------------------------
    # Vacation and presence
    # ------------------------------------------------------------------
    def _vacation_changed(self, entity, attribute, old, new, **kwargs) -> None:
        """ Vacation prevents vacuums from starting while away.
            When the switch is turned off the house is cleaned once before you get home.
        """
        if new == 'on':
            self.vacation = True
        elif new == 'off':
            self.vacation = False
            if old in UNAVAILABLE_STATES:
                return # Home Assistant came back, not a real change
            if not self._anyone_at_main_house_home():
                self.start_vacuum()

    def _outsideChange(self, entity, attribute, old, new, **kwargs) -> None:
        """ Listens for the manual outside switches. """
        person = self._person_by_switch.get(entity)
        if person is None:
            return
        if new == 'on' and not person.outside_activated:
            person.update_is_outside(is_outside = True)
            if person.home:
                self._away(person)
        elif new == 'off' and person.outside_activated:
            person.update_is_outside(is_outside = False)
            if person.home:
                self._home(person)

    def _presenceChange(self, entity, attribute, old, new, **kwargs) -> None:
        """ Listens for trackers. unavailable and unknown are ignored, so a restart of
            Home Assistant or a tracker dropping out does not set away mode.
        """
        person = self._person_by_entity.get(entity)
        if person is None:
            return
        if new in UNAVAILABLE_STATES:
            self.ADapi.log(f"{self.name}: {entity} is {new}. Keeping last known presence.", level = 'DEBUG')
            return

        if new == 'home' and not person.home:
            person.update_state(is_home = True)
            if not person.outside_activated:
                self._home(person)
        elif new != 'home' and person.home:
            person.update_state(is_home = False)
            if not person.outside_activated:
                self._away(person)

    def _home(self, person:Person) -> None:
        """ A person is now home. The person state is updated by the caller. """
        if person.role in ('adult', 'family'):
            self.stop_vacuum()
        if person.role == 'tenant':
            return # No current logic

        if self._anyone_at_main_house_home():
            if self.current_MODE == translations.away:
                self.current_MODE = translations.automagical
                self._fire_mode(translations.automagical)
                self.stop_alarm()

            self._cancel_timer(self.away_handler)
            self.away_handler = None

            if (
                self._count('adult', 'family') >= 1
                and self.current_MODE not in (translations.away, translations.night)
            ):
                self.disableRelockDoor()

        elif person.role == 'housekeeper':
            self._notify(
                message = f"Housekeeper {person.person_id} entered",
                message_title = "Housekeeping",
                message_recipient = self.notify_receiver,
                also_if_not_home = True,
                data = {'tag' : 'last_unlock_user'}
            )
            if self.current_MODE == translations.away:
                self.stop_alarm()

    def _away(self, person:Person) -> None:
        """ A person left. The person state is updated by the caller. """
        if person.role == 'tenant':
            return

        if (
            person.stopMorning
            and self.current_MODE == translations.morning
            and self._anyone_at_main_house_home()
        ):
            self.current_MODE = translations.automagical
            self._fire_mode(translations.automagical)
            return

        if self._count('adult', 'family') > 0:
            return # Someone is still home

        self.enableRelockDoor()

        if (
            self.keep_mode_when_outside is not None
            and self.ADapi.get_state(self.keep_mode_when_outside, namespace = self.HASS_namespace) == 'on'
        ):
            return

        if (
            self.current_MODE.startswith(translations.night)
            and self.ADapi.now_is_between(self.night_runtime, self.morning_runtime)
            and self._count('kid') > 0
        ):
            return

        self._cancel_timer(self.away_handler)
        self.away_handler = self.ADapi.run_in(self.setAwayMode, self.delay_before_setting_away)

    def setAwayMode(self, **kwargs) -> None:
        """ Starts the vacuums and sets away mode when no one is home. """
        self.away_handler = None
        if (
            not self.vacation
            and self.ADapi.now_is_between(self.vacuum_earliest, self.vacuum_latest)
        ):
            self.start_vacuum()

        if not self._anyone_at_main_house_home():
            self.start_alarm()

            if self.current_MODE != translations.away:
                self.current_MODE = translations.away
                self._fire_mode(translations.away)

    # ------------------------------------------------------------------
    # Notification when nobody is home
    # ------------------------------------------------------------------
    def start_alarm(self) -> None:
        """ Starts listening for sensor activity. """
        if not self.alarm_active:
            for sensor in self.alarmsensors:
                handle = self.ADapi.listen_state(self._sensor_activated, sensor,
                    namespace = self.HASS_namespace
                )
                self.sensor_handle.append(handle)
            self.alarm_active = True
            self.notify_on_alarm = True
            self.media_on_alarm = True

    def stop_alarm(self) -> None:
        """ Stops listening for sensor activity. """
        self._cancel_handles(self.sensor_handle)
        self.sensor_handle = []
        self.alarm_active = False

    def _pause_alarm_notification(self, seconds:int, notify:bool = True, media:bool = True) -> None:
        """ No notifications and/or alarm media until the pause is over. """
        if notify:
            self.notify_on_alarm = False
            self._cancel_timer(self._alarm_reset_timer)
            self._alarm_reset_timer = self.ADapi.run_in(self._reset_alarm_notification, seconds)
        if media:
            self.media_on_alarm = False
            self._cancel_timer(self._media_reset_timer)
            self._media_reset_timer = self.ADapi.run_in(self._reset_alarm_media, seconds)

    def _sensor_activated(self, entity, attribute, old, new, **kwargs) -> None:
        """ Sends notification with picture if triggered, and plays music. """
        if new not in ALARM_STATES or old in UNAVAILABLE_STATES:
            return

        for person in self.presence:
            if person.role != 'tenant' and person.is_home():
                return

        send_notification = self.notify_on_alarm
        play_media = (
            self.media_on_alarm
            and bool(self.alarm_media)
            and entity not in self.alarm_no_media
        )
        if not send_notification and not play_media:
            return
        self._pause_alarm_notification(ALARM_NOTIFICATION_PAUSE, notify = send_notification, media = play_media)

        if send_notification:
            self._alarm_notification(entity)
        if play_media:
            self._alarm_media()

    def _alarm_notification(self, entity:str) -> None:
        """ Notification with a picture if the sensor has a camera. """
        data:Dict[str, Any] = {'tag' : 'sensor_activated_in_modeManagement'}
        camera = self.alarm_cameras.get(entity, None)
        delay = 0
        if camera:
            if self._save_image is not None:
                path = self._save_image(
                    ADapi = self.ADapi,
                    target_directory = self.snapshot_directory,
                    local_directory = '',
                    camera_entity = camera,
                    namespace = self.HASS_namespace,
                    keep_days = self.snapshot_keep_days,
                )
                data['image'] = path                # Android
                data['attachment'] = {'url': path}  # iOS
                delay = 2 # Home Assistant writes the file after the service call
            else:
                data['image'] = f"/api/camera_proxy/{camera}"       # Android
                data['entity_id'] = camera                          # iOS
                data['push'] = {'category': 'camera'}               # iOS

        self.ADapi.run_in(self._send_alarm_notification, delay, entity = entity, data = data)

    def _alarm_media(self) -> None:
        """ Selects source, sets volume and starts the alarm playlists. """
        for play_media in self.alarm_media:
            if 'amp' in play_media:
                if 'source' in play_media:
                    self.ADapi.call_service('media_player/select_source',
                        entity_id = play_media['amp'],
                        source = play_media['source'],
                        namespace = self.HASS_namespace
                    )
                if 'volume' in play_media:
                    self.ADapi.call_service('media_player/volume_set',
                        entity_id = play_media['amp'],
                        volume_level = play_media['volume'],
                        namespace = self.HASS_namespace
                    )
            self.ADapi.run_in(self.play_alarm_on_speakers, 8,
                play_media = play_media
            )

    def _send_alarm_notification(self, **kwargs) -> None:
        self._notify(
            message = f"{kwargs['entity']}",
            message_title = "Sensor triggered",
            message_recipient = self.notify_receiver,
            also_if_not_home = True,
            data = kwargs['data']
        )

    def play_alarm_on_speakers(self, **kwargs) -> None:
        """ Plays media after sensor is triggered. """
        play_media = kwargs['play_media']
        self.ADapi.call_service('media_player/play_media',
            entity_id = play_media['player'],
            media_content_id = play_media['playlist'],
            media_content_type = 'music',
            namespace = self.HASS_namespace
        )
        if 'normal_volume' in play_media:
            self.ADapi.run_in(self._reset_soundlevel, 120,
                play_media = play_media
            )

    def _reset_soundlevel(self, **kwargs) -> None:
        """ Sets sound level back to normal volume after alarm. """
        play_media = kwargs['play_media']
        self.ADapi.call_service('media_player/volume_set',
            entity_id = play_media['amp'],
            volume_level = play_media['normal_volume'],
            namespace = self.HASS_namespace
        )

    def _reset_alarm_notification(self, **kwargs) -> None:
        """ Resets timer so that any sensors triggered it will send a new notification. """
        self.notify_on_alarm = True

    def _reset_alarm_media(self, **kwargs) -> None:
        """ Allows alarm media to play again. """
        self.media_on_alarm = True

    # ------------------------------------------------------------------
    # Vacuum
    # ------------------------------------------------------------------
    def start_vacuum(self) -> None:
        if self.vacuum_control is not None:
            self.vacuum_control.start()
        if self.vacuum_event:
            self.ADapi.fire_event(self.vacuum_event, action = 'start', namespace = self.HASS_namespace)

    def stop_vacuum(self) -> None:
        if self.vacuum_control is not None:
            self.vacuum_control.stop()
        if self.vacuum_event:
            self.ADapi.fire_event(self.vacuum_event, action = 'stop', namespace = self.HASS_namespace)
