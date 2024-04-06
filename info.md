# ModeManagement by Pythm
An example of automating modes with Appdaemon to set suitable lights using the [Lightwand](https://github.com/Pythm/ad-Lightwand) Appdaemon app and automate other entities and appliances based on presence. Lightwand listens to the event "MODE_CHANGE" in Home Assistant to set different light modes with 'normal' mode as the default setting.

## Installation
1. Download the `ModeManagement` directory from inside the `apps` directory here to your [Appdaemon](https://appdaemon.readthedocs.io/en/latest/) `apps` directory.
2. Add the configuration to a .yaml or .toml file to enable the `ModeManagement` module.

### Dependencies:
This app uses Workday sensor to change light to Normal and not Morning on holidays: [Home Assistant Workday integration](https://www.home-assistant.io/integrations/workday/)


## App Usage and Configuration
> [!TIP]
> All sections and configurations are optional, so you can use only what is applicable. This app is written to meet my family's needs and is only meant as an example, but can act as a good baseline for automating presence and day/night shifts in your home. See definitions below on app behaviour and adjust accordingly.

Set a main vacation switch with `vacation` to prevent the app from changing modes while you are away.

Receive notifications to your devices with `notify_receiver`

You can receive notifications on your devices by listing them under `notify_receiver`. When certain conditions are met (like when sensors are triggered and no one is home), you will receive notifications on your phone or other devices.

### Default Times Set in App
This app's behavior is based on listening to sensors and some automated times if sensors are not triggered.
- The app starts listening for morning sensors at 06:50 and runs until 10:00. If no sensors are triggered during this time, you will have to manually set your mode.
- If the mode is `morning` at 08:50, the app will automatically change it to `normal`.
- The app listens for night sensors at 22:30 and continues until 02:00. If no sensors are triggered, it will fire the `night` mode as long as `vacation` is not set.

## Morning
To define Home Assistant (HA) binary sensors that trigger the morning mode, use the `morning_sensors` configuration. If you have a defined `workday` sensor, it will change the mode to normal if there is a holiday. It will also change to normal on Saturdays and Sundays.

## Night
To define HA binary sensors that trigger night mode, use the `night_sensors` configuration. This will change the mode to night and turn off entities defined with `turn_off_at_night`.

## Presence
Input trackers/persons with `person` and assign a `role` to each tracker, which can be 'adult', 'kid', 'housekeeper', or 'tenant'.

If no adults are home, `vacuum` cleaners will start. They will return to their dock if an adult returns home. If no adults or kids are home, the mode will be set to `away`.

If you define persons with a housekeeper role and only the housekeeper is present, the mode will be set to 'wash'. In Lightwand, the standard setting for 'wash' is 100% brightness.

Previously, I intended to prevent vacuum cleaners from starting when the tenant was home, but this feature is not currently implemented.

You can also start a playlist in addition to sending notifications to your phone if no one is home, vacuum cleaners are not running, and a sensor is triggered.

## Example App configuration

```yaml
modeManage:
  module: modeManagement
  class: ModeManagement
  workday: binary_sensor.workday_sensor # HA workday sensor: https://www.home-assistant.io/integrations/workday/
  vacation: input_boolean.vekk_reist # HA state for vacations for not setting morning/normal/night mode when away
  turn_off_at_night: # Items to turn off automatically at night
    - media_player.denon_avr_x3000
  morning_sensors: # Sensors to trigger morning mode or normal mode if not workday
    - binary_sensor.multisensor_home_security_motion_detection
  night_sensors: # Sensors to trigger night mode and turn off items
    - binary_sensor.fibaro_door_window_sensor_2_access_control_window_door_is_open_4 # Bedroom window...
  
  presence: # Tracking of who is home
    - person: person.myself
      role: adult
    - person: person.mywife
      role: adult
    - person: person.mytenant
      role: tenant
    - person: person.mykid
      role: kid
    - person: person.parents-in-law
      role: housekeeper

  vacuum: # Automatically start vacuum cleaners if no adults is home and stop when adults return home
    - vacuum.roomba
    - vacuum.roborock_s8
  
  alarmsensors: # Set up HA sensors if you want notification to phone if triggered, and no one is home
    - binary_sensor.multisensor_home_security_motion_detection
    - binary_sensor.motion_sensor_home_security_motion_detection

  notify_reciever:
    - mobile_app_your_iphone
  alarm_media: # Play a playlist if alarmsensors is triggered
    - amp: media_player.denon_avr_x3000 # Device to turn on
      source: Roon
      volume: 0.5
      normal_volume: 0.33
      player: media_player.gaming_krok # Device to start playing from
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
