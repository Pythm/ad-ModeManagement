""" Mode Event Management

    Presence and time based house modes. Fires MODE_CHANGE events that Lightwand
    consumes, keeps the current mode in sync with events from other apps (fire
    detection, Lightwand GUI), and drives the alarm notifications, the MQTT door
    lock and the vacuums from presence.

    Mode names come from Lightwand's translations_lightmodes. Add
    'dependencies: mode_translation' to the app config so they load first.

    @Pythm / https://github.com/Pythm
"""
__version__ = "0.3.1"

import datetime
import json
from typing import Any, Dict, List, Optional, Tuple

from appdaemon import adbase as ad

from translations_lightmodes import translations

from modeManagement_config import Person
from vacuum_manager import UNAVAILABLE_STATES, VacuumControl, _as_list

# States of a triggered alarm sensor: binary sensors, switches and covers/doors
ALARM_STATES = ('on', 'open', 'opening')
ALARM_NOTIFICATION_PAUSE = 600  # seconds between alarm notifications
UNLOCK_ALARM_PAUSE = 20  # seconds without alarm notifications after a door unlock while nobody is home
LOCK_DELAY = 10  # seconds from enabling auto relock until the door is locked
UNLOCK_DELAY = 3  # seconds from disabling auto relock until the door is unlocked
SNAPSHOT_WRITE_DELAY = 2  # seconds. Home Assistant writes the snapshot file after the service call
MEDIA_START_DELAY = 8  # seconds. The amplifier needs time to switch source before playback
VOLUME_RESET_DELAY = 120  # seconds of alarm playback before the volume is set back to normal

# Roles that keep the house out of away mode and silence the alarm.
MAIN_HOUSE_ROLES = ('adult', 'kid', 'family')
# Roles that unlock the door when they come home and stop the vacuums.
# The house counts as empty for the away path when nobody with one of these roles is home.
# 'family' (extended family) behaves like 'adult' here. The difference is the optional
# 'family' light mode, used as the normal mode when family is home without an adult.
ADULT_ROLES = ('adult', 'family')


def _parse_mode_and_room(mode: str) -> Tuple[str, Optional[str]]:
    """ Splits 'off_livingroom' into ('off', 'livingroom'). """
    if '_' not in mode:
        return mode, None
    modename, roomname = mode.split('_', 1)
    return modename, roomname


class ModeManagement(ad.ADBase):
    """ One instance per house.

        All Home Assistant calls go through self.ADapi in HASS_namespace. MQTT is only
        used when MQTT_door_lock is set.
    """

    def initialize(self):
        """ Reads the app args, reads each state once and registers the listeners.
            The setup helpers run in dependency order: the mode at startup needs the
            vacation state and the input_text, the alarm needs the sensors.
        """
        self.ADapi = self.get_ad_api()

        # Namespaces for HASS and MQTT
        self.HASS_namespace:str = self.args.get('HASS_namespace', 'default')
        self.MQTT_namespace:str = self.args.get('MQTT_namespace', 'mqtt')

        self._setup_notification()
        self._setup_times()
        self._setup_vacation()
        self._setup_holidays()
        self._setup_presence()
        self._setup_alarm()
        self._setup_vacuum()
        self._setup_door_lock()

        # Update current mode to a Home Assistant input_text
        self.ha_light_mode_text:Optional[str] = self.args.get('HALightModeText', None)

        # Setting data
        self.current_mode:str = self._initial_mode()
        if self.current_mode == translations.away:
            self.start_alarm()

        self._setup_schedule()

        # Listens for mode events
        self.ADapi.listen_event(self._mode_event, translations.MODE_CHANGE, namespace = self.HASS_namespace)

    # ------------------------------------------------------------------
    # Setup helpers. Called once from initialize, in the order above
    # ------------------------------------------------------------------
    def _setup_notification(self) -> None:
        """ Notification receivers and the pause flags for alarm notifications and media. """
        self.notify_receiver:list = _as_list(self.args.get('notify_receiver', []))
        self.notify_app_name:Optional[str] = self.args.get('notify_app', None)
        self.notify_on_alarm:bool = True
        self.media_on_alarm:bool = True
        self._alarm_reset_timer = None
        self._media_reset_timer = None
        # When the running pauses end, so a new shorter pause never cuts a running one short
        self._alarm_pause_end:Optional[datetime.datetime] = None
        self._media_pause_end:Optional[datetime.datetime] = None

    def _setup_times(self) -> None:
        """ Times for the morning and night routines and the vacuum window. """
        self.morning_runtime:str = self._time_arg('morning_start_listen_time', '06:00:00')
        self.execute_morning:str = self._time_arg('execute_morning_at', '10:00:00')
        self.night_runtime:str = self._time_arg('night_start_listen_time', '22:00:00')
        self.execute_night:str = self._time_arg('execute_night_at', '02:00:00')
        self.vacuum_earliest:str = self._time_arg('vacuum_earliest_start', self.morning_runtime)
        self.vacuum_latest:str = self._time_arg('vacuum_latest_start', '18:00:00')

    def _setup_vacation(self) -> None:
        """ Vacation switch from Home Assistant. Blocks the vacuums and means away at startup. """
        self.vacation:bool = False
        # away_state is the old name for vacation. It wins when both are set, so old
        # configs keep working unchanged. Do not "fix" the order.
        vacation_entity = self.args.get('away_state', None)
        if vacation_entity is None:
            vacation_entity = self.args.get('vacation', None)
        if vacation_entity is not None:
            state = self.ADapi.get_state(vacation_entity, namespace = self.HASS_namespace)
            if state is None:
                self.ADapi.log(f"{self.name}: vacation entity {vacation_entity} does not exist", level = 'WARNING')
        else:
            # Default entity, only used if it exists. One get_state gives both existence and value
            state = self.ADapi.get_state('input_boolean.vacation', namespace = self.HASS_namespace)
            if state is not None:
                vacation_entity = 'input_boolean.vacation'
        if vacation_entity is not None:
            self.vacation = state == 'on'
            self.ADapi.listen_state(self._vacation_changed, vacation_entity,
                namespace = self.HASS_namespace
            )

    def _setup_holidays(self) -> None:
        """ Holidays. Only loaded when country_code is set. """
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

    def _setup_presence(self) -> None:
        """ Persons with trackers and optional outside switches for manual override. """
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
            self.ADapi.listen_state(self._presence_changed, person.person_id, namespace = self.HASS_namespace)

            if person.outside_switch is not None:
                self._person_by_switch[person.outside_switch] = person
                switch_state = self.ADapi.get_state(person.outside_switch, namespace = self.HASS_namespace)
                if switch_state is None:
                    self.ADapi.log(f"{self.name}: {person.outside_switch} does not exist", level = 'WARNING')
                person.update_is_outside(is_outside = switch_state == 'on')
                self.ADapi.listen_state(self._outside_changed, person.outside_switch, namespace = self.HASS_namespace)

        self.keep_mode_when_outside:Optional[str] = self.args.get('keep_mode_when_outside', None)
        self.delay_before_setting_away:int = self.args.get('delay_before_setting_away', 0)
        self.away_handler:Optional[str] = None

        # Optional light mode for when extended family is home without any adult.
        # Replaces automagical as the normal daytime mode while that holds. Unset: no family mode
        self.family_mode:Optional[str] = None
        family_mode = self.args.get('family', None)
        if family_mode is not None:
            if isinstance(family_mode, str) and family_mode.strip():
                self.family_mode = family_mode
            else:
                self.ADapi.log(
                    f"{self.name}: family must be a non-empty light mode name, got {family_mode!r}. Ignored.",
                    level = 'WARNING'
                )

    def _setup_alarm(self) -> None:
        """ Sensors that notify (with optional camera picture and media) when nobody is home. """
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
        self.alarm_media:List[Dict[str, Any]] = _as_list(self.args.get('alarm_media', []))

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

    def _setup_vacuum(self) -> None:
        """ Vacuum robots. Either handled here or by the VacuumManager app through an event. """
        self.vacuum_control:Optional[VacuumControl] = None
        if self.args.get('vacuum', None):
            self.vacuum_control = VacuumControl(
                self.ADapi,
                self.HASS_namespace,
                self.args['vacuum'],
                self.args.get('prevent_vacuum', []),
                self.args.get('vacuum_min_battery', 40),
            )
        self.vacuum_event:Optional[str] = self.args.get('vacuum_event', None)

    def _setup_door_lock(self) -> None:
        """ MQTT door lock. Disabled when the MQTT plugin is missing. """
        self.mqtt_door_lock:list = _as_list(self.args.get('MQTT_door_lock', []))
        self.unlock_door_when_home:bool = bool(self.args.get('unlock_door_when_home', False))
        self.mqtt:Optional[Any] = None
        self._lock_timer = None
        self._unlock_timer = None
        if self.mqtt_door_lock:
            self.mqtt = self.get_plugin_api("MQTT")
            if self.mqtt is None:
                self.ADapi.log(f"{self.name}: MQTT plugin not found. Door lock is disabled.", level = 'WARNING')
                self.mqtt_door_lock = []
        for door in self.mqtt_door_lock:
            self.mqtt.mqtt_subscribe(door)
            self.mqtt.listen_event(self._mqtt_doorlock_event, "MQTT_MESSAGE",
                topic = door,
                namespace = self.MQTT_namespace
            )

    def _setup_schedule(self) -> None:
        """ Daily timers for the morning and night routines. Needs current_mode. """
        # Morning routine
        self.morning_handler:list = []
        self.morning_sensors:list = _as_list(self.args.get('morning_sensors', []))
        self.turn_on_in_the_morning:list = _as_list(self.args.get('turn_on_in_the_morning', []))

        self.ADapi.run_daily(self._waiting_for_morning, self.morning_runtime)
        # AppDaemon may start inside the morning window after the daily timer has
        # already fired today, so run the catch-up once here.
        if (
            self.ADapi.now_is_between(self.morning_runtime, self.execute_morning)
            and self.current_mode.startswith(translations.night)
        ):
            self._waiting_for_morning()
        self.ADapi.run_daily(self._good_day_now, self.execute_morning)

        self.morning_to_day:str = self.execute_morning
        if self.args.get('morning_to_normal', None) is not None:
            morning_to_normal = self._time_arg('morning_to_normal', self.execute_morning)
            self.morning_to_day = morning_to_normal
            self.ADapi.run_daily(self._change_morning_to_day, morning_to_normal)

        # Night routine
        self.night_handler:list = []
        self.turn_off_at_night:list = _as_list(self.args.get('turn_off_at_night', []))
        self.night_sensors:list = _as_list(self.args.get('night_sensors', []))

        self.ADapi.run_daily(self._waiting_for_night, self.night_runtime)
        # Same catch-up for the night window after a restart.
        if (
            self.ADapi.now_is_between(self.night_runtime, self.execute_night)
            and self.current_mode != translations.night
        ):
            self._waiting_for_night()
        self.ADapi.run_daily(self._good_night_now, self.execute_night)

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
        """ Mode at startup. Vacation is away, then the input_text, else the time of day.
            'fire' is never a real mode (see _mode_event), so a stale 'fire' in the
            input_text after a restart is ignored.
            A stored normal mode (automagical or the family mode) is re-evaluated against
            presence, since who is home may have changed while the app was down.
        """
        if self.vacation:
            return translations.away
        if self.ha_light_mode_text:
            text = self.ADapi.get_state(self.ha_light_mode_text, namespace = self.HASS_namespace)
            if text not in UNAVAILABLE_STATES and text != '' and text != translations.fire:
                if text in (translations.automagical, self.family_mode):
                    return self._normal_mode()
                return str(text)
        if self.ADapi.now_is_between(self.execute_night, self.morning_runtime):
            return translations.night
        return self._normal_mode()

    # ------------------------------------------------------------------
    # Presence helpers. Counted from the persons, so the numbers cannot drift
    # ------------------------------------------------------------------
    def _count(self, *roles:str) -> int:
        """ Number of persons with one of roles who are home and not marked outside. """
        return sum(1 for person in self.presence if person.role in roles and person.is_home())

    def anyone_home(self) -> bool:
        """ True if any person, whatever the role, is home and not marked outside.
            Public: FireAlarm in Pythm_AppdaemonApps calls this through get_app.
        """
        return any(person.is_home() for person in self.presence)

    def _anyone_at_main_house_home(self) -> bool:
        """ True if an adult, kid or family member is home. Tenants and housekeepers do not count. """
        return self._count(*MAIN_HOUSE_ROLES) > 0

    def _family_mode_active(self) -> bool:
        """ True when a family mode is configured, a family member is home and no adult is home.
            Kids, tenants and housekeepers do not matter.
        """
        return (
            self.family_mode is not None
            and self._count('adult') == 0
            and self._count('family') > 0
        )

    def _normal_mode(self) -> str:
        """ The normal daytime mode: the family mode while _family_mode_active, else automagical.
            Every site that returns the house to normal goes through here.
        """
        if self._family_mode_active():
            return self.family_mode
        return translations.automagical

    def _sync_family_mode(self) -> None:
        """ Switches between automagical and the family mode after a presence change.
            Only those two modes are touched. Morning, night, away and wash are left
            alone, they return to normal through _normal_mode later.
        """
        if self.family_mode is None:
            return
        if self.current_mode not in (translations.automagical, self.family_mode):
            return
        normal = self._normal_mode()
        if self.current_mode != normal:
            self._set_mode(normal)

    def _in_vacuum_window(self) -> bool:
        """ True when the vacuums may start: not on vacation and inside vacuum_earliest/latest. """
        return (
            not self.vacation
            and self.ADapi.now_is_between(self.vacuum_earliest, self.vacuum_latest)
        )

    def _cancel_timer(self, handle) -> None:
        """ Cancels a run_in timer if it is still waiting. Safe to call with None. """
        if handle is not None and self.ADapi.timer_running(handle):
            self.ADapi.cancel_timer(handle, silent = True)

    def _notify(self, **kwargs) -> None:
        """ Sends notification with the notify app from args or Home Assistant notify.
            message_recipient defaults to notify_receiver for both paths.
        """
        kwargs.setdefault('message_recipient', self.notify_receiver)
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
        for receiver in _as_list(kwargs['message_recipient']):
            self.ADapi.call_service(f'notify/{receiver}',
                title = message_title,
                message = kwargs['message'],
                data = data,
                namespace = self.HASS_namespace
            )

    def _fire_mode(self, mode:str) -> None:
        """ Fires MODE_CHANGE. _mode_event stores the mode when the event comes back. """
        self.ADapi.fire_event(translations.MODE_CHANGE, mode = mode, namespace = self.HASS_namespace)

    def _set_mode(self, mode:str) -> None:
        """ Sets current_mode now and fires MODE_CHANGE.
            _mode_event stores the mode too, but only when the event comes back from
            AppDaemon. Callers that check current_mode on the next lines need it set now.
        """
        self.current_mode = mode
        self._fire_mode(mode)

    # ------------------------------------------------------------------
    # Mode events
    # ------------------------------------------------------------------
    def _mode_event(self, event_name, data, **kwargs) -> None:
        """ Listens to mode events and reacts on night, morning, normal.
            Also updates the input_text with mode.
        """
        mode = data.get('mode', None)
        if not isinstance(mode, str) or not mode:
            return
        # The family mode is a house mode even if its name contains '_', so it is
        # matched before the room parsing
        if self.family_mode is not None and mode == self.family_mode:
            modename, roomname = mode, None
        else:
            modename, roomname = _parse_mode_and_room(mode)

        ## Transition from night to morning ##
        # The family mode counts as normal here. With no family mode, None never matches
        if (
            self.current_mode.startswith(translations.night)
            and self.ADapi.now_is_between(self.morning_runtime, self.execute_morning)
            and modename in (translations.automagical, translations.morning, self.family_mode)
        ):
            for item in self.turn_on_in_the_morning:
                if self.ADapi.get_state(item, namespace = self.HASS_namespace) == 'off':
                    self.ADapi.call_service('homeassistant/turn_on',
                        entity_id = item,
                        namespace = self.HASS_namespace
                    )
            self._cancel_listening_for_morning()
            self._set_auto_relock(False)

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

            self._set_auto_relock(True)

        ## Main "Away" mode ##
        if mode == translations.away:
            self.start_alarm()

            self._set_auto_relock(True)

        ## False alarm from your fire detection app ##
        ## Re-fires the mode from before the fire. The false alarm itself is never stored
        elif mode == translations.false_alarm:
            self._fire_mode(self.current_mode)
            return

        ## Fire detected from your fire detection app ##
        ## Updates input_text but not the current_mode so it can go back to previous if false alarm
        elif mode == translations.fire:
            if self.ha_light_mode_text:
                self.ADapi.call_service('input_text/set_value',
                    value = translations.fire,
                    entity_id = self.ha_light_mode_text,
                    namespace = self.HASS_namespace
                )
            return

        # Store mode to current_mode. Room modes like off_kitchen do not change the house mode
        if roomname is None:
            if modename == translations.reset:
                # Lightwand resets itself, so only store the mode. The family mode
                # (if configured) returns with the next presence change.
                self.current_mode = translations.automagical
            else:
                self.current_mode = modename

            # Update input_text do display in GUI
            if self.ha_light_mode_text:
                self.ADapi.call_service('input_text/set_value',
                    value = self.current_mode,
                    entity_id = self.ha_light_mode_text,
                    namespace = self.HASS_namespace
                )

    # ------------------------------------------------------------------
    # Morning and Night handling
    # ------------------------------------------------------------------
    def _cancel_handles(self, handles:list) -> None:
        """ Cancels a list of listen_state handles. """
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
        """ Starts listening for sensors activating morning/normal mode.
            Also resets the keep_mode_when_outside switch for the new day.
        """
        if self.current_mode != translations.away:
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

    def _change_morning_to_day(self, **kwargs) -> None:
        """ Changes mode from morning to normal at given time. """
        if self.current_mode == translations.morning:
            self._fire_mode(self._normal_mode())

    def _waking_up(self, entity, attribute, old, new, **kwargs) -> None:
        """ Reacts to morning sensors. Morning on workdays before morning_to_day, else normal. """
        if (
            self.ADapi.now_is_between(self.morning_runtime, self.morning_to_day)
            and not self._is_holiday()
        ):
            self._fire_mode(translations.morning)
        else:
            self._fire_mode(self._normal_mode())
        self._cancel_listening_for_morning()

    def _going_to_bed(self, entity, attribute, old, new, **kwargs) -> None:
        """ Reacts to night sensors. Not in away mode. """
        if self.current_mode != translations.away:
            self._fire_mode(translations.night)
        self._cancel_listening_for_night()

    def _good_day_now(self, **kwargs) -> None:
        """ Change to normal day light at this time if mode is night or morning. """
        if (
            self.current_mode.startswith(translations.night)
            or self.current_mode == translations.morning
        ):
            self._fire_mode(self._normal_mode())
        self._cancel_listening_for_morning()

    def _good_night_now(self, **kwargs) -> None:
        """ Change to night at the given time. """
        if (
            self.current_mode != translations.away
            and self.current_mode != translations.night
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
    def _publish_to_doors(self, suffix:str, payload:str) -> None:
        """ Publishes payload to <door><suffix> for every MQTT door. """
        for door in self.mqtt_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + suffix,
                payload = payload,
                namespace = self.MQTT_namespace
            )

    def _set_auto_relock(self, enable:bool) -> None:
        """ Enables auto relock and locks the door after LOCK_DELAY, or disables auto
            relock and unlocks the door after UNLOCK_DELAY.
            Unlocking is only done with unlock_door_when_home. The opposite pending
            action is cancelled, and a pending action of the same kind is left alone.
        """
        if not self.mqtt_door_lock:
            return
        if not enable and not self.unlock_door_when_home:
            return
        if enable:
            self._cancel_timer(self._unlock_timer)
            self._unlock_timer = None
            pending = self._lock_timer
        else:
            self._cancel_timer(self._lock_timer)
            self._lock_timer = None
            pending = self._unlock_timer
        if pending is not None and self.ADapi.timer_running(pending):
            return # Already on its way

        self._publish_to_doors("/set/auto_relock", "true" if enable else "false")
        if enable:
            self._lock_timer = self.ADapi.run_in(self._lock_door, LOCK_DELAY)
        else:
            self._unlock_timer = self.ADapi.run_in(self._unlock_door, UNLOCK_DELAY)

    def _lock_door(self, **kwargs) -> None:
        """ Locks the MQTT doors. Timer callback from _set_auto_relock(True). """
        self._lock_timer = None
        self._publish_to_doors("/set", "LOCK")

    def _unlock_door(self, **kwargs) -> None:
        """ Unlocks the MQTT doors. Timer callback from _set_auto_relock(False). """
        self._unlock_timer = None
        self._publish_to_doors("/set", "UNLOCK")

    def _mqtt_doorlock_event(self, event_name, data, **kwargs) -> None:
        """ Listens to MQTT door events. An unlock by a known lock_user notifies, and a
            housekeeper unlocking in away mode starts wash mode.
        """
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
                        and self.current_mode == translations.away
                    ):
                        self._set_mode(translations.wash)
                    self._notify(
                        message = f"{person.person_id} unlocked the door",
                        message_title = "Door unlock",
                        also_if_not_home = True,
                        data = {'tag' : 'last_unlock_user'}
                    )
                    break

            # Someone opened the door while the alarm is armed: give them a moment
            # before the sensors notify. A longer pause already running is kept.
            if not self._anyone_at_main_house_home():
                self._pause_alarm_notification(UNLOCK_ALARM_PAUSE)

    # ------------------------------------------------------------------
    # Vacation and presence
    # ------------------------------------------------------------------
    def _vacation_changed(self, entity, attribute, old, new, **kwargs) -> None:
        """ Vacation prevents vacuums from starting while away.
            When the switch is turned off while nobody is home the house is cleaned once
            before you get home, but only inside the normal vacuum start window.
        """
        if new == 'on':
            self.vacation = True
        elif new == 'off':
            self.vacation = False
            if old in UNAVAILABLE_STATES:
                return # Home Assistant came back, not a real change
            if self._anyone_at_main_house_home():
                return
            if not self._in_vacuum_window():
                self.ADapi.log(
                    f"{self.name}: Vacation ended outside the vacuum window "
                    f"{self.vacuum_earliest} to {self.vacuum_latest}. Vacuums not started.",
                    level = 'INFO'
                )
                return
            self.start_vacuum()

    def _outside_changed(self, entity, attribute, old, new, **kwargs) -> None:
        """ Listens for the manual outside switches. Only persons the tracker says are
            home are moved in or out of the presence count.
        """
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

    def _presence_changed(self, entity, attribute, old, new, **kwargs) -> None:
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
        if person.role in ADULT_ROLES:
            self.stop_vacuum()
        if person.role == 'tenant':
            return # No current logic

        if self._anyone_at_main_house_home():
            if self.current_mode == translations.away:
                self._set_mode(self._normal_mode())
                self.stop_alarm()
            # Family arrived with no adult home, or an adult arrived in family mode
            self._sync_family_mode()

            self._cancel_timer(self.away_handler)
            self.away_handler = None

            # Kids do not unlock the door, and at night or away the door stays locked
            if (
                self._count(*ADULT_ROLES) > 0
                and self.current_mode not in (translations.away, translations.night)
            ):
                self._set_auto_relock(False)

        elif person.role == 'housekeeper':
            # Nobody from the main house is home. The mode stays away (or wash after a
            # door unlock, see _mqtt_doorlock_event), only the alarm is silenced
            self._notify(
                message = f"Housekeeper {person.person_id} entered",
                message_title = "Housekeeping",
                also_if_not_home = True,
                data = {'tag' : 'last_unlock_user'}
            )
            if self.current_mode == translations.away:
                self.stop_alarm()

    def _away(self, person:Person) -> None:
        """ A person left. The person state is updated by the caller.
            This is also the path back from wash mode: when the housekeeper leaves and
            somebody from the main house is home the mode goes back to normal. When
            nobody is home, the door locks and _set_away_mode starts the vacuums and
            sets away.
        """
        if person.role == 'tenant':
            return

        if (
            person.role == 'housekeeper'
            and self.current_mode == translations.wash
            and self._anyone_at_main_house_home()
        ):
            self._set_mode(self._normal_mode())

        if (
            person.stopMorning
            and self.current_mode == translations.morning
            and self._anyone_at_main_house_home()
        ):
            self._set_mode(self._normal_mode())
            return

        # An adult left with family home, or the last family member left in family mode
        self._sync_family_mode()

        if self._count(*ADULT_ROLES) > 0:
            return # Someone is still home

        self._set_auto_relock(True)

        if (
            self.keep_mode_when_outside is not None
            and self.ADapi.get_state(self.keep_mode_when_outside, namespace = self.HASS_namespace) == 'on'
        ):
            return

        # Kids asleep at night: keep night mode and do not start vacuums
        if (
            self.current_mode.startswith(translations.night)
            and self.ADapi.now_is_between(self.night_runtime, self.morning_runtime)
            and self._count('kid') > 0
        ):
            return

        # Kids may still be home: the door locks and the vacuums may start, but away
        # mode is only set if nobody is home (checked again in _set_away_mode after the delay)
        self._cancel_timer(self.away_handler)
        self.away_handler = self.ADapi.run_in(self._set_away_mode, self.delay_before_setting_away)

    def _set_away_mode(self, **kwargs) -> None:
        """ Starts the vacuums and sets away mode when no one is home.
            Timer callback from _away, after delay_before_setting_away.
        """
        self.away_handler = None
        if self._in_vacuum_window():
            self.start_vacuum()

        if not self._anyone_at_main_house_home():
            self.start_alarm()

            if self.current_mode != translations.away:
                self._set_mode(translations.away)

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

    def _start_pause(self, handle, pause_end:Optional[datetime.datetime], callback, seconds:int):
        """ Re-arms a pause timer, unless the running one ends later than the new one.
            Returns the (handle, end time) to store.
        """
        new_end = self.ADapi.get_now() + datetime.timedelta(seconds = seconds)
        if (
            handle is not None
            and pause_end is not None
            and self.ADapi.timer_running(handle)
            and pause_end > new_end
        ):
            return handle, pause_end # The running pause is longer, keep it
        self._cancel_timer(handle)
        return self.ADapi.run_in(callback, seconds), new_end

    def _pause_alarm_notification(self, seconds:int, notify:bool = True, media:bool = True) -> None:
        """ No notifications and/or alarm media until the pause is over.
            A pause that is already running and ends later is never shortened.
        """
        if notify:
            self.notify_on_alarm = False
            self._alarm_reset_timer, self._alarm_pause_end = self._start_pause(
                self._alarm_reset_timer, self._alarm_pause_end, self._reset_alarm_notification, seconds
            )
        if media:
            self.media_on_alarm = False
            self._media_reset_timer, self._media_pause_end = self._start_pause(
                self._media_reset_timer, self._media_pause_end, self._reset_alarm_media, seconds
            )

    def _sensor_activated(self, entity, attribute, old, new, **kwargs) -> None:
        """ Sends notification with picture if triggered, and plays music. """
        # A sensor recovering from unavailable/unknown is not a trigger (README, 0.3.1)
        if new not in ALARM_STATES or old in UNAVAILABLE_STATES:
            return

        # Unlike _anyone_at_main_house_home, a housekeeper at home also silences the
        # alarm: they work inside the main house. Tenants live separately and do not
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
                delay = SNAPSHOT_WRITE_DELAY
            else:
                data['image'] = f"/api/camera_proxy/{camera}"       # Android
                data['entity_id'] = camera                          # iOS
                data['push'] = {'category': 'camera'}               # iOS

        if delay:
            self.ADapi.run_in(self._send_alarm_notification, delay, entity = entity, data = data)
        else:
            self._send_alarm_notification(entity = entity, data = data)

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
            self.ADapi.run_in(self._play_alarm_on_speakers, MEDIA_START_DELAY,
                play_media = play_media
            )

    def _send_alarm_notification(self, **kwargs) -> None:
        """ Sends the sensor notification. Called directly or from run_in when a snapshot is written. """
        self._notify(
            message = f"{kwargs['entity']}",
            message_title = "Sensor triggered",
            also_if_not_home = True,
            data = kwargs['data']
        )

    def _play_alarm_on_speakers(self, **kwargs) -> None:
        """ Plays media after sensor is triggered. """
        play_media = kwargs['play_media']
        self.ADapi.call_service('media_player/play_media',
            entity_id = play_media['player'],
            media_content_id = play_media['playlist'],
            media_content_type = 'music',
            namespace = self.HASS_namespace
        )
        if 'normal_volume' in play_media:
            self.ADapi.run_in(self._reset_soundlevel, VOLUME_RESET_DELAY,
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
        """ Embedded control first, then the event for a stand-alone VacuumManager. """
        if self.vacuum_control is not None:
            self.vacuum_control.start()
        if self.vacuum_event:
            self.ADapi.fire_event(self.vacuum_event, action = 'start', namespace = self.HASS_namespace)

    def stop_vacuum(self) -> None:
        """ Sends the vacuums back: embedded control first, then the event. """
        if self.vacuum_control is not None:
            self.vacuum_control.stop()
        if self.vacuum_event:
            self.ADapi.fire_event(self.vacuum_event, action = 'stop', namespace = self.HASS_namespace)
