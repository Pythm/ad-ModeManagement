# ModeManagement by Pythm
An example of automating modes with Appdaemon to set suitable lights using the [Lightwand](https://github.com/Pythm/ad-Lightwand) Appdaemon app and automate other entities and appliances based on presence. Lightwand listens to the event "MODE_CHANGE" in Home Assistant to set different light modes with 'normal' mode as the default setting.

## Installation
1. Download the `ModeManagement` directory from inside the `apps` directory here to your [Appdaemon](https://appdaemon.readthedocs.io/en/latest/) `apps` directory.
2. Add the configuration to a .yaml or .toml file to enable the `ModeManagement` module.

### Dependencies:
This app uses Workday sensor to change light to Normal and not Morning on weekends and on holidays: [Home Assistant Workday integration](https://www.home-assistant.io/integrations/workday/)


## App Usage and Configuration
> [!TIP]
> All sections and configurations are optional, so you can use only what is applicable. This app was written to meet my family's needs and is only meant as an example, but can act as a good baseline for automating presence and day/night shifts in your home. All times is now configurable so it could be a little bit easier to adapt. See definitions below on app behaviour and adjust accordingly.

Set a main vacation switch with `vacation` to prevent the app from changing modes while you are away for the night or longer.

Configure HA workday sensor with `workday`.

You can receive notifications on your devices by listing them under `notify_receiver`. When certain conditions are met, like when sensors are triggered and no one is home, you will receive notifications.

Use a Home Assistant input_text helper to display current Light Mode configured with `HALightModeText`.

```yaml
manageModes:
  module: modeManagement
  class: ModeManagement
  workday: binary_sensor.workday_sensor
  vacation: input_boolean.vacation
  HALightModeText: input_text.lightmode
  notify_reciever:
    - mobile_app_my_phone
```

## Set up Mode behaviour
This app's behavior is based on listening to sensors and some automated times if sensors are not triggered.
Modes will not change with vacation switch on.

### Morning
The app starts listening for morning sensors at time configured with `morning_start_listen_time` and runs until `execute_morning_at`.

To define Home Assistant sensors that trigger the morning mode, input them as a list under `morning_sensors` in configuration.

You have the option to define a time the morning is changed to normal mode with `morning_to_normal`. This defaults to the time provided with `execute_morning_at`.

If your mode is still night or morning at `execute_morning_at`, the mode will be set to normal.

You have the option to turn on entities that are off with `turn_on_in_the_morning`. This only applies to entities with state on or off.

```yaml
  morning_sensors:
    - binary_sensor.motion_detection
    - binary_sensor.presence_sensor
  morning_start_listen_time: '06:00:00'
  morning_to_normal: '09:00:00'
  execute_morning_at: '10:00:00'

  turn_on_in_the_morning:
    - switch.coffee_machine
```

### Night
Night is basically a reverse of morning. Define your sensors with `night_sensors` in configuration. This will change the mode to night and turn off entities defined with `turn_off_at_night`. Turn off at night is entities with state on or off.

The app starts listening at the sensors at `night_start_listen_time` and stops listening and changes mode to night at time configured with `execute_night_at`.

```yaml
  night_sensors:
    - binary_sensor.window_door_is_open
  night_start_listen_time: '22:00:00'
  execute_night_at: '02:00:00'

  turn_off_at_night:
    - media_player.tv
```

## MQTT Door lock
I have a Nimly door lock that I set to auto lock, when no adults are home and during nighttime.
> [!NOTE]
> The Nimly MQTT module seems buggy / not reporting correct user in the MQTT message. Use at own risk

```yaml
  MQTT_door_lock:
    - zigbee2mqtt/NimlyDoor
```

## Presence
Trackers/persons are configured with `person` and assign a `role` to each tracker, which can be 'adult' (default), 'kid' or 'housekeeper'.
Each person can have an `outside` HA helper to manually set person away. This is useful when you are in close proximity and want the doors to auto lock.

If no adults or kids are home, the mode will be set to `away`.

If you define persons with a housekeeper role and only the housekeeper is present, the mode will be set to 'wash'. In Lightwand, the standard setting for 'wash' is 100% brightness.

If you have a nimly door lock you can also spesify the lock ID for each person with `lock_user`.
The unlock with id is programmed to set wash mode if person unlocking is defined as a "housekeeper" It is also programmed to reset the "outside" switch for person unlocking.

```yaml
  presence:
    - person: person.me
      outside: input_boolean.outside_me
      role: adult
      lock_user: 0
```

In additon to the outside switch pr person you can configure one switch that prevents the app from setting away with `keep_mode_when_outside`. This is reset at the time defined with `morning_start_listen_time`.

### Vacuum cleaners
If no adults are home, `vacuum` cleaners will start. They will return to their dock if an adult returns home. You can prevent them to start with sensors in the list `prevent_vacuum`.

```yaml
  vacuum:
    - vacuum.roomba
    - vacuum.roborock

  prevent_vacuum:
    - media_player.tv
```

### Alarm
Set up sensors that will send you a notification if triggered. It only fires if no one is home and the vaccum cleaners is not running.

```yaml
  alarmsensors:
    - binary_sensor.entrance_motion_motion_detection
    - cover.garage_door
    - binary_sensor.door_window_door_is_open
```

You can start a playlist in addition to sending notifications when a sensor is triggered.

```yaml
  alarm_media: # Play a playlist if alarmsensors is triggered
    - amp: media_player.denon_avr_x3000 # Device to turn on
      source: Roon
      volume: 0.5
      normal_volume: 0.33
      player: media_player.yourplayer # Device to start playing from
      playlist: 'Library/Artists/Alarm/Alarm'
```

### Namespace
If you have defined a namespace for MQTT other than default you need to define your namespace with `MQTT_namespace`. Same for HASS you need to define your namespace with `HASS_namespace`.

## Putting it all togehter
Easisest to start off with is to copy this example and update with your sensors and lights and build from that.


```yaml
manageModes:
  module: modeManagement
  class: ModeManagement
  workday: binary_sensor.workday_sensor
  vacation: input_boolean.vacation
  HALightModeText: input_text.lightmode
  notify_reciever:
    - mobile_app_my_phone

  morning_sensors:
    - binary_sensor.motion_detection
    - binary_sensor.presence_sensor
  morning_start_listen_time: '06:00:00'
  morning_to_normal: '09:00:00'
  execute_morning_at: '10:00:00'

  night_sensors:
    - binary_sensor.window_door_is_open
  night_start_listen_time: '22:00:00'
  execute_night_at: '02:00:00'

  turn_off_at_night:
    - media_player.tv

  MQTT_door_lock:
    - zigbee2mqtt/NimlyDoor

  presence:
    - person: person.me
      outside: input_boolean.outside_me
      role: adult
      lock_user: 0

  vacuum:
    - vacuum.roomba
    - vacuum.roborock

  prevent_vacuum:
    - media_player.tv

  alarmsensors:
    - binary_sensor.entrance_motion_motion_detection
    - cover.garage_door
    - binary_sensor.door_window_door_is_open

  alarm_media: # Play a playlist if alarmsensors is triggered
    - amp: media_player.denon_avr_x3000 # Device to turn on
      source: Roon
      volume: 0.5
      normal_volume: 0.33
      player: media_player.yourplayer # Device to start playing from
      playlist: 'Library/Artists/Alarm/Alarm'
```

key | optional | type | default | description
-- | -- | -- | -- | --
`module` | False | string | | The module name of the app.
`class` | False | string | | The name of the Class.
`workday` | True | string | `binary_sensor.workday_sensor`| HA workday sensor: https://www.home-assistant.io/integrations/workday/
`vacation` | True | string | `input_boolean.vacation`|  HA input_boolean for vacations to not setting morning/normal/night mode when away
`turn_off_at_night` | True | list || Items to turn off automatically at night
`morning_sensors` | True | list || Sensors to trigger morning mode or normal mode if not workday
`night_sensors` | True | list || Sensors to trigger night mode and turn off items
`presence` | False | dictionary || Tracking of who is home
`vacuum` | True | list || Vacuum cleaners
`alarmsensors` | True | list || HA sensors for notification and start media playing
`notify_reciever` | True | list || Receivers for notifications
`alarm_media` | True | dictionary || Play a playlist if alarmsensor is triggered
