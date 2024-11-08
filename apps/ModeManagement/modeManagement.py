""" Mode Event Management

    @Pythm / https://github.com/Pythm
"""
__version__ = "0.1.6"

import appdaemon.plugins.hass.hassapi as hass
import datetime
import json

class ModeManagement(hass.Hass):

    def initialize(self):

        self.mqtt = None

        # Namespaces for HASS and MQTT
        self.HASS_namespace:str = self.args.get('HASS_namespace', 'default')
        self.MQTT_namespace:str = self.args.get('MQTT_namespace', 'default')


        # Set up notification
        self.notify_app = Notify_Mobiles(self)
        self.notify_reciever = self.args.get('notify_reciever', [])
        self.nofify_on_alarm = True


        # Holliday switch from Home Assistant
        if 'away_state' in self.args: # Old name for entity
            self.away_state = self.args['away_state']
            self.listen_state(self.vacation_ending, self.away_state, new = 'off')
        elif 'vacation' in self.args:
            self.away_state = self.args['vacation']
            self.listen_state(self.vacation_ending, self.away_state, new = 'off')
        else:
            self.away_state = 'input_boolean.vacation'
            if not self.entity_exists(self.get_entity(self.away_state)):
                self.set_state(self.away_state,
                    state = 'off'
                )
            else:
                self.log(
                    "'vacation' not configured. Using 'input_boolean.vacation' as default away state",
                    level = 'WARNING'
                )


        # Day to day mode management automation
        if 'workday' in self.args:
            self.workday = self.args['workday']
        else:
            self.workday = 'binary_sensor.workday_sensor'
            if not self.entity_exists(self.get_entity(self.workday)):
                self.set_state(self.workday,
                    state = 'on'
                )
                self.log(
                    "'workday' binary_sensor not defined in app configuration. Will fire morning mode every day. "
                    "https://www.home-assistant.io/integrations/workday/",
                    level = 'INFO'
                )


        # Presence detection and HA switch for manual override
        self.adultAtHome = 0
        self.kidsAtHome = 0
        self.tenantAtHome = 0
        self.housekeeperAtHome = 0

        self.presence = self.args['presence']
        for person in self.presence:
            self.listen_state(self.presenceChange, person['person'])
            person.update(
                {'state' : self.get_state(person['person']), 'last_lock' : False}
            )

            if 'outside' in person:
                self.listen_state(self.presenceChange, person['outside'])
            else:
                name:str = person['person']
                if name[:6] == 'person':
                    name = name[7:]
                elif name[:14] == 'device_tracker':
                    name = name[14:]
                person['outside'] = 'input_boolean.outside_' + name

            if not self.entity_exists(self.get_entity(person['outside'])):
                self.set_state(person['outside'],
                    state = 'off'
                )

            if not 'role' in person:
                person.update(
                    {'role' : 'adult'}
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
        self.delay_to_keep_lights_on = self.args.get('delay_to_keep_lights_on', 900)
        # TODO. Implement a delay to keep current mode when away before setting away


        # Set up notification if sensor is activated when no one is home
        self.alarmsensors = self.args.get('alarmsensors',[])
        self.sensor_handle = []
        self.alarm_active = False
        self.alarm_media = self.args.get('alarm_media', [])


        # Start vacuum robots when no adults is home
        self.vacuum = self.args.get('vacuum',[])
        self.prevent_vacuum = self.args.get('prevent_vacuum', [])


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
        if self.get_state(self.away_state) == 'off':
            if self.haLightModeText:
                self.current_MODE = self.get_state(self.haLightModeText)
            elif self.now_is_between('02:00:00', '05:00:00'):
                self.current_MODE = 'night'
            else:
                self.current_MODE = 'normal'
        else:
            self.current_MODE = 'away'
            self.start_alarm()


        # Morning routine
        self.morning_handler = []

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


        self.run_daily(self.waiting_for_morning, self.morning_runtime)

        if (
            self.now_is_between(self.morning_runtime, self.execute_morning)
            and self.current_MODE == 'night'
        ):
            self.run_in(self.waiting_for_morning, 1)

        self.run_daily(self.cancel_listening_for_morning, self.execute_morning)

        self.run_daily(self.good_day_now, self.execute_morning)

        if self.morning_to_day != None:
            try:
                test_runtime = self.parse_time(self.morning_to_day)
            except ValueError as ve:
                self.log(
                    f"Not able to convert morning_to_normal: {self.morning_to_day}. Error: {ve}",
                    level = 'INFO'    
                )
                self.morning_to_day = execute_morning

            self.run_daily(self.changeMorningToDay, self.morning_to_day)
        else:
            self.morning_to_day = execute_morning


        # Night routine
        self.night_handler = []

        self.turn_off_at_night = self.args.get('turn_off_at_night',[])

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


        self.run_daily(self.waiting_for_night, self.night_runtime)

        if (
            self.now_is_between(self.night_runtime, self.execute_night)
            and self.current_MODE != 'night'
        ):
            self.run_in(self.waiting_for_night, 1)
        self.run_daily(self.good_night_now, self.execute_night)


        # Listens for mode events
        self.listen_event(self.mode_event, "MODE_CHANGE")


    def mode_event(self, event_name, data, kwargs):
        """ Functions to change and manage modes for controlling lights and other
        """
        if self.haLightModeText:
            self.set_state(self.haLightModeText,
                state = data['mode'],
                namespace = self.HASS_namespace
            )

        # Morning
        string:str = self.current_MODE
        if string[:5] == 'night':
            if (
                data['mode'] == 'normal'
                or data['mode'] == 'morning'
            ):
                if self.now_is_between(self.morning_runtime, self.execute_morning):
                    self.cancel_listening_for_morning(0)
                self.unlockDoor()

        # Night
        if (
            data['mode'] == 'night'
            and self.now_is_between(self.night_runtime, self.execute_night)
        ):
            for item in self.turn_off_at_night:
                if self.get_state(item) == 'on':
                    self.turn_off(item)

            self.cancel_listening_for_night()

            for door in self.MQTT_door_lock:
                self.mqtt.mqtt_publish(
                    topic = str(door) + "/set/auto_relock",
                    payload = "true",
                    namespace = self.MQTT_namespace
                )
            self.run_in(self.lockDoor, 1)

        self.current_MODE = data['mode']

        # Away
        if data['mode'] == 'away':
            self.start_alarm()

            for door in self.MQTT_door_lock:
                self.mqtt.mqtt_publish(
                    topic = str(door) + "/set/auto_relock",
                    payload = "true",
                    namespace = self.MQTT_namespace
                )
            self.run_in(self.lockDoor, 7)


        # Morning and Night handling
    def cancel_listening_for_morning(self, kwargs):
        for handler in self.morning_handler:
            try:
                if self.cancel_listen_state(handler):
                    self.log(f"Cancel listen state {handler} ended", level = 'DEBUG')
                else:
                    self.log(f"Cancel listen state {handler} not stopped", level = 'DEBUG')
            except Exception as exc:
                self.log(f"Not possible to stop {handler}. Exception: {exc}")
        self.morning_handler = []


    def cancel_listening_for_night(self):
        for handler in self.night_handler:
            try:
                if self.cancel_listen_state(handler):
                    self.log(f"Cancel listen state {handler} ended", level = 'DEBUG')
                else:
                    self.log(f"Cancel listen state {handler} not stopped", level = 'DEBUG')
            except Exception as exc:
                self.log(f"Not possible to stop {handler}. Exception: {exc}")
        self.night_handler = []


    def waiting_for_morning(self, kwargs):
        if self.current_MODE != 'away':
            if self.keep_mode_when_outside != None:
                self.turn_off(self.keep_mode_when_outside)

            for sensor in self.morning_sensors:
                handler = self.listen_state(self.waking_up, sensor,
                    new = 'on'
                )
                self.morning_handler.append(handler)

    def waiting_for_night(self, kwargs):
        for sensor in self.night_sensors:
            handler = self.listen_state(self.going_to_bed, sensor,
                new = 'on'
            )
            self.night_handler.append(handler)


    def changeMorningToDay(self, kwargs):
        if self.current_MODE == 'morning':
            self.fire_event('MODE_CHANGE', mode = 'normal')
        self.cancel_listening_for_morning(0)


    def waking_up(self, entity, attribute, old, new, kwargs):
        if (
            self.now_is_between(self.morning_runtime, self.morning_to_day)
            and self.get_state(self.workday) == 'on'
        ):
            self.fire_event('MODE_CHANGE', mode = 'morning')
        else:
            self.fire_event('MODE_CHANGE', mode = 'normal')
        self.cancel_listening_for_morning(0)


    def going_to_bed(self, entity, attribute, old, new, kwargs):
        if self.current_MODE != 'away':
            self.fire_event("MODE_CHANGE", mode = 'night')
        self.cancel_listening_for_night()


    def good_day_now(self, kwargs):
        if (
            self.current_MODE == 'night'
            or self.current_MODE == 'morning'
        ):
            self.fire_event("MODE_CHANGE", mode = 'normal')
        self.cancel_listening_for_morning(0)


    def good_night_now(self, kwargs):
        if (
            self.current_MODE != 'away'
            and self.current_MODE != 'night'
        ):
            self.fire_event("MODE_CHANGE", mode = 'night')
        self.cancel_listening_for_night()


        # Door lock
    def lockDoor(self, kwargs):
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set",
                payload = "LOCK",
                namespace = self.MQTT_namespace
            )

        # Door unlock
    def unlockDoor(self):
        for door in self.MQTT_door_lock:
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set/auto_relock",
                payload = "false",
                namespace = self.MQTT_namespace
            )
            self.mqtt.mqtt_publish(
                topic = str(door) + "/set",
                payload = "UNLOCK",
                namespace = self.MQTT_namespace
            )

        # Doorlock listen
    def MQTT_doorlock_event(self, event_name, data, kwargs) -> None:
        try:
            data = json.loads(data['payload'])
        except Exception as e:
            self.log(f"Could not get payload from topic for {data}. Exception: {e}", level = 'INFO') # DEBUG
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
                        and self.current_MODE == 'away'
                        and self.housekeeperAtHome >= 1
                    ):
                        self.current_MODE = 'wash'
                        self.fire_event("MODE_CHANGE", mode = 'wash')
                        self.notify_app.send_notification(f"Turned on wash lights. Housekeeper unlocked door", "Housekeeper", self.notify_reciever)

                if 'lock_user' in person:
                    if data['last_unlock_user'] == person['lock_user']:
                        if not person['last_lock']:
                            self.log(f"User unlock: {person['person']}. State: {data['state']}. Outside switch: {self.get_state(person['outside'])}") ###
                            self.turn_off(person['outside'])
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


    def vacation_ending(self, entity, attribute, old, new, kwargs):
        for robot in self.vacuum:
            if (
                (self.get_state(robot) == 'docked'
                or self.get_state(robot) == 'charging')
                and self.get_state(robot, attribute='battery_level') > 40
            ):
                self.call_service('vacuum/start', entity_id = robot)


    def presenceChange(self, entity, attribute, old, new, kwargs):
        """ React to manual switches
        """
        if new == 'on':
            new = 'away'
            old = 'home'
            for person in self.presence:
                if person['outside'] == entity:
                    entity = person['person']
        elif new == 'off':
            for person in self.presence:
                if person['outside'] == entity:
                    entity = person['person']
                    self.log(f"Person is: {self.get_state(person['person'])}")
                    if self.get_state(person['person']) == 'home':
                        new = 'home'


        """ React to presence trackers
        """
        if new == 'home':
            stop_vacuum = False
            entity_tenant = False

            for person in self.presence:
                if person['person'] == entity:
                    if self.get_state(person['outside']) == 'off':
                        person.update(
                            {'state': new }
                        )
                        if person['role'] == 'adult':
                            stop_vacuum = True
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
                if self.current_MODE == 'away':
                    self.current_MODE = 'normal'
                    self.fire_event("MODE_CHANGE", mode = 'normal')
                    self.stop_alarm()


            elif self.housekeeperAtHome >= 1:
                self.notify_app.send_notification(f"Housekeeper {entity} entered", "Housekeeper", self.notify_reciever)
                if self.current_MODE == 'away':
                    self.stop_alarm()

            if stop_vacuum:
                for robot in self.vacuum:
                    if self.get_state(robot) == 'cleaning':
                        self.call_service('vacuum/return_to_base', entity_id = robot)

                if self.adultAtHome == 1:
                    self.unlockDoor()


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
                        and self.current_MODE == 'morning'
                    ):
                        self.current_MODE = 'normal'
                        self.fire_event("MODE_CHANGE", mode = 'normal') # TODO Check if anyone else is home.

                    break

            if self.get_state(self.keep_mode_when_outside) == 'on':
                return
                # Aborts setting away mode

            if self.adultAtHome == 0:
                for item in self.prevent_vacuum:
                    if self.get_state(item) == 'on':
                        start_vacuum = False
                if (
                    self.get_state(self.away_state) == 'off'
                    and self.now_is_between(self.morning_runtime, '18:00:00')
                    and start_vacuum
                ):
                    for robot in self.vacuum:
                        if (
                            (self.get_state(robot) == 'docked'
                            or self.get_state(robot) == 'charging')
                            and self.get_state(robot, attribute='battery_level') > 40
                        ):
                            self.call_service('vacuum/start', entity_id = robot)

                for door in self.MQTT_door_lock:
                    self.mqtt.mqtt_publish(
                        topic = str(door) + "/set/auto_relock",
                        payload = "true",
                        namespace = self.MQTT_namespace
                    )
                self.run_in(self.lockDoor, 7)

                if self.kidsAtHome == 0:
                    if self.housekeeperAtHome == 0:
                        self.start_alarm()

                        if self.current_MODE != 'away':
                            self.current_MODE = 'away'
                            self.fire_event("MODE_CHANGE", mode = 'away')


        #Function to handle notification when nobody is home
    def start_alarm(self):
        if not self.alarm_active:
            for sensor in self.alarmsensors:
                handle = self.listen_state(self.sensor_activated, sensor,
                    new = 'on'
                )
                self.sensor_handle.append(handle)
            self.alarm_active = True
            self.nofify_on_alarm = True


    def stop_alarm(self):
        for handle in self.sensor_handle:
            try:
                self.cancel_listen_state(handle)
            except:
                self.log(f"Not able to stop listen state for {handle}", level = 'DEBUG')
        self.sensor_handle = []
        self.alarm_active = False


    def sensor_activated(self, entity, attribute, old, new, kwargs):
        for robot in self.vacuum:
            if self.get_state(robot) == 'cleaning':
                return

        for person in self.presence:
            if person['role'] != 'tenant':
                if person['state'] == 'home':
                    return

        if self.nofify_on_alarm:
            self.notify_app.send_notification(f"{entity} triggered", "Alarm", self.notify_reciever)
            self.nofify_on_alarm = False
            self.run_in(self.reset_alarm_notification, 600)

        for play_media in self.alarm_media:
            self.call_service('media_player/select_source',
                entity_id = play_media['amp'],
                source = play_media['source']
            )
            self.call_service('media_player/volume_set',
                entity_id = play_media['amp'],
                volume_level = play_media['volume']
            )
            self.run_in(self.play_alarm_on_speakers, 8,
                play_media = play_media
            )


    def play_alarm_on_speakers(self, kwargs):
        play_media = kwargs['play_media']
        self.call_service('media_player/play_media',
            entity_id = play_media['player'],
            media_content_id = play_media['playlist'],
            media_content_type = 'music'
        )
        self.run_in(self.reset_soundlevel, 1,
            play_media = play_media
        )


    def reset_soundlevel(self,kwargs):
        play_media = kwargs['play_media']
        self.call_service('media_player/volume_set',
            entity_id = play_media['amp'],
            volume_level = play_media['normal_volume']
        )


    def reset_alarm_notification(self, kwargs):
        self.nofify_on_alarm = True


class Notify_Mobiles:

    ADapi = None
    def __init__(self,
        api):
        self.ADapi = api

    def send_notification(self,
        message = 'Message',
        message_title = 'title',
        message_recipient = ['all']
    ):
        if message_recipient == ['all']:
            self.ADapi.notify(f"{message}", title = f"{message_title}")
        else:
            for reciever in message_recipient:
                self.ADapi.notify(f"{message}", title = f"{message_title}", name = f"{reciever}")
