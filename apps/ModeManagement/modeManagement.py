""" Mode Event Management

    @Pythm / https://github.com/Pythm
"""
__version__ = "0.3.0"

from appdaemon.plugins.hass.hassapi import Hass
import datetime
import json
import holidays
from typing import Tuple, Optional, List, Dict, Any

from translations_lightmodes import translations
from lightwand_utils import _parse_mode_and_room

from modeManagement_config import Person, Vacuum

class ModeManagement(Hass):

    def initialize(self):
        self.mqtt = None

        # Namespaces for HASS and MQTT
        self.HASS_namespace:str = self.args.get('HASS_namespace', 'default')
        self.MQTT_namespace:str = self.args.get('MQTT_namespace', 'mqtt')

        # Set up notification
        self.notify_receiver = self.args.get('notify_receiver', [])
        name_of_notify_app = self.args.get('notify_app', None)
        if name_of_notify_app is not None:
            self.notify_app = self.get_app(name_of_notify_app)
        else:
            self.notify_app = Notify_Mobiles(self)
        self.nofify_on_alarm:bool = True

        # Holliday switch from Home Assistant
        if 'away_state' in self.args: # Old name for vacation
            away_state = self.args['away_state']
        elif 'vacation' in self.args:
            away_state = self.args['vacation']
        else:
            away_state = None
            if self.entity_exists('input_boolean.vacation',
                namespace = self.HASS_namespace
            ):
                away_state = 'input_boolean.vacation'
        if away_state is None:
            self.away_state = False
        else:
            self.away_state = self.get_state(away_state, namespace = self.HASS_namespace)  == 'on'
            self.listen_state(self._vacation_ending, away_state,
                namespace = self.HASS_namespace
            )

        # Detect country and initialize holidays
        self.country_code = None
        self.holidays = None
        if 'country_code' in self.args:
            self.country_code = self.args['country_code']
            try:
                holiday_class = getattr(holidays, self.country_code.upper())
                self.holidays = holiday_class(years=[datetime.date.today().year, datetime.date.today().year + 1])
            except AttributeError:
                self.log(f"Could not find holidays for {self.country_code}. Will fire morning every day.", level = 'INFO')

        # Presence detection and HA switch for manual override
        self.adultAtHome:int = 0
        self.kidsAtHome:int = 0
        self.extendedFamilyAtHome:int = 0
        self.tenantAtHome:int = 0
        self.housekeeperAtHome:int = 0

        # Load the presence list – convert every entry into a Person object
        self.presence: List[Person] = []
        for entry in self.args.get('presence', []):
            # `entry` can be a plain dict or already a Person.
            if isinstance(entry, Person):
                person_obj = entry
            else:
                person_obj = Person(**entry)  # type: ignore[arg-type]
            self.presence.append(person_obj)

        for person in self.presence:

            self.listen_state(self._presenceChange, person.person_id, namespace = self.HASS_namespace)

            if person.outside_switch is not None:
                self.listen_state(self._outsideChange, person.outside_switch, namespace = self.HASS_namespace)

            if person.is_home():
                if person.role == 'adult':
                    self.adultAtHome += 1
                if person.role == 'kid':
                    self.kidsAtHome += 1
                if person.role == 'family':
                    self.extendedFamilyAtHome += 1
                if person.role == 'tenant':
                    self.tenantAtHome += 1
                if person.role == 'housekeeper':
                    self.housekeeperAtHome += 1

        self.keep_mode_when_outside = self.args.get('keep_mode_when_outside', None)
        self.delay_before_setting_away = self.args.get('delay_before_setting_away', 0)
        self.away_handler = None

        # Set up notification if sensor is activated when no one is home
        self.alarmsensors = self.args.get('alarmsensors',[])
        self.sensor_handle:list = []
        self.alarm_active:bool = False
        self.alarm_media = self.args.get('alarm_media', [])

        # Set up vacuum robots
        raw_vacuum_cfg: List[Union[str, dict]] = self.args.get('vacuum', [])

        self.vacuum: List[Vacuum] = []
        global_prevent = self.args.get('prevent_vacuum', [])
        for i, item in enumerate(raw_vacuum_cfg):
            if isinstance(item, str):
                vacuum_dict = {"vacuum": item}
            elif isinstance(item, dict):
                vacuum_dict = item
            else:
                self.log(f"Vacuum list must be defined as a string or a dictionary. vacuum: {item}",
                        level='INFO')
                continue

            # Apply the global prevent_vacuum list if the entry has no own list.
            if 'prevent_vacuum' not in vacuum_dict:
                vacuum_dict['prevent_vacuum'] = global_prevent

            # Create the Pydantic object (validates the schema).
            try:
                vacuum_obj = Vacuum(**vacuum_dict)
            except Exception as exc:
                self.log(f"Could not create Vacuum instance from {vacuum_dict}. Exception: {exc}",
                        level='ERROR')
                continue

            self.vacuum.append(vacuum_obj)

        self.enable_stop_vacuum:bool = False

        # MQTT Door lock
        self.MQTT_door_lock:list = self.args.get('MQTT_door_lock',[])
        if (
            self.MQTT_door_lock
            and not self.mqtt
        ):
            self.mqtt = self.get_plugin_api("MQTT")
        self.lastUnlockTime = datetime.datetime.now()
        self.lastUnlockUser = None

        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_subscribe(door)
            self.mqtt.listen_event(self.MQTT_doorlock_event, "MQTT_MESSAGE",
                topic = door,
                namespace = self.MQTT_namespace
            )

        # Update current mode to a Home Assistant input_text
        self.haLightModeText = self.args.get('HALightModeText', None) 

        # Setting data
        if not self.away_state:
            if self.haLightModeText:
                self.current_MODE = self.get_state(self.haLightModeText, namespace = self.HASS_namespace)
            elif self.now_is_between('02:00:00', '05:00:00'):
                self.current_MODE = translations.night
            else:
                self.current_MODE = translations.automagical
        else:
            self.current_MODE = translations.away
            self.start_alarm()

        # Morning routine
        self.morning_handler:list = []

        self.morning_sensors = self.args.get('morning_sensors', [])
        self.morning_runtime = self.args.get('morning_start_listen_time', '06:00:00')
        self.morning_to_day = self.args.get('morning_to_normal', None)
        self.execute_morning = self.args.get('execute_morning_at', '10:00:00')

        try:
            test_runtime = self.parse_time(self.morning_runtime)
        except ValueError as ve:
            self.log(
                f"Not able to convert morning_start_listen_time: {self.morning_runtime}. Error: {ve}",
                level = 'INFO'    
            )
            self.morning_runtime = '06:00:00'
        try:
            test_runtime = self.parse_time(self.execute_morning)
        except ValueError as ve:
            self.log(
                f"Not able to convert execute_morning_at: {self.execute_morning}. Error: {ve}",
                level = 'INFO'    
            )
            self.execute_morning = '10:00:00'

        self.run_daily(self._waiting_for_morning, self.morning_runtime)

        if (
            self.now_is_between(self.morning_runtime, self.execute_morning)
            and self.current_MODE.startswith(translations.night)
        ):
            self.run_in(self._waiting_for_morning, 1)

        self.run_daily(self._cancel_listening_for_morning, self.execute_morning)

        self.run_daily(self._good_day_now, self.execute_morning)

        if self.morning_to_day is not None:
            try:
                test_runtime = self.parse_time(self.morning_to_day)
            except ValueError as ve:
                self.log(
                    f"Not able to convert morning_to_normal: {self.morning_to_day}. Error: {ve}",
                    level = 'INFO'    
                )
                self.morning_to_day = self.execute_morning
            else:
                self.run_daily(self._changeMorningToDay, self.morning_to_day)
        else:
            self.morning_to_day = self.execute_morning

        # Night routine
        self.night_handler:list = []

        self.turn_off_at_night = self.args.get('turn_off_at_night',[])
        self.turn_on_in_the_morning = self.args.get('turn_on_in_the_morning', [])

        self.night_sensors = self.args.get('night_sensors', [])
        self.night_runtime = self.args.get('night_start_listen_time', '22:00:00')
        self.execute_night = self.args.get('execute_night_at', '02:00:00')
        try:
            test_runtime = self.parse_time(self.night_runtime)
        except ValueError as ve:
            self.log(
                f"Not able to convert night_start_listen_time: {self.night_runtime}. Error: {ve}",
                level = 'INFO'    
            )
            self.night_runtime = '22:00:00'
        try:
            test_runtime = self.parse_time(self.execute_night)
        except ValueError as ve:
            self.log(
                f"Not able to convert execute_night_at: {self.execute_night}. Error: {ve}",
                level = 'INFO'    
            )
            self.execute_night = '02:00:00'

        self.run_daily(self._waiting_for_night, self.night_runtime)
        if (
            self.now_is_between(self.night_runtime, self.execute_night)
            and self.current_MODE != translations.night
        ):
            self.run_in(self._waiting_for_night, 1)
        self.run_daily(self._good_night_now, self.execute_night)

        # Listens for mode events
        self.listen_event(self.mode_event, translations.MODE_CHANGE, namespace = self.HASS_namespace)


    def anyone_home(self) -> bool:
        if (
            self.adultAtHome == 0
            and self.kidsAtHome == 0
            and self.extendedFamilyAtHome == 0
            and self.tenantAtHome == 0
            and self.housekeeperAtHome == 0
        ):
            return False
        return True

    def anyone_at_main_house_home(self) -> bool:
        if (
            self.adultAtHome == 0
            and self.kidsAtHome == 0
            and self.extendedFamilyAtHome == 0
            and self.housekeeperAtHome == 0
        ):
            return False
        return True

    def mode_event(self, event_name, data, **kwargs) -> None:
        """ Listens to mode events and reacts on night, morning, normal.
            Also updates the input_text with mode.
        """
        modename, roomname = _parse_mode_and_room(data['mode'])

        ## Turning off one room during morning ## Do Nothing
        if (
            self.current_MODE == translations.morning
            and self.now_is_between(self.morning_runtime, self.execute_morning)
            and modename == translations.off
            and roomname is not None
        ):
            return

        ## Transition from night to morning ##
        if (
            self.current_MODE.startswith(translations.night)
            and self.now_is_between(self.morning_runtime, self.execute_morning)
            and (modename == translations.automagical
            or modename == translations.morning)
        ):
                for item in self.turn_on_in_the_morning:
                    if self.get_state(item, namespace = self.HASS_namespace) == 'off':
                        self.turn_on(item, namespace = self.HASS_namespace)
                self._cancel_listening_for_morning(0)
                self.disableRelockDoor()

        ## Transition to main "Night" mode ##
        if (
            data['mode'] == translations.night
            and self.now_is_between(self.night_runtime, self.execute_night)
        ):
            for item in self.turn_off_at_night:
                if self.get_state(item, namespace = self.HASS_namespace) == 'on':
                    self.turn_off(item, namespace = self.HASS_namespace)

            self._cancel_listening_for_night()

            self.enableRelockDoor()

        ## Main "Away" mode ##
        if data['mode'] == translations.away:
            self.start_alarm()

            self.enableRelockDoor()

        ## False alarm from your fire detection app ##
        elif data['mode'] == translations.false_alarm:
            modename = self.current_MODE
            self.fire_event(translations.MODE_CHANGE, mode = self.current_MODE, namespace = self.HASS_namespace)

        ## Fire detected from your fire detection app ##
        ## Updates input_text but not the current_MODE so it can go back to previous if false alarm
        elif data['mode'] == translations.fire:
            if self.haLightModeText:
                self.call_service('input_text/set_value',
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
            if roomname is None:
                self.call_service('input_text/set_value',
                    value = self.current_MODE,
                    entity_id = self.haLightModeText,
                    namespace = self.HASS_namespace
                )

        # Morning and Night handling
    def _cancel_listening_for_morning(self, kwargs) -> None:
        """ Cancels the listen for morning handler.
        """
        for handler in self.morning_handler:
            try:
                if self.cancel_listen_state(handler):
                    self.log(f"Cancel listen state {handler} ended", level = 'DEBUG')
                else:
                    self.log(f"Cancel listen state {handler} not stopped", level = 'DEBUG')
            except Exception as exc:
                self.log(f"Not possible to stop {handler}. Exception: {exc}")
        self.morning_handler = []

    def _cancel_listening_for_night(self) -> None:
        """ Cancels the listen for night handler.
        """
        for handler in self.night_handler:
            try:
                if self.cancel_listen_state(handler):
                    self.log(f"Cancel listen state {handler} ended", level = 'DEBUG')
                else:
                    self.log(f"Cancel listen state {handler} not stopped", level = 'DEBUG')
            except Exception as exc:
                self.log(f"Not possible to stop {handler}. Exception: {exc}")
        self.night_handler = []

    def _waiting_for_morning(self, kwargs) -> None:
        """ Starts listening for sensors activating morning/normal mode.
        """
        if self.current_MODE != translations.away:
            if self.keep_mode_when_outside is not None:
                self.turn_off(self.keep_mode_when_outside, namespace = self.HASS_namespace)

            for sensor in self.morning_sensors:
                handler = self.listen_state(self._waking_up, sensor,
                    new = 'on',
                    namespace = self.HASS_namespace
                )
                self.morning_handler.append(handler)

    def _waiting_for_night(self, kwargs) -> None:
        """ Starts listening for sensors activating night.
        """
        for sensor in self.night_sensors:
            handler = self.listen_state(self._going_to_bed, sensor,
                new = 'on',
                namespace = self.HASS_namespace
            )
            self.night_handler.append(handler)

    def _changeMorningToDay(self, kwargs) -> None:
        """ Changes mode from morning to normal at given time.
        """
        if self.current_MODE == translations.morning:
            self.fire_event(translations.MODE_CHANGE, mode = translations.automagical, namespace = self.HASS_namespace)

    def _waking_up(self, entity, attribute, old, new, kwargs) -> None:
        """ Reacts to morning sensors
        """
        if (
            self.now_is_between(self.morning_runtime, self.morning_to_day)
            and not self._is_holiday(datetime.date.today())
        ):
            self.fire_event(translations.MODE_CHANGE, mode = translations.morning, namespace = self.HASS_namespace)
        else:
            self.fire_event(translations.MODE_CHANGE, mode = translations.automagical, namespace = self.HASS_namespace)
        self._cancel_listening_for_morning(0)

    def _going_to_bed(self, entity, attribute, old, new, kwargs) -> None:
        """ Reacts to night sensors
        """
        if self.current_MODE != translations.away:
            self.fire_event(translations.MODE_CHANGE, mode = translations.night, namespace = self.HASS_namespace)
        self._cancel_listening_for_night()

    def _good_day_now(self, kwargs) -> None:
        """ Change to normal day light at this time if mode is night or morning.
        """
        if (
            self.current_MODE.startswith(translations.night)
            or self.current_MODE == translations.morning
        ):
            self.fire_event(translations.MODE_CHANGE, mode = translations.automagical, namespace = self.HASS_namespace)
        self._cancel_listening_for_morning(0)

    def _good_night_now(self, kwargs) -> None:
        """ Change to night at the given time.
        """
        if (
            self.current_MODE != translations.away
            and self.current_MODE != translations.night
        ):
            self.fire_event(translations.MODE_CHANGE, mode = translations.night, namespace = self.HASS_namespace)
        self._cancel_listening_for_night()

        # Door functions
    def enableRelockDoor(self) -> None:
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set/auto_relock",
                payload = "true",
                namespace = self.MQTT_namespace
            )
        self.run_in(self.lockDoor, 10)

    def lockDoor(self, kwargs) -> None:
        """ Locks the MQTT door.
        """
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set",
                payload = "LOCK",
                namespace = self.MQTT_namespace
            )

    def disableRelockDoor(self) -> None:
        """ Disables auto relock in door.
        """
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set/auto_relock",
                payload = "false",
                namespace = self.MQTT_namespace
            )
        self.run_in(self.unlockDoor, 3)

    def unlockDoor(self, kwargs) -> None:
        """ Unlocks the MQTT door, and disables auto relock.
        """
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set",
                payload = "UNLOCK",
                namespace = self.MQTT_namespace
            )
        self.lastUnlockUser = 0

        # Doorlock listen
    def MQTT_doorlock_event(self, event_name, data, **kwargs) -> None:
        """ Listens to MQTT door events.
        """
        try:
            data = json.loads(data['payload'])
        except Exception as e:
            self.log(f"Could not get payload from topic for {data}. Exception: {e}", level = 'DEBUG')
            return
        if (
            data['last_unlock_source'] != 'self'
            and data['state'] == 'UNLOCK'
        ):
            self.lastUnlockTime = datetime.datetime.now()
            self.lastUnlockUser = data['last_unlock_user']

            for person in self.presence:
                if self.lastUnlockUser == person.lock_user:
                    if (
                        person.role == 'housekeeper'
                        and self.current_MODE == translations.away
                        #and self.housekeeperAtHome >= 1
                    ):
                        self.current_MODE = translations.wash
                        self.fire_event(translations.MODE_CHANGE, mode = translations.wash, namespace = self.HASS_namespace)
                    data = {
                        'tag' : 'last_unlock_user'
                        }
                    self.notify_app.send_notification(
                        message = f"{person.person_id} unlocked the door",
                        message_title = "Door unlock",
                        message_recipient = self.notify_receiver,
                        also_if_not_home = True,
                        data = data
                    )
                    break
                    
            if not self.anyone_at_main_house_home():
                self.nofify_on_alarm = False
                self.run_in(self._reset_alarm_notification, 20)

    def _vacation_ending(self, entity, attribute, old, new, kwargs) -> None:
        """ Ends vacation when switch/button is turned off.
        """
        if new == 'on':
            self.away_state = True
        elif new == 'off':
            self.away_state = False
            self.start_vacuum()

    def _outsideChange(self, entity, attribute, old, new, kwargs) -> None:
        """ Listens for trackers and switches on presence.
        """
        # React to manual switches
        for person in self.presence:
            if person.outside_switch == entity:
                if new == 'on':
                    person.update_is_outside(is_outside=True)
                    if person.home:
                        self._away(person=person)

                elif new == 'off':
                    person.update_is_outside(is_outside=False)
                    if person.home:
                        self._home(person=person)

    def _presenceChange(self, entity, attribute, old, new, kwargs) -> None:
        """ Listens for trackers and switches on presence.
        """
        # React to presence trackers
        for person in self.presence:
            if person.person_id == entity:
                if new == 'home':
                    person.update_state(is_home=True)
                    if person.outside_activated:
                        self.ADapi.log(f"{person.person_id} outside activated when returning home. Is home: {person.is_home()}") ###
                        return
                    self._home(person=person)

                elif old == 'home':
                    person.update_state(is_home=False)
                    if person.outside_activated:
                        self.ADapi.log(f"{person.person_id} already outside activated when going away. Is home: {person.is_home()}") ###
                        return
                    self._away(person=person)

    def _home(self, person:Person) -> None:

        if person.role == 'adult':
            self.stop_vacuum()
            self.adultAtHome += 1
        elif person.role == 'kid':
            self.kidsAtHome += 1
        elif person.role == 'family':
            self.stop_vacuum()
            self.extendedFamilyAtHome += 1
        elif person.role == 'tenant':
            self.tenantAtHome += 1
            return # No current logic
        elif person.role == 'housekeeper':
            self.housekeeperAtHome += 1

        if self.adultAtHome + self.kidsAtHome + self.extendedFamilyAtHome >= 1:
            if self.current_MODE == translations.away:
                self.current_MODE = translations.automagical
                self.fire_event(translations.MODE_CHANGE, mode = translations.automagical)
                self.stop_alarm()

            if self.away_handler is not None:
                if self.timer_running(self.away_handler):
                    try:
                        self.cancel_timer(self.away_handler)
                    except Exception as e:
                        self.log(
                            f"Was not able to stop existing handler to stop setting away state. {e}",
                            level = "DEBUG"
                        )
                self.away_handler = None
            
            if self.adultAtHome + self.extendedFamilyAtHome >= 1 and self.current_MODE not in (translations.away, translations.night):
                self.disableRelockDoor()

        elif person.role == 'housekeeper':
            data = {
                'tag' : 'last_unlock_user'
                }
            self.notify_app.send_notification(
                message = f"Housekeeper {person.person_id} entered",
                message_title = "Housekeeping",
                message_recipient = self.notify_receiver,
                also_if_not_home = True,
                data = data
            )
            if self.current_MODE == translations.away:
                self.stop_alarm()

    def _away(self, person:Person) -> None:

        enable_start_vacuum = False

        if person.role == 'adult':
            self.adultAtHome -= 1
            enable_start_vacuum = True
        elif person.role == 'kid':
            self.kidsAtHome -= 1
        elif person.role == 'family':
            self.extendedFamilyAtHome -= 1
        elif person.role == 'tenant':
            self.tenantAtHome -= 1
            return
        elif person.role == 'housekeeper':
            self.housekeeperAtHome -= 1
        
        if (
            person.stopMorning
            and self.current_MODE == translations.morning
            and self.anyone_at_main_house_home()
        ):
            self.current_MODE = translations.automagical
            self.fire_event(translations.MODE_CHANGE, mode = translations.automagical, namespace = self.HASS_namespace)
            return


        if self.adultAtHome + self.extendedFamilyAtHome == 0:
            self.enableRelockDoor()

            if self.get_state(self.keep_mode_when_outside, namespace = self.HASS_namespace) == 'on':
                return
            
            if (
                self.current_MODE.startswith(translations.night)
                and self.now_is_between(self.night_runtime, self.morning_runtime)
            ):
                return

            self.away_handler = self.run_in(
                                            self.setAwayMode,
                                            self.delay_before_setting_away,
                                            enable_start_vacuum = enable_start_vacuum)

    def setAwayMode(self, **kwargs) -> None:
        """ Sets away mode.
        """
        enable_start_vacuum = kwargs['enable_start_vacuum']
        if (
            not self.away_state
            and self.now_is_between(self.morning_runtime, '18:00:00')
            and enable_start_vacuum
        ):
            self.start_vacuum()

        if not self.anyone_at_main_house_home():
            self.start_alarm()

            if self.current_MODE != translations.away:
                self.current_MODE = translations.away
                self.fire_event(translations.MODE_CHANGE, mode = translations.away, namespace = self.HASS_namespace)

        #Function to handle notification when nobody is home
    def start_alarm(self) -> None:
        """ Starts listening for sensor activity.
        """
        if not self.alarm_active:
            for sensor in self.alarmsensors:
                handle = self.listen_state(self._sensor_activated, sensor,
                    new = 'on',
                    namespace = self.HASS_namespace
                )
                self.sensor_handle.append(handle)
            self.alarm_active = True
            self.nofify_on_alarm = True

    def stop_alarm(self) -> None:
        """ Stops listening for sensor activity.
        """
        for handle in self.sensor_handle:
            try:
                self.cancel_listen_state(handle)
            except:
                self.log(f"Not able to stop listen state for {handle}", level = 'DEBUG')
        self.sensor_handle = []
        self.alarm_active = False

    def _sensor_activated(self, entity, attribute, old, new, kwargs) -> None:
        """ Listens for sensors to send notification if triggered and play music.
        """
        for person in self.presence:
            if person.role != 'tenant':
                if person.is_home():
                    return

        if self.nofify_on_alarm:
            data = {
                'tag' : 'sensor_activated_in_modeManagement'
                }
            self.notify_app.send_notification(
                message = f"{entity}",
                message_title = "Sensor triggered",
                message_recipient = self.notify_receiver,
                also_if_not_home = True,
                data = data
            )
            self.nofify_on_alarm = False
            self.run_in(self._reset_alarm_notification, 600)

        for play_media in self.alarm_media:
            if 'amp' in play_media:
                if 'source' in play_media:
                    self.call_service('media_player/select_source',
                        entity_id = play_media['amp'],
                        source = play_media['source'],
                        namespace = self.HASS_namespace
                    )
                if 'volume' in play_media:
                    self.call_service('media_player/volume_set',
                        entity_id = play_media['amp'],
                        volume_level = play_media['volume'],
                        namespace = self.HASS_namespace
                    )
            self.run_in(self.play_alarm_on_speakers, 8,
                play_media = play_media
            )

    def play_alarm_on_speakers(self, **kwargs) -> None:
        """ Plays media after sensor is triggered.
        """
        play_media = kwargs['play_media']
        self.call_service('media_player/play_media',
            entity_id = play_media['player'],
            media_content_id = play_media['playlist'],
            media_content_type = 'music',
            namespace = self.HASS_namespace
        )
        if 'normal_volume' in play_media:
            self.run_in(self._reset_soundlevel, 120,
                play_media = play_media
            )

    def _reset_soundlevel(self, **kwargs) -> None:
        """ Sets sound level back to normal volume after alarm.
        """
        play_media = kwargs['play_media']
        self.call_service('media_player/volume_set',
            entity_id = play_media['amp'],
            volume_level = play_media['normal_volume'],
            namespace = self.HASS_namespace
        )

    def _reset_alarm_notification(self, kwargs) -> None:
        """ Resets timer so that any sensors triggered it will send a new notification.
        """
        self.nofify_on_alarm = True

    def stop_vacuum(self) -> None:
        for robot in self.vacuum:
            if not robot.manual_start and self.get_state(robot.vacuum) == 'cleaning':
                self.call_service('vacuum/return_to_base', entity_id = robot.vacuum, namespace = self.HASS_namespace)


    def start_vacuum(self) -> None:
        for robot in self.vacuum:
            for item in robot.prevent_vacuum:
                if self.get_state(item, namespace = self.HASS_namespace) == 'on':
                    continue
            if (
                (self.get_state(robot.vacuum, namespace = self.HASS_namespace) == 'docked'
                or self.get_state(robot.vacuum, namespace = self.HASS_namespace) == 'charging')
            ):
                if self.get_battery_level(robot=robot) > 40:
                    # Start robot by daily routine if provided, else full program
                    if 'daily_routine' in robot:
                        if robot.daily_routine.startswith('button'):
                            self.call_service('button/press',
                                entity_id = robot.daily_routine,
                                namespace = self.HASS_namespace)
                        else:
                            try:
                                self.call_service('switch/turn_on',
                                    entity_id = robot.daily_routine,
                                    namespace = self.HASS_namespace)
                            except Exception as e:
                                self.log(
                                    f"Not able to start {robot.daily_routine}. Not a button or a switch. "
                                    f"Please make a feasture request with information and error log: {e}",
                                    level = 'INFO'
                                )
                    else:
                        self.call_service('vacuum/start',
                            entity_id = robot.vacuum,
                            namespace = self.HASS_namespace)
                    robot.manual_start = False
            else:
                robot.manual_start = True

    def get_battery_level(self, robot):
        battery_level = 101
        if robot.battery is not None:
            try:
                battery_level = float(self.get_state(robot.battery, namespace = self.HASS_namespace))
            except (ValueError, TypeError):
                pass
        if battery_level == 101:
            try:
                battery_level = float(self.get_state(robot.vacuum, attribute='battery_level', namespace = self.HASS_namespace))
            except (ValueError, TypeError):
                self.log(
                    f"Not able to get battery_level from {robot.vacuum}. Try defining 'battery: sensor.vacuum_battery' for your robot",
                    level = 'INFO'
                )
                battery_level = 100
        return battery_level


    def _is_holiday(self, date):
        if self.holidays is not None:
            isNotWorkday:bool = date in self.holidays
            if not isNotWorkday:
                isNotWorkday = date.weekday() > 4
            return isNotWorkday
        return False

class Notify_Mobiles:
    """ Class to send notification with 'notify' HA integration
    """
    def __init__(self, api):
        self.ADapi = api

    def send_notification(self, **kwargs) -> None:
        """ Sends notification to recipients via Home Assistant notification.
        """
        message:str = kwargs['message']
        message_title:str = kwargs.get('message_title', 'Home Assistant')
        message_recipient:str = kwargs.get('message_recipient', True)
        also_if_not_home:bool = kwargs.get('also_if_not_home', True)
        data:dict = kwargs.get('data', {'clickAction' : 'noAction'})

        for re in message_recipient:
            self.ADapi.call_service(f'notify/{re}',
                title = message_title,
                message = message,
                data = data
            )