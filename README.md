# ModeManagement by Pythm
an example on how to automate modes with Appdaemon to set suitable lights using [Lightwand](https://github.com/Pythm/ad-Lightwand) Appdaemon app. Lightwand uses mode_event "MODE_CHANGE" in Home Assistant to set different light modes with 'normal' mode as default setting.
Also contains some notifications/media actions if sensors is triggered and no one is home.
Will start vacuum robots if no adults are home.

## Installation

Download the `ModeManagement` directory from inside the `apps` directory here to your [Appdaemon](https://appdaemon.readthedocs.io/en/latest/) `apps` directory, then add the configuration to enable the `ModeManagement` module.

## Example App configuration

```yaml
modeManage:
  module: modeManagement
  class: ModeManagement
  workday: binary_sensor.workday_sensor # HA workday sensor: https://www.home-assistant.io/integrations/workday/
  away_state: input_boolean.vekk_reist # HA state for vacations for not setting morning/normal/night mode when away
  turn_off_at_night: # Items to turn off automatically at night
    - media_player.denon_avr_x3000
    - media_player.denon_avr_x3000_2
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
`away_state` | True | string | `input_boolean.vacation`|  HA input_boolean for vacations to not setting morning/normal/night mode when away
`turn_off_at_night` | True | list || Items to turn off automatically at night
`morning_sensors` | True | list || Sensors to trigger morning mode or normal mode if not workday
`night_sensors` | True | list || Sensors to trigger night mode and turn off items
`presence` | False | dictionary || Tracking of who is home
`vacuum` | True | list || Vacuum cleaners
`alarmsensors` | True | list || HA sensors for notification and start media playing
`notify_reciever` | True | list || Receivers for notifications
`alarm_media` | True | dictionary || Play a playlist if alarmsensor is triggered
