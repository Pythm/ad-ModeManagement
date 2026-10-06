
# ModeManagement by Pythm  
**An example of automating modes with AppDaemon to set suitable lights using the [Lightwand](https://github.com/Pythm/ad-Lightwand) AppDaemon app and automate other entities and appliances based on presence.**

---

## 🔍 Features
- **Morning/Night Mode Triggers**: Uses presence, time, and sensor triggers to automatically switch between `automagical` (the normal mode), `morning`, `night` and `away`.
- **Family Light Mode**: Optionally use your own light mode instead of `automagical` while extended family is home without any adult (see [Family light mode](#family-light-mode)).
- **Vacation Mode**: While your `vacation` switch is on, vacuum cleaners are not started (so a robot is not left running or stuck with a draining battery). When the switch is turned off the vacuums start once, if nobody is home and the time is inside the vacuum start window, so the house is clean when you arrive. The switch does not block or change modes by itself. If AppDaemon starts with it on, the mode is `away`, and the morning and night routines do nothing while the mode is `away`.
- **Door Lock Integration**: Supports MQTT-based door locks (e.g., Nimly) for auto-locking when no adults or family members are home or during nighttime.
- **Vacuum Cleaner Automation**: Triggers vacuum cleaners when no adults or family members are home and stops them if one of them returns. Can run inside ModeManagement or as the separate `VacuumManager` app.
- **Alarm Notifications**: Sends alerts via `notify_receiver` when sensors are triggered (e.g., open windows, doors, motion) and no one is home. Optionally with a picture from a camera.
- **Customizable Schedules**: All times and thresholds are configurable for flexibility.

---

## 🚨 Breaking Changes
### **0.3.1**
Nothing to do if you only use the defaults, except the door lock behaviour below. Your YAML keeps working.

- **Door unlock is now opt-in**: Before, the door was unlocked when an adult or family member arrived and when morning started after the night. Now the door stays locked unless you set `unlock_door_when_home: True` (see [MQTT Door locks](#mqtt-door-locks)). Set it to keep the old behaviour. Locking when away or at night is unchanged.
- **Presence**: A person or tracker changing to `unavailable` or `unknown` (for example when Home Assistant restarts) is ignored instead of being treated as leaving home. A person who really leaves still goes from `home` to another state.
- **Alarm sensors**: Doors and covers (`open`, `opening`) now trigger the same way as `on`. A sensor going from `unavailable`/`unknown` to `on` does not trigger. `alarm_media` now has its own 10 minute pause. Before, the playlist started on every sensor change. New: `play_media: False` on a sensor gives notification only.
- **Alarm pause after a door unlock**: A door unlock while nobody is home still pauses alarm notifications for 20 seconds, but it no longer shortens a longer pause that is already running (for example the 10 minutes after a notification).
- **Vacuum**: `daily_routine` was ignored in earlier versions and the full program was started instead. It is now used when set. Vacuums are only started when the vacuum is `docked` or `charging`, as before. When the vacation switch is turned off, vacuums only start if nobody is home and the time is inside the vacuum start window. Outside the window they are not started, and this is logged at INFO level.
- **Vacuum start window**: The start window is `morning_start_listen_time` to `18:00:00` as before. It can now be set with `vacuum_earliest_start` and `vacuum_latest_start`.
- **Housekeeper**: When the housekeeper leaves while the mode is `wash` and someone from the house is home, the mode goes back to normal. If nobody is home, the house goes back to `away` as before.
- **Startup**: The app no longer stops if `HALightModeText` is `unknown`, `unavailable` or still shows `fire` after a restart. It then uses `night` between `execute_night_at` and `morning_start_listen_time`, otherwise the normal mode (`automagical`, or the `family` mode when it applies).
- **Python packages**: `holidays` is only imported when `country_code` is set.
- **Translations**: If you translate or rename modes, set the language once with the new `ModeTranslation` app that comes with Lightwand 2.3.0 and add `dependencies: mode_translation` to this app, so the mode names are loaded before this app starts. Without it the result depends on the order AppDaemon starts your apps in. English users need no change. See [Lightwand: Translating or Changing Modes](https://github.com/Pythm/ad-Lightwand#-translating-or-changing-modes).
- **Fix**: The mode event fired when someone arrives home from `away` now uses `HASS_namespace` like all other events from this app.
- **Restored**: `anyone_home()`, used by other apps, is available again (see [Used by other apps](#-used-by-other-apps)).
- **New, optional: `family` light mode**: Set `family: <light mode name>` to use your own light mode while a family member is home and no adult is. See [Family light mode](#family-light-mode).
  - **Upgrading**: Nothing to do. Without `family` the app behaves as before.

### **0.2.1**
- **Morning routine**: Defining `country_code` is now optional and app will not try to find location based on Appdaemon config. Lack of doing so will fire **morning** mode every day.

### **0.2.0**
- **Lightwand translations**: App now uses Lightwand translations singleton. This requires Lightwand version 2.0.0 or later installed in your AppDaemon (the mode names are read from Lightwand's `translations_lightmodes` module). Check out https://github.com/Pythm/ad-Lightwand?tab=readme-ov-file#-translating-or-changing-modes on how to use your own mode names.

### **0.1.13**
- **Spelling Correction**: Changed `notify_reciever` → `notify_receiver`.

### **0.1.12**
- **MQTT Namespace Update**: Default MQTT namespace changed to `'mqtt'` to align with AppDaemon defaults.

---

## 📦 Dependencies

Install the required packages using `requirements.txt`:
  - holidays (only needed if you set `country_code`)

The app also uses `pydantic`. It is not listed in `requirements.txt`, because it is expected to come with your AppDaemon installation. If AppDaemon logs `No module named 'pydantic'`, install it the same way as `holidays`.

Other apps:
  - [Lightwand](https://github.com/Pythm/ad-Lightwand) 2.3.0 or later is required (mode names). Install it with HACS or by cloning it.
  - [Pythm_AppdaemonApps](https://github.com/Pythm/Pythm_AppdaemonApps) is optional, only for `snapshot_directory`. Clone it into your `apps` folder yourself.

This repository is **not** published to HACS, so it is installed by cloning. Neither `git clone` nor `requirements.txt` installs other repositories automatically, so each repository above has to be installed on its own.

- If you run Appdaemon as a Addon in HA you'll have to specify the python packages manually in configuration in the Addon and restart Appdaemon.

- If your Appdaemon install method does not handle requirements automatically:

```bash
pip install -r requirements.txt
```

---

## 🛠️ Installation
1. **Clone the repository** into your AppDaemon `apps` directory:  
   ```bash
   git clone https://github.com/Pythm/ad-ModeManagement.git /path/to/appdaemon/apps/ModeManagement
   # update later with:
   cd /path/to/appdaemon/apps/ModeManagement && git pull
   ```
2. **Configure the app** in your AppDaemon `.yaml` or `.toml` file:

   ```yaml
   manageModes:
     module: modeManagement
     class: ModeManagement
     country_code: 'NO'
     vacation: input_boolean.vacation
     notify_receiver:
       - mobile_app_my_phone
   ```  

> 💡 **Tip**: Default values are used if parameters are omitted in the configuration.

---

## 📌 Tips & Best Practices  
- **Vacation Mode**: While `vacation` is on, vacuums are not started. When it is turned off and nobody is home, the vacuums start once if the time is between `vacuum_earliest_start` and `vacuum_latest_start`. Outside that window they are not started. If AppDaemon starts with it on, the mode is `away`.
- **Holiday Detection**: Define `country_code` to fetch holidays. This will set normal automation instead of morning mode during holidays and weekends. If not defined, app will call morning mode every day.
- **Light‑Mode Display** – Use a Home Assistant input_text helper configured with (`HALightModeText`) to show the current Light mode. It is also used at startup to restore the last mode, and it shows `fire` during a fire alarm.

> [!NOTE]  
> If a light in Lightwand does not contain morning mode, the automagical automation is automagically controlling your light.

---

## 📚 Configurations

### Using different roles for persons
| Role | Modes and alarm | Door‑Lock / Vacuum Behaviour |
|------|-----------------|------------------------------|
| **adult** | Primary role. Keeps the house out of `away` and silences alarm notifications. Arriving while the mode is `away` sets the normal mode. | When no adult or family member is home, the door is locked with auto relock and the vacuums start (also when kids are home). Arriving stops the vacuums. The door unlocks when one arrives only with `unlock_door_when_home`. |
| **family** | Extended family, for example visiting grandparents. Same as adult. With the optional `family` setting they can have their own light mode while no adult is home (see [Family light mode](#family-light-mode)). | Same as adult. |
| **kid** | Keeps the house out of `away` and silences alarm notifications. Arriving while the mode is `away` sets the normal mode. | Does not unlock the door or stop vacuums. When only kids are home the door is locked and the vacuums start. At night in night mode the door is locked, but the vacuums are not started. |
| **housekeeper** | Arriving while nobody else is home only notifies you and stops alarm notifications. The mode stays `away`. Unlocking the MQTT door with their `lock_user` while the mode is `away` sets `wash`. While at home they silence alarm notifications, but do not count as someone home for modes, door and vacuums. | When the housekeeper leaves and nobody is home, the house goes back to `away` (door locked, vacuums start). If someone from the house is home and the mode is `wash`, it goes back to normal (`automagical`, or the `family` mode when it applies). |
| **tenant** | Ignored for modes. A tenant at home does not silence alarm notifications. | Ignored. |

Vacuums only start inside the vacuum start window and not while `vacation` is on (see [Vacuum Cleaners](#vacuum-cleaners)).

### Family light mode
Set `family` to a light mode name to use it instead of `automagical` while a person with the `family` role is home and no `adult` is (kids may be home).

```yaml
  family: grandparents   # optional, a light mode that exists in Lightwand
  presence:
    - person: person.me
      role: adult
    - person: person.grandma
      role: family
```

- It only replaces `automagical`. `morning`, `night`, `away` and `wash` behave as before. While the family mode applies, the app uses it wherever it would otherwise go back to `automagical` (after morning, when coming home from `away`, after `wash`).
- An adult leaves while family is home and the mode is `automagical`: the family mode is set.
- A family member arrives while no adult is home and the mode is `automagical`: the family mode is set.
- An adult arrives, or the last family member leaves, while the mode is the family mode: `automagical` is set.
- With `keep_mode_when_outside` on, an adult marked as outside still makes the house switch to the family mode.
- A `reset` event stores `automagical`. The family mode comes back at the next presence change.
- The mode name must exist in Lightwand. This app only fires `MODE_CHANGE` with it. The name is not checked against the house modes, so do not set it to `away`, `night`, `morning` or `wash`.

### MQTT Door locks


The door is locked (auto relock is enabled, and the lock command follows about 10 seconds later) when:
- the last adult or family member leaves, also if kids are still home,
- the mode changes to `away`,
- the mode changes to `night` between `night_start_listen_time` and `execute_night_at`.

The door is **not** unlocked automatically. To unlock it when an adult or family member arrives home (not in away or night mode) and when morning starts after the night, set `unlock_door_when_home: True`. Auto relock is then disabled until the next lock.

When the door is unlocked by a person with a `lock_user`, you get a notification. An unlock while nobody from the house is home pauses alarm notifications and alarm media for 20 seconds, so you have time to come in. A longer pause that is already running is kept. Unlocks the lock reports with `last_unlock_source: self` are ignored.

```yaml
  MQTT_door_lock:
    - zigbee2mqtt/NimlyDoor
  unlock_door_when_home: True   # optional, default False
```

> ⚠️ **Safety note** – Think about whether it is safe to leave your door unlocked when you are home before you enable `unlock_door_when_home`.

---

## Vacuum Cleaners

You can automatically start and stop a vacuum cleaner when a person with the *adult* or *family* role leaves or returns home.

### What it can do

| Feature | Description |
|---------|-------------|
| **Start when away** | Starts docked (`docked` or `charging`) vacuums when the last adult/family member has left, after `delay_before_setting_away`, between `vacuum_earliest_start` (default `morning_start_listen_time`) and `vacuum_latest_start` (default `18:00:00`). Not while `vacation` is on, not while `keep_mode_when_outside` is on, and not when kids are home at night in night mode. |
| **Start after vacation** | When the `vacation` switch is turned off and nobody is home, the vacuums start once if the time is inside the start window. Outside the window they are not started (logged at INFO level). |
| **Return to base** | When an adult or family member arrives, every vacuum that is `cleaning` is sent back to its base. Exception: a vacuum the app found already cleaning when it tried to start it is treated as started by you and left alone until it docks. |
| **Battery** | Vacuums start only when the battery is above `min_battery` (default 40 %). The `battery` sensor is read first, then the `battery_level` attribute of the vacuum. If no level can be read, a warning is logged once and the vacuum is started anyway. |
| **Custom start routine** | `daily_routine` takes a `button`, `input_button`, `script` or switch-like entity that starts the cleaning job. Without it `vacuum.start` is used. |

### Example configuration

```yaml
vacuum:
  - vacuum: vacuum.roborock_s8
    battery: sensor.roborock_s8_battery   # optional – only if the vacuum entity lacks a battery attribute
    daily_routine: button.daily_clean     # optional – the entity that starts the cleaning job
    min_battery: 50                       # optional – overrides vacuum_min_battery for this vacuum
    prevent_vacuum:                       # <-- only this vacuum has a custom prevent list
      - switch.vacuum3_pause

# optional: global prevent_vacuum list
prevent_vacuum:
  - media_player.tv
```

#### How `prevent_vacuum` works

- The list under `prevent_vacuum` contains entities that act as *gatekeepers*.
- If any of those entities reports a state of **`on`**, the automation will **skip** starting the vacuum. Only the exact state `on` counts, so for example a media player that is `playing` does not stop the vacuum.
- A `prevent_vacuum` list on a vacuum **replaces** the global list for that vacuum. The two lists are not merged.

> **TIP** – Use any entity that can report `on`/`off` (switches, media players, sensors, etc.) to control the start condition.

### Separate vacuum app

The vacuum logic lives in `vacuum_manager.py`. Instead of the `vacuum:` setting above, you can run it as its own app. ModeManagement then only tells it when to start and stop with the event `VACUUM_CONTROL`, and your own Home Assistant automations can fire the same event (`event: VACUUM_CONTROL`, `event_data: {action: start}` or `{action: stop}`).

```yaml
vacuums:
  module: vacuum_manager
  class: VacuumManager
  HASS_namespace: default       # optional
  vacuum_event: VACUUM_CONTROL  # optional
  min_battery: 40               # optional
  vacuum:
    - vacuum: vacuum.roborock_s8
      battery: sensor.roborock_s8_battery
  prevent_vacuum:
    - media_player.tv

manageModes:
  module: modeManagement
  class: ModeManagement
  vacuum_event: VACUUM_CONTROL  # fires the event. Do not use together with vacuum:
```

Use either `vacuum:` or `vacuum_event` in ModeManagement, not both. With both set and a `VacuumManager` app running for the same vacuums, they get every start and stop twice.

---

### 📢 Notifications  
- Configure `notify_receiver` with a list of devices (e.g., `mobile_app_your_phone`).  
- You can use a custom notification app instead with `notify_app` that contains the `send_notification` function. It is called as `send_notification(message=..., message_title=..., message_recipient=<notify_receiver>, also_if_not_home=True, data=...)`. If the app is not found, a warning is logged and Home Assistant `notify` is used.

Messages sent:

| Title | Message | When |
|-------|---------|------|
| `Sensor triggered` | the sensor entity id | A sensor in `alarmsensors` is triggered while nobody is home. |
| `Door unlock` | `<person entity id> unlocked the door` | The MQTT door is unlocked by a person with a matching `lock_user`. |
| `Housekeeping` | `Housekeeper <person entity id> entered` | A housekeeper arrives while nobody from the house is home. |

### 📷 Picture with the alarm notification
When a sensor in `alarmsensors` is triggered while no one is home, the notification can include a camera picture. Set a camera per sensor, or one for all with `alarm_camera`:

```yaml
  alarm_camera: camera.entrance          # optional, used by sensors without own camera
  alarmsensors:
    - binary_sensor.entrance_motion      # uses alarm_camera
    - sensor: cover.garage_door
      camera: camera.garage              # own camera
```

- Default: the picture is fetched by the Companion app from the camera entity (`image: /api/camera_proxy/camera.x` for Android and `entity_id` with the `camera` notification category for iOS). No files are saved and nothing is publicly available. See [Companion app attachments](https://companion.home-assistant.io/docs/notifications/notification-attachments/). Check how it looks on your own phones, as it depends on the camera integration.
- Optional: set `snapshot_directory` to save snapshots with `utils_apps` from [Pythm_AppdaemonApps](https://github.com/Pythm/Pythm_AppdaemonApps) (add that repository to your AppDaemon `apps` folder). The directory must be inside Home Assistant `www`, be listed in `allowlist_external_dirs` and be visible for AppDaemon. Files in `www` are available at `/local/` **without authentication**. Without `utils_apps` installed, the app logs a warning and uses the camera entity.
- Only one notification is sent each 10 minutes. A door unlock while nobody is home pauses notifications for 20 seconds, but never shortens a longer pause (see [MQTT Door locks](#mqtt-door-locks)).
- "Nobody is home" here means nobody except tenants: a housekeeper at home also silences the alarm.

### 🔊 Alarm media only on some sensors
`alarm_media` plays when a sensor is triggered. If you only want a notification from some sensors, for example cameras outside the house, set `play_media: False` on those sensors. The notification is still sent. Media plays at most once each 10 minutes, counted separately from the notification, so an outdoor sensor does not block the alarm from an indoor sensor.

```yaml
  alarmsensors:
    - sensor: binary_sensor.garden_person_detected
      camera: camera.garden
      play_media: False                  # notification only
    - binary_sensor.door_window_door_is_open   # notification and alarm_media
```

---

## 📡 Events
- Fires `MODE_CHANGE` with `mode: <name>` in `HASS_namespace`. The event name and the mode names come from Lightwand's translations (English: `automagical`, `morning`, `night`, `away`, `wash`).
- Listens to the same event, also from Lightwand or your own automations, to keep track of the current mode:
  - `away` starts the alarm and locks the door.
  - `night` between `night_start_listen_time` and `execute_night_at` turns off `turn_off_at_night` and locks the door.
  - `automagical`, `morning` or the `family` mode while in night mode, between `morning_start_listen_time` and `execute_morning_at`, turns on `turn_on_in_the_morning` (and unlocks the door with `unlock_door_when_home`).
  - `reset` stores `automagical`. `false-alarm` fires the mode from before the fire again. `fire` only shows `fire` in `HALightModeText`.
  - Room modes like `off_kitchen` do not change the stored mode.
- With `vacuum_event` set, fires that event with `action: start` or `action: stop`.

### 🔗 Used by other apps
`anyone_home()` is a public method. It returns `True` if any person in `presence` is home and not marked as outside, whatever the role (also tenants and housekeepers). FireAlarm from [Pythm_AppdaemonApps](https://github.com/Pythm/Pythm_AppdaemonApps) uses it.

---

## 📚 Key Definitions  
### **App-Level Configuration**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `country_code`       | string     | (optional)     | Country code for your location to find holidays, e.g. `NO`. Weekends count as holidays. |
| `vacation`           | input_boolean | `input_boolean.vacation` if it exists | Vacuums are not started while it is on, and start once when it is turned off (inside the vacuum start window, if nobody is home). On at startup gives `away`. The old name `away_state` still works and wins if both are set. |
| `HALightModeText`    | input_text | (optional)     | Input text to display current light mode. Also used at startup to restore the last mode. |
| `notify_receiver`    | list       | (optional)     | List of devices to send notifications to (e.g., `mobile_app_your_phone`).   |
| `MQTT_namespace`     | string     | `"mqtt"`       | MQTT namespace.                                                             |
| `HASS_namespace`     | string     | `"default"`    | Home Assistant namespace.                                                   |
| `morning_start_listen_time` | string | `"06:00:00"` | Time to start listening for morning sensors to change from night to morning.|
| `execute_morning_at` | string     | `"10:00:00"`   | Time to change from night or morning to normal mode if the sensors have not done it. |
| `morning_to_normal`  | string     | `execute_morning_at` | Time to change mode from morning to normal. Morning sensors after this time set normal instead of morning. |
| `night_start_listen_time` | string | `"22:00:00"` | Time to start listening for night sensors to activate night mode.            |
| `execute_night_at`   | string     | `"02:00:00"`   | Time to execute night mode (not in away mode).                              |
| `delay_before_setting_away` | int | `0` | Optional delay in seconds before setting away mode and starting the vacuums when no one is home. The door is locked without this delay. |
| `keep_mode_when_outside` | input_boolean | (optional) | If on when the last adult or family member leaves, away mode is not set and the vacuums are not started. The door is still locked. Turned off at `morning_start_listen_time` unless the mode is `away`. |
| `family`             | string     | (optional)     | Light mode used instead of `automagical` while a family member is home and no adult is. See [Family light mode](#family-light-mode). |
| `vacuum_earliest_start` | string  | `morning_start_listen_time` | Earliest time of day vacuums are started when leaving. |
| `vacuum_latest_start` | string    | `"18:00:00"`   | Latest time of day vacuums are started when leaving.                         |
| `notify_app`         | string     | (optional)     | AppDaemon app with `send_notification`. Home Assistant `notify` is used without it. |
| `prevent_vacuum`     | list       | (optional)     | Sensors to prevent vacuum cleaners from running.                            |
| `turn_on_in_the_morning` | list   | (optional)     | Entities that are `off` are turned on when the mode changes from night to morning or normal between `morning_start_listen_time` and `execute_morning_at`. |
| `turn_off_at_night`  | list       | (optional)     | Entities that are `on` are turned off when night mode is set between `night_start_listen_time` and `execute_night_at`. |

> Times that cannot be parsed fall back to the default, with a warning in the log.

### **Mode Triggers**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `morning_sensors`    | list       | (optional)     | Sensors turning `on` after `morning_start_listen_time` set morning mode (normal mode on weekends, holidays and after `morning_to_normal`). |
| `night_sensors`      | list       | (optional)     | Sensors turning `on` after `night_start_listen_time` set night mode (not in away mode). |

### **Presence Tracking**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `presence`           | list       | (optional)     | List of persons with roles.                                                 |
| `person`             | person/tracker | (optional) | Person or tracker to track.                                                 |
| `role`               | string     | `adult`        | Person role (`adult`, `kid`, `family`, `housekeeper`, `tenant`)             |
| `outside_switch` (or `outside`) | input_boolean |  (optional) | Manually set person away.                                       |
| `lock_user`          | int/string | (optional)     | Lock user ID for MQTT door lock.                                            |
| `stopMorning`        | bool       | `False`        | Ends morning mode when this person leaves and someone else is home.         |

> 💡 **Tip**: Unknown keys in a `presence` or `vacuum` entry are ignored, so a misspelled key is silently dropped. An entry with an invalid value, for example an unknown role, is skipped with an error in the log.

### **Vacuum Cleaners**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `vacuum`             | list       | (optional)     | List of vacuum cleaners. Each is an entity id or a dict with the keys below. |
| `vacuum` (in list)   | string     |                | Vacuum entity.                                                              |
| `battery`            | string     | (optional)     | Battery sensor.                                                             |
| `daily_routine`      | string     | (optional)     | Button, input_button, script or switch that starts the cleaning.            |
| `min_battery`        | number     | `vacuum_min_battery` | Lowest battery level (exclusive) to start.                            |
| `prevent_vacuum` (in list) | list | global `prevent_vacuum` | Replaces the global list for this vacuum.                          |
| `vacuum_min_battery` | number     | `40`           | App wide minimum battery level to start.                                    |
| `vacuum_event`       | string     | (optional)     | Fire this event with `action: start`/`stop` for the `VacuumManager` app.    |

### **`VacuumManager` app**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `vacuum`             | list       | (optional)     | Same format as `vacuum` above.                                              |
| `prevent_vacuum`     | list       | (optional)     | Global prevent list.                                                        |
| `min_battery`        | number     | `40`           | App wide minimum battery level. Note: `min_battery` here, not `vacuum_min_battery`. |
| `vacuum_event`       | string     | `VACUUM_CONTROL` | Event to listen for, with `action: start` or `action: stop`.              |
| `HASS_namespace`     | string     | `"default"`    | Home Assistant namespace.                                                   |

### **MQTT Door lock**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `MQTT_door_lock`     | list       | (optional)     | List of MQTT door lock topics that are locked when away and at night.       |
| `unlock_door_when_home` | bool    | `False`        | Also unlock the door when an adult/family member arrives (not in away or night mode) and in the morning. |

### **Alarm Sensors**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `alarmsensors`       | list       | (optional)     | Sensors (`on`, `open`, `opening`) to trigger notifications and media playback. Each is an entity id or `sensor:` with an own `camera:` and `play_media: False` for notification only. |
| `alarm_camera`       | camera     | (optional)     | Camera for the picture in the notification.                                 |
| `snapshot_directory` | path       | (optional)     | Save snapshots here with `utils_apps` ([see above](#-picture-with-the-alarm-notification)). |
| `snapshot_keep_days` | number     | (optional)     | Delete saved snapshots older than this.                                     |
| `alarm_media`        | list       | (optional)     | Players to start when alarmsensors are triggered. Keys: `player` and `playlist` (required), `amp`, `source`, `volume`, `normal_volume` (`source`, `volume` and `normal_volume` need `amp`). Playback starts 8 seconds after source and volume are set. `normal_volume` is set back after 2 minutes. |

---

## 🧩 Example Configuration  
```yaml
manageModes:
  module: modeManagement
  class: ModeManagement
  country_code: 'NO'
  vacation: input_boolean.vacation
  HALightModeText: input_text.lightmode

  # Notification setup
  notify_receiver:
    - mobile_app_my_phone

  # Morning routine setup
  morning_sensors:
    - binary_sensor.motion_detection
    - binary_sensor.presence_sensor
  morning_start_listen_time: '06:00:00'
  morning_to_normal: '09:00:00'
  execute_morning_at: '10:00:00'
  turn_on_in_the_morning:
    - media_player.amp

  # Night routine setup
  night_sensors:
    - binary_sensor.window_door_is_open
  night_start_listen_time: '22:00:00'
  execute_night_at: '02:00:00'
  turn_off_at_night:
    - media_player.amp

  # Doorlock setup
  MQTT_door_lock:
    - zigbee2mqtt/NimlyDoor
  unlock_door_when_home: False

  # Presence detection setup
  presence:
    - person: person.me
      outside: input_boolean.outside_me
      role: adult
      lock_user: 0

  # Vacuum setup
  vacuum:
    - vacuum: vacuum.roborock_s8
      battery: sensor.roborock_s8_battery
  prevent_vacuum:
    - media_player.tv

  # Alarm configurations
  alarm_camera: camera.entrance
  alarmsensors:
    - binary_sensor.entrance_motion_motion_detection
    - sensor: cover.garage_door
      camera: camera.garage
    - binary_sensor.door_window_door_is_open
  alarm_media:
    - amp: media_player.your_amp # Device to turn on
      source: Roon # Source select on device
      volume: 0.5 # Volume on device
      normal_volume: 0.33 # Volume to return to after 2 minutes (optional)
      player: media_player.yourplayer
      playlist: 'Library/Artists/Alarm/Alarm'
```

## 📌 License  
[MIT License](LICENSE)  

---

## 📈 Roadmap  
- Rewrite MQTT door lock to support more lock types.

---

## 🙋 Contributing  
- Found a bug? Open an issue or submit a PR!  
- Want to add a feature? Discuss in the [GitHub Discussions](https://github.com/Pythm/ad-ModeManagement/discussions).  

---

**ModeManagement by [Pythm](https://github.com/Pythm)**  
[GitHub](https://github.com/Pythm/ad-ModeManagement)
