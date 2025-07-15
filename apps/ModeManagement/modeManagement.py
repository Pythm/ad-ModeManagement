""" Mode Event Management

    @Pythm / https://github.com/Pythm
"""
__version__ = "0.1.12"

from appdaemon.plugins.hass.hassapi import Hass
import datetime
import json

NORMAL_TRANSLATE:str = 'normal'
MORNING_TRANSLATE:str = 'morning'
AWAY_TRANSLATE:str = 'away'
OFF_TRANSLATE:str = 'off'
NIGHT_TRANSLATE:str = 'night'
CUSTOM_TRANSLATE:str = 'custom'
FIRE_TRANSLATE:str = 'fire'
FALSE_ALARM_TRANSLATE:str = 'false-alarm'
WASH_TRANSLATE:str = 'wash'
RESET_TRANSLATE:str = 'reset'

@staticmethod
def split_around_underscore(input_string):
    index = input_string.find('_')
    
    if index != -1:
        part_before = input_string[:index]
        part_after = input_string[index + 1:]
        return part_before, part_after
    else:
        return None, None

class ModeManagement(Hass):

    def initialize(self):

        self.mqtt = None

        # Namespaces for HASS and MQTT
        self.HASS_namespace:str = self.args.get('HASS_namespace', 'default')
        self.MQTT_namespace:str = self.args.get('MQTT_namespace', 'default')
        
        self.event_listen_str:str = 'MODE_CHANGE'
        language = self.args.get('lightwand_language', 'en')
        language_file = self.args.get('language_file', '/conf/apps/Lightwand/translations.json')
        try:
            with open(language_file) as lang:
                translations = json.load(lang)
        except FileNotFoundError:
            self.log("Translation file not found", level = 'DEBUG')
        else:
            self.event_listen_str = translations[language]['MODE_CHANGE']
            global NORMAL_TRANSLATE
            NORMAL_TRANSLATE = translations[language]['normal']
            global MORNING_TRANSLATE
            MORNING_TRANSLATE = translations[language]['morning']
            global AWAY_TRANSLATE
            AWAY_TRANSLATE = translations[language]['away']
            global OFF_TRANSLATE
            OFF_TRANSLATE = translations[language]['off']
            global NIGHT_TRANSLATE
            NIGHT_TRANSLATE = translations[language]['night']
            global CUSTOM_TRANSLATE
            CUSTOM_TRANSLATE = translations[language]['custom']
            global FIRE_TRANSLATE
            FIRE_TRANSLATE = translations[language]['fire']
            global FALSE_ALARM_TRANSLATE
            FALSE_ALARM_TRANSLATE = translations[language]['false-alarm']
            global WASH_TRANSLATE
            WASH_TRANSLATE = translations[language]['wash']
            global RESET_TRANSLATE
            RESET_TRANSLATE = translations[language]['reset']

        # Set up notification
        self.notify_reciever = self.args.get('notify_reciever', [])
        name_of_notify_app = self.args.get('notify_app', None)
        if name_of_notify_app is not None:
            self.notify_app = self.get_app(name_of_notify_app)
        else:
            self.notify_app = Notify_Mobiles(self)
        self.nofify_on_alarm:bool = True


        # Holliday switch from Home Assistant
        if 'away_state' in self.args: # Old name for vacation
            self.away_state = self.args['away_state']
            self.listen_state(self._vacation_ending, self.away_state,
                new = 'off',
                namespace = self.HASS_namespace)
        elif 'vacation' in self.args:
            self.away_state = self.args['vacation']
            self.listen_state(self._vacation_ending, self.away_state,
                new = 'off',
                namespace = self.HASS_namespace)
        else:
            self.away_state = 'input_boolean.vacation'
            if not self.entity_exists(self.away_state, namespace = self.HASS_namespace):
                self.call_service("state/set",
                    entity_id = self.away_state,
                    attributes = {'friendly_name' : 'Vacation'},
                    state = 'off',
                    namespace = self.HASS_namespace
                )
            else:
                self.log(
                    "'vacation' not configured. Using 'input_boolean.vacation' as default away state",
                    level = 'INFO'
                )


        # Day to day mode management automation
        if 'workday' in self.args:
            self.workday = self.args['workday']
        else:
            self.workday = 'binary_sensor.workday_sensor_AD'
            if (
                not self.entity_exists(self.workday, namespace = self.HASS_namespace)
                and not self.entity_exists('binary_sensor.workday_sensor', namespace = self.HASS_namespace)
            ):
                self.call_service("state/set",
                    entity_id = self.workday,
                    attributes = {'friendly_name' : 'Workday'},
                    state = 'on',
                    namespace = self.HASS_namespace
                )
                self.log(
                    "'workday' binary_sensor not defined in app configuration. Will fire morning mode every day. "
                    "https://www.home-assistant.io/integrations/workday/",
                    level = 'INFO'
                )


        # Presence detection and HA switch for manual override
        self.adultAtHome:int = 0
        self.kidsAtHome:int = 0
        self.extendedFamilyAtHome:int = 0
        self.tenantAtHome:int = 0
        self.housekeeperAtHome:int = 0

        self.presence = self.args['presence']
        for person in self.presence:
            if not 'role' in person:
                person.update(
                    {'role' : 'adult'}
                )
            self.listen_state(self._presenceChange, person['person'], namespace = self.HASS_namespace)
            person.update(
                {'state' : self.get_state(person['person']), 'last_lock' : False}
            )

            if 'outside' in person:
                self.listen_state(self._presenceChange, person['outside'], namespace = self.HASS_namespace)
            elif person['role'] in ['adult', 'kid']:
                name:str = person['person']
                if name[:6] == 'person':
                    name = name[7:]
                elif name[:14] == 'device_tracker':
                    name = name[14:]
                person['outside'] = 'input_boolean.outside_' + name

            if 'outside' in person:
                if not self.entity_exists(person['outside'], namespace = self.HASS_namespace):
                    self.call_service("state/set",
                        entity_id = person['outside'],
                        attributes = {'friendly_name' : str(person['person']) + ' Outside'},
                        state = 'off',
                        namespace = self.HASS_namespace
                    )

            if person['state'] == 'home':
                if person['role'] == 'adult':
                    self.adultAtHome += 1
                if person['role'] == 'kid':
                    self.kidsAtHome += 1
                if person['role'] == 'tenant':
                    self.tenantAtHome += 1
                if person['role'] == 'housekeeper':
                    self.housekeeperAtHome += 1

        self.keep_mode_when_outside = self.args.get('keep_mode_when_outside', None)
        self.delay_before_setting_away = self.args.get('delay_before_setting_away', 0)
        self.away_handler = None


        # Set up notification if sensor is activated when no one is home
        self.alarmsensors = self.args.get('alarmsensors',[])
        self.sensor_handle:list = []
        self.alarm_active:bool = False
        self.alarm_media = self.args.get('alarm_media', [])


        # Start vacuum robots when no adults is home
        self.vacuum = self.args.get('vacuum',[])
        self.prevent_vacuum = self.args.get('prevent_vacuum', [])
        self.stop_vacuum:bool = False


        # MQTT Door lock
        self.MQTT_door_lock:list = self.args.get('MQTT_door_lock',[])
        if (
            self.MQTT_door_lock
            and not self.mqtt
        ):
            self.mqtt = self.get_plugin_api("MQTT")
        self.lastUnlockTime = datetime.datetime.now()

        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_subscribe(door)
            self.mqtt.listen_event(self.MQTT_doorlock_event, "MQTT_MESSAGE",
                topic = door,
                namespace = self.MQTT_namespace
            )


        # Update current mode to a Home Assistant input_text
        self.haLightModeText = self.args.get('HALightModeText', None) 


        # Setting data
        if self.get_state(self.away_state, namespace = self.HASS_namespace) == 'off':
            if self.haLightModeText:
                self.current_MODE = self.get_state(self.haLightModeText, namespace = self.HASS_namespace)
            elif self.now_is_between('02:00:00', '05:00:00'):
                self.current_MODE = NIGHT_TRANSLATE
            else:
                self.current_MODE = NORMAL_TRANSLATE
        else:
            self.current_MODE = AWAY_TRANSLATE
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
            and self.current_MODE == NIGHT_TRANSLATE
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
            and self.current_MODE != NIGHT_TRANSLATE
        ):
            self.run_in(self._waiting_for_night, 1)
        self.run_daily(self._good_night_now, self.execute_night)

        # Listens for mode events
        self.listen_event(self.mode_event, self.event_listen_str, namespace = self.HASS_namespace)


    def anyone_home(self) -> bool:
        if (
            self.adultAtHome == 0
            and self.kidsAtHome == 0
            and self.housekeeperAtHome == 0
            and self.tenantAtHome == 0
        ):
            return False
        return True


    def mode_event(self, event_name, data, kwargs) -> None:
        """ Listens to mode events and reacts on night, morning, normal.
            Also updates the input_text with mode.
        """
        modename, roomname = split_around_underscore(data['mode'])
        if modename is None:
            modename = data['mode']
        # Morning
        if (
            self.current_MODE == MORNING_TRANSLATE
            and self.now_is_between(self.morning_runtime, self.execute_morning)
            and modename == OFF_TRANSLATE
            and roomname is not None
        ):
            return
        if (
            self.current_MODE == NIGHT_TRANSLATE
            and self.now_is_between(self.morning_runtime, self.execute_morning)
            and (modename == NORMAL_TRANSLATE
            or modename == MORNING_TRANSLATE)
        ):
                for item in self.turn_on_in_the_morning:
                    if self.get_state(item, namespace = self.HASS_namespace) == 'off':
                        self.turn_on(item, namespace = self.HASS_namespace)
                self._cancel_listening_for_morning(0)
                self.disableRelockDoor()

        # Night
        if (
            data['mode'] == NIGHT_TRANSLATE
            and self.now_is_between(self.night_runtime, self.execute_night)
        ):
            for item in self.turn_off_at_night:
                if self.get_state(item, namespace = self.HASS_namespace) == 'on':
                    self.turn_off(item, namespace = self.HASS_namespace)

            self._cancel_listening_for_night()

            self.enableRelockDoor()

        # Away
        if data['mode'] == AWAY_TRANSLATE:
            self.start_alarm()

            self.enableRelockDoor()

        elif data['mode'] == FALSE_ALARM_TRANSLATE:
            modename = self.current_MODE
            self.fire_event(self.event_listen_str, mode = self.current_MODE, namespace = self.HASS_namespace)

        elif data['mode'] == FIRE_TRANSLATE:
            self.call_service('input_text/set_value',
                value = FIRE_TRANSLATE,
                entity_id = self.haLightModeText,
                namespace = self.HASS_namespace
            )
            return

        # Set mode
        if roomname is None:
            if modename == RESET_TRANSLATE:
                self.current_MODE = NORMAL_TRANSLATE
            else:
                self.current_MODE = modename

        if self.haLightModeText:
            if roomname is not None:
                self.call_service('input_text/set_value',
                    value = f"{modename} in {roomname}",
                    entity_id = self.haLightModeText,
                    namespace = self.HASS_namespace
                )
            else:
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
        if self.current_MODE != AWAY_TRANSLATE:
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
        if self.current_MODE == MORNING_TRANSLATE:
            self.fire_event(self.event_listen_str, mode = NORMAL_TRANSLATE, namespace = self.HASS_namespace)


    def _waking_up(self, entity, attribute, old, new, kwargs) -> None:
        """ Reacts to morning sensors
        """
        if (
            self.now_is_between(self.morning_runtime, self.morning_to_day)
            and self.get_state(self.workday, namespace = self.HASS_namespace) == 'on'
        ):
            self.fire_event(self.event_listen_str, mode = MORNING_TRANSLATE, namespace = self.HASS_namespace)
        else:
            self.fire_event(self.event_listen_str, mode = NORMAL_TRANSLATE, namespace = self.HASS_namespace)
        self._cancel_listening_for_morning(0)


    def _going_to_bed(self, entity, attribute, old, new, kwargs) -> None:
        """ Reacts to night sensors
        """
        if self.current_MODE != AWAY_TRANSLATE:
            self.fire_event(self.event_listen_str, mode = NIGHT_TRANSLATE, namespace = self.HASS_namespace)
        self._cancel_listening_for_night()


    def _good_day_now(self, kwargs) -> None:
        """ Change to normal day light at this time if mode is night or morning.
        """
        if (
            self.current_MODE == NIGHT_TRANSLATE
            or self.current_MODE == MORNING_TRANSLATE
        ):
            self.fire_event(self.event_listen_str, mode = NORMAL_TRANSLATE, namespace = self.HASS_namespace)
        self._cancel_listening_for_morning(0)


    def _good_night_now(self, kwargs) -> None:
        """ Change to night at the given time.
        """
        if (
            self.current_MODE != AWAY_TRANSLATE
            and self.current_MODE != NIGHT_TRANSLATE
        ):
            self.fire_event(self.event_listen_str, mode = NIGHT_TRANSLATE, namespace = self.HASS_namespace)
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


        # Doorlock listen
    def MQTT_doorlock_event(self, event_name, data, kwargs) -> None:
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

            for person in self.presence:
                if person['role'] == 'housekeeper':
                    if (
                        data['last_unlock_user'] == person['lock_user']
                        and self.current_MODE == AWAY_TRANSLATE
                        and self.housekeeperAtHome >= 1
                    ):
                        self.current_MODE = WASH_TRANSLATE
                        self.fire_event(self.event_listen_str, mode = WASH_TRANSLATE, namespace = self.HASS_namespace)
                        data = {
                            'tag' : 'housekeeperdoor'
                            }
                        self.notify_app.send_notification(
                            message = f"Housekeeper {entity} unlocked door. Turned on wash lights",
                            message_title = "Housekeeper",
                            message_recipient = self.notify_reciever,
                            also_if_not_home = True,
                            data = data
                        )

                if 'lock_user' in person:
                    if data['last_unlock_user'] == person['lock_user']:
                        if not person['last_lock']:
                            if 'outside' in person:
                                self.turn_off(person['outside'], namespace = self.HASS_namespace)
                            person.update(
                                {'last_lock' : True}
                            )
                    else:
                        person.update(
                            {'last_lock' : False}
                        )
        elif (
            data['last_unlock_source'] != 'self'
            and data['state'] == 'LOCK'
        ):
            for person in self.presence:
                person.update(
                    {'last_lock' : False}
                )


    def _vacation_ending(self, entity, attribute, old, new, kwargs) -> None:
        """ Ends vacation when switch/button is turned off.
        """
        for robot in self.vacuum:
            if (
                (self.get_state(robot, namespace = self.HASS_namespace) == 'docked'
                or self.get_state(robot, namespace = self.HASS_namespace) == 'charging')
                and self.get_state(robot, attribute='battery_level', namespace = self.HASS_namespace) > 40
            ):
                self.call_service('vacuum/start', entity_id = robot, namespace = self.HASS_namespace)


    def _presenceChange(self, entity, attribute, old, new, kwargs) -> None:
        """ Listens for trackers and switches on presence.
        """
        # React to manual switches
        if new == 'on':
            new = AWAY_TRANSLATE
            old = 'home'
            for person in self.presence:
                if 'outside' in person:
                    if person['outside'] == entity:
                        entity = person['person']
        elif new == 'off':
            for person in self.presence:
                if 'outside' in person:
                    if person['outside'] == entity:
                        entity = person['person']
                        self.log(f"{person['person']} is: {self.get_state(person['person'], namespace = self.HASS_namespace)} when turning off outside switch") ###
                        if self.get_state(person['person'], namespace = self.HASS_namespace) == 'home':
                            new = 'home'


        # React to presence trackers
        if new == 'home':
            entity_tenant = False

            for person in self.presence:
                if person['person'] == entity:
                    if 'outside' in person:
                        if self.get_state(person['outside'], namespace = self.HASS_namespace) == 'on':
                            return
                    person.update(
                        {'state': new }
                    )
                    if person['role'] == 'adult':
                        if self.adultAtHome == 0:
                            if self.stop_vacuum:
                                for robot in self.vacuum:
                                    if self.get_state(robot) == 'cleaning':
                                        self.call_service('vacuum/return_to_base', entity_id = robot, namespace = self.HASS_namespace)
                                self.stop_vacuum = False
                        self.adultAtHome += 1
                    elif person['role'] == 'kid':
                        self.kidsAtHome += 1
                    elif person['role'] == 'tenant':
                        self.tenantAtHome += 1
                        entity_tenant = True
                    elif person['role'] == 'housekeeper':
                        self.housekeeperAtHome += 1
                    break

            if (
                self.adultAtHome + self.kidsAtHome >= 1
                and not entity_tenant
            ):
                if self.current_MODE == AWAY_TRANSLATE:
                    self.current_MODE = NORMAL_TRANSLATE
                    self.fire_event(self.event_listen_str, mode = NORMAL_TRANSLATE)
                    self.stop_alarm()

                if self.away_handler is not None:
                    if self.timer_running(self.away_handler):
                        try:
                            self.cancel_timer(self.away_handler)
                            self.log(f"Stopped existing handler to stop setting away state", level = "INFO") ###
                        except Exception as e:
                            self.log(
                                f"Was not able to stop existing handler to stop setting away state. {e}",
                                level = "DEBUG"
                            )
                    self.away_handler = None
                
                if self.adultAtHome >= 1:
                    self.disableRelockDoor()


            elif self.housekeeperAtHome >= 1:
                data = {
                    'tag' : 'housekeeperdoor'
                    }
                self.notify_app.send_notification(
                    message = f"Housekeeper {entity} entered",
                    message_title = "Housekeeping",
                    message_recipient = self.notify_reciever,
                    also_if_not_home = True,
                    data = data
                )
                if self.current_MODE == AWAY_TRANSLATE:
                    self.stop_alarm()

        elif old == 'home':
            start_vacuum = False

            for person in self.presence:
                if person['person'] == entity:
                    person.update(
                        {'state': new }
                    )
                    if person['role'] == 'adult':
                        self.adultAtHome -= 1
                        start_vacuum = True
                    elif person['role'] == 'kid':
                        self.kidsAtHome -= 1
                    elif person['role'] == 'tenant':
                        self.tenantAtHome -= 1
                    elif person['role'] == 'housekeeper':
                        self.housekeeperAtHome -= 1
                    
                    if (
                        'stopMorning' in person
                        and self.current_MODE == MORNING_TRANSLATE
                        and self.adultAtHome + self.kidsAtHome + self.housekeeperAtHome != 0
                    ):
                        self.current_MODE = NORMAL_TRANSLATE
                        self.fire_event(self.event_listen_str, mode = NORMAL_TRANSLATE, namespace = self.HASS_namespace)

                    break

            if self.adultAtHome == 0:
                if self.get_state(self.keep_mode_when_outside, namespace = self.HASS_namespace) == 'on':
                    return
                if (
                    str(self.current_MODE)[:5] == NIGHT_TRANSLATE
                    and self.now_is_between(self.night_runtime, self.morning_runtime)
                ):
                   return

                self.enableRelockDoor()

                self.away_handler = self.run_in(self.setAwayMode, self.delay_before_setting_away, start_vacuum = start_vacuum)


    def setAwayMode(self, **kwargs) -> None:
        """ Sets away mode.
        """
        start_vacuum = kwargs['start_vacuum']
        for item in self.prevent_vacuum:
            if self.get_state(item, namespace = self.HASS_namespace) == 'on':
                start_vacuum = False
        if (
            self.get_state(self.away_state, namespace = self.HASS_namespace) == 'off'
            and self.now_is_between(self.morning_runtime, '18:00:00')
            and start_vacuum
        ):
            for robot in self.vacuum:
                if (
                    (self.get_state(robot, namespace = self.HASS_namespace) == 'docked'
                    or self.get_state(robot, namespace = self.HASS_namespace) == 'charging')
                    and self.get_state(robot, attribute='battery_level', namespace = self.HASS_namespace) > 40
                ):
                    self.call_service('vacuum/start', entity_id = robot, namespace = self.HASS_namespace)
                    self.stop_vacuum = True


        if self.kidsAtHome == 0:
            if self.housekeeperAtHome == 0:
                self.start_alarm()

                if self.current_MODE != AWAY_TRANSLATE:
                    self.current_MODE = AWAY_TRANSLATE
                    self.fire_event(self.event_listen_str, mode = AWAY_TRANSLATE, namespace = self.HASS_namespace)


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
            if person['role'] != 'tenant':
                if person['state'] == 'home':
                    return

        if self.nofify_on_alarm:
            
            self.notify_app.send_notification(
                message = f"{entity}",
                message_title = "Sensor triggered",
                message_recipient = self.notify_reciever,
                also_if_not_home = True
            )
            self.nofify_on_alarm = False
            self.run_in(self._reset_alarm_notification, 600)

        for play_media in self.alarm_media:
            self.call_service('media_player/select_source',
                entity_id = play_media['amp'],
                source = play_media['source'],
                namespace = self.HASS_namespace
            )
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
        self.run_in(self._reset_soundlevel, 10,
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