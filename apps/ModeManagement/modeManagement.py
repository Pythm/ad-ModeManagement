""" Mode Event Management

    @Pythm / https://github.com/Pythm
"""
__version__ = "0.1.2"

import appdaemon.plugins.hass.hassapi as hass
import datetime


class ModeManagement(hass.Hass):

    def initialize(self):

        # Set up notification
        self.notify_app = Notify_Mobiles(self)
        self.notify_reciever = self.args.get('notify_reciever', [])
        self.nofify_on_alarm = True

        # Holliday switch from Home Assistant
        if 'away_state' in self.args: # Old name for entity
            self.away_state = self.args['away_state']
        elif 'vacation' in self.args:
            self.away_state = self.args['vacation']
        else:
            self.away_state = 'input_boolean.vacation'
            if not self.entity_exists(self.get_entity(self.away_state)):
                self.set_state(self.away_state, state = 'off')
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
                self.set_state(self.workday, state = 'on')
                self.log(
                    "'workday' binary_sensor not defined in app configuration. Will fire morning mode every day. "
                    "https://www.home-assistant.io/integrations/workday/",
                    level = 'INFO'
                )

        self.morning_handler = []
        self.night_handler = []

        self.turn_off_at_night = self.args.get('turn_off_at_night',[])

        self.morning_sensors = self.args.get('morning_sensors', [])
        self.run_daily(self.waiting_for_morning, datetime.time(6, 50, 0) )
        if self.now_is_between('06:50:00', '10:00:00'):
            self.run_in(self.waiting_for_morning, 1 )
        self.run_daily(self.cancel_listening_for_morning, datetime.time(10, 0, 1))

        self.run_daily(self.changeMorningToDay, datetime.time(8, 50, 0))

        self.night_sensors = self.args.get('night_sensors', [])
        self.run_daily(self.waiting_for_night, datetime.time(22, 30, 0) )
        if self.now_is_between('22:30:00', '02:00:00'):
            self.run_in(self.waiting_for_night, 1 )
        self.run_daily(self.good_night_now, datetime.time(2, 0, 0))


        # Presence detection:
        self.adultAtHome = 0
        self.kidsAtHome = 0
        self.tenantAtHome = 0
        self.housekeeperAtHome = 0
                
        self.presence = self.args['presence']
        for person in self.presence:
            self.listen_state(self.presenceChange, person['person'])
            person.update(
                {'state' : self.get_state(person['person'])}
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

        # Set up notification if sensor is activated when no one is home
        self.alarmsensors = self.args.get('alarmsensors',[])
        self.sensor_handle = []
        self.alarm_active = False
        self.alarm_media = self.args.get('alarm_media', [])

        # Start vacuum robots when no adults is home
        self.vacuum = self.args.get('vacuum',[])

        # Update current mode to a Home Assistant input_text
        self.haLightModeText = self.args.get('HALightModeText', None) 

        # Getting right data to start with
        if self.get_state(self.away_state) == 'off':
            if self.haLightModeText:
                self.current_MODE = self.get_state(self.haLightModeText)
            elif self.now_is_between('02:00:00', '06:50:00'):
                self.current_MODE = 'night'
            else:
                self.current_MODE = 'normal'
        else:
            self.current_MODE = 'away'
            self.start_alarm()

        self.listen_event(self.mode_event, "MODE_CHANGE")


    def mode_event(self, event_name, data, kwargs):
        """ Functions to change and manage modes for controlling lights
        """
        if self.haLightModeText:
            self.set_state(self.haLightModeText, state = data['mode'])
            
        if self.current_MODE != 'away':
            if (
                data['mode'] == 'normal'
                or data['mode'] == 'morning'
            ):
                if self.now_is_between('06:50:00', '10:00:00'):
                    self.cancel_listening_for_morning(0)
            elif (
                data['mode'] == 'night'
                and self.now_is_between('22:30:00', '02:10:00')
            ):
                for item in self.turn_off_at_night:
                    if self.get_state(item) == 'on':
                        self.turn_off(item)

                self.cancel_listening_for_night()

        self.current_MODE = data['mode']
        if data['mode'] == 'away':
            self.start_alarm()
            # TODO: Lock door?


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
            for sensor in self.morning_sensors:
                handler = self.listen_state(self.waking_up, sensor,
                    new = 'on'
                )
                self.morning_handler.append(handler)


    def changeMorningToDay(self, kwargs):
        if self.current_MODE == 'morning':
            self.fire_event('MODE_CHANGE', mode = 'normal')


    def waiting_for_night(self, kwargs):
        for sensor in self.night_sensors:
            handler = self.listen_state(self.going_to_bed, sensor,
                new = 'on'
            )
            self.night_handler.append(handler)


    def waking_up(self, entity, attribute, old, new, kwargs):
        if (
            self.now_is_between('06:50:00', '08:30:00')
            and self.get_state(self.workday) == 'on'
        ):
            self.fire_event('MODE_CHANGE', mode = 'morning')
        else:
            self.fire_event('MODE_CHANGE', mode = 'normal')


    def going_to_bed(self, entity, attribute, old, new, kwargs):
        if self.current_MODE != 'away':
            self.fire_event("MODE_CHANGE", mode = 'night')


    def good_night_now(self, kwargs):
        if self.current_MODE != 'away':
            self.fire_event("MODE_CHANGE", mode = 'night')
        else:
            self.cancel_listening_for_night()


    def presenceChange(self, entity, attribute, old, new, kwargs):
        """ React to presence trackers
        """
        if new == 'home':
            stop_vacuum = False
            entity_tenant = False

            for person in self.presence:
                if person['person'] == entity:
                    person.update(
                        {'state': new }
                    )
                    if person['role'] == 'adult':
                        self.adultAtHome += 1
                        stop_vacuum = True
                    elif person['role'] == 'kid':
                        self.kidsAtHome += 1
                    elif person['role'] == 'tenant':
                        self.tenantAtHome += 1
                        entity_tenant = True
                        #stop_vacuum = True
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
                    # TODO: Unlock door...

            elif self.housekeeperAtHome >= 1:
                if self.current_MODE == 'away':
                    self.current_MODE = 'wash'
                    self.fire_event("MODE_CHANGE", mode = 'wash')
                    self.stop_alarm()

            if stop_vacuum:
                for robot in self.vacuum:
                    if self.get_state(robot) == 'cleaning':
                        self.call_service('vacuum/return_to_base', entity_id = robot)

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
                        self.fire_event("MODE_CHANGE", mode = 'normal')

                    break

            if self.adultAtHome == 0:
                if (
                    self.get_state(self.away_state) == 'off'
                    and self.now_is_between('07:30:00', '18:00:00')
                    and start_vacuum
                ):
                    for robot in self.vacuum:
                        if (
                            (self.get_state(robot) == 'docked'
                            or self.get_state(robot) == 'charging')
                            and self.get_state(robot, attribute='battery_level') > 40
                        ):
                            self.call_service('vacuum/start', entity_id = robot)

                if self.kidsAtHome == 0:
                    if self.housekeeperAtHome == 0:
                        self.start_alarm()
                        # TODO: Lock door...

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
            self.notify_app.send_notification(f"{entity} triggered","Alarm", self.notify_reciever)
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
            self.notify(f"{message}", title = f"{message_title}")
        else:
            for reciever in message_recipient:
                self.notify(f"{message}", title = f"{message_title}", name = f"{reciever}")