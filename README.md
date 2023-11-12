# ad-ModeManagement

Use this as an example on how to automate modes to set suitable lighting using lightwand app. Lightwand uses mode_event "MODE_CHANGE" in Home Assistant to set different light modes with 'normal' mode as default setting. Also contains some notifications/media actions if sensors is triggered and no one is home

## Installation

Download the `ModeManagement` directory from inside the `apps` directory here to your local `apps` directory, then add the configuration to enable the `ModeManagement` module.

## App configuration

```yaml
modeManage:
  module: modeManagement
  class: ModeManagement
  workday: binary_sensor.workday_sensor # HA workday sensor: https://www.home-assistant.io/integrations/workday/
  away_state: input_boolean.vekk_reist # HA state for vacations for not setting morning/normal/night mode when away
  turn_off_at_night: # Items to turn off automatically at night
    - media_player.denon_avr_x3000
    - media_player.denon_avr_x3000_2
  morning_sensors: # Sensor to trigger morning mode or normal mode if not workday
    - binary_sensor.multisensor_home_security_motion_detection
  night_sensors: # Sensor to trigger night mode and turn off items
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
    - sensor: binary_sensor.multisensor_home_security_motion_detection
    - sensor: binary_sensor.motion_sensor_home_security_motion_detection

  notify_reciever:
    - reciever: mobile_app_your_iphone
  notify_title: 'Alarm'
  notify_message: 'Movement when nobody is home'
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
`presence`-`person` | False | string || tracker sensor
`presence`-`role` | False | string || Role at house. Can be adult, kid, tenant, housekeeper
`vacuum` | True | list || Vacuum cleaners
`alarmsensors` | True | list || HA sensors for notification and start media playing
`notify_reciever` | True | dictionary || Receivers for notifications
`notify_reciever`-`reciever` | True | string || Mobile app or other defined notify receiver
`notify_title` | True | string || Title for your notification
`notify_message` | True | string || Your notification text
`alarm_media` | True | dictionary || Play a playlist if alarmsensor is triggered
`alarm_media`-`amp` | True | string || Device to turn on
`alarm_media`-`source` | True | string || Switch to source
`alarm_media`-`volume` | True | float || Set alarm volume
`alarm_media`-`normal_volume` | float | string || Rest volume to this
`alarm_media`-`player` | True | string || Device to start playing from
`alarm_media`-`playlist` | True | string || Playlist to play
