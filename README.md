
# ModeManagement by Pythm  
**An example of automating modes with AppDaemon to set suitable lights using the [Lightwand](https://github.com/Pythm/ad-Lightwand) AppDaemon app and automate other entities and appliances based on presence.**

---

## 🔍 Features
- **Morning/Night Mode Triggers**: Uses presence, time, and sensor triggers to automatically switch between `normal`, `morning`, and `night` modes.
- **Vacation Mode**: While your `vacation` switch is on, vacuum cleaners are not started (so a robot is not left running or stuck with a draining battery). When the switch is turned off the vacuums start once, if nobody is home, so the house is clean when you arrive. The switch does not block or change modes by itself. If AppDaemon starts with it on, the mode is `away`, and the morning and night routines do nothing while the mode is `away`.
- **Door Lock Integration**: Supports MQTT-based door locks (e.g., Nimly) for auto-locking when no adults are home or during nighttime.
- **Vacuum Cleaner Automation**: Triggers vacuum cleaners when no adults are home and stops them if an adult returns. Can run inside ModeManagement or as the separate `VacuumManager` app.
- **Alarm Notifications**: Sends alerts via `notify_receiver` when sensors are triggered (e.g., open windows, doors, motion) and no one is home. Optionally with a picture from a camera.
- **Customizable Schedules**: All times and thresholds are configurable for flexibility.

---

## 🚨 Breaking Changes
### **0.3.1**
Nothing to do if you only use the defaults, except the door lock behaviour below. Your YAML keeps working.

- **Door unlock is now opt-in**: Before, the door was unlocked when an adult or family member arrived and when morning started after the night. Now the door stays locked unless you set `unlock_door_when_home: True` (see [MQTT Door locks](#mqtt-door-locks)). Set it to keep the old behaviour. Locking when away or at night is unchanged.
- **Presence**: A person or tracker changing to `unavailable` or `unknown` (for example when Home Assistant restarts) is ignored instead of being treated as leaving home. A person who really leaves still goes from `home` to another state.
- **Alarm sensors**: Doors and covers (`open`, `opening`) now trigger the same way as `on`. A sensor going from `unavailable`/`unknown` to `on` does not trigger. `alarm_media` now has its own 10 minute pause. Before, the playlist started on every sensor change. New: `play_media: False` on a sensor gives notification only.
- **Vacuum**: `daily_routine` was ignored in earlier versions and the full program was started instead. It is now used when set. Vacuums are only started when the vacuum is `docked` or `charging`, as before. When the vacation switch is turned off, vacuums only start if nobody is home.
- **Vacuum start window**: The start window is `morning_start_listen_time` to `18:00:00` as before. It can now be set with `vacuum_earliest_start` and `vacuum_latest_start`.
- **Startup**: The app no longer stops if `HALightModeText` is `unknown`, `unavailable` or still shows `fire` after a restart. It then uses `night` between `execute_night_at` and `morning_start_listen_time`, otherwise `automagical`.
- **Python packages**: `holidays` is only imported when `country_code` is set.
- **Translations**: If you translate or rename modes, set the language once with the new `ModeTranslation` app that comes with Lightwand 2.3.0 and add `dependencies: mode_translation` to this app, so the mode names are loaded before this app starts. Without it the result depends on the order AppDaemon starts your apps in. English users need no change. See [Lightwand: Translating or Changing Modes](https://github.com/Pythm/ad-Lightwand#-translating-or-changing-modes).
- **Fix**: The mode event fired when someone arrives home from `away` now uses `HASS_namespace` like all other events from this app.

### **0.2.1**
- **Morning routine**: Defining `country_code` is now optional and app will not try to find location based on Appdaemon config. Lack of doing so will fire **morning** mode every day.

### **0.2.0**
- **Lightwand translations**: App now uses Lightwand translations singleton. This requires Lightwand version 2.0.0 or later installed in your AppDaemon (the mode names are read from Lightwand's `translations_lightmodes` module). Check out https://github.com/Pythm/ad-Lightwand?tab=readme-ov-file#-translating-or-changing-modes on how to use your own mode names.

### **0.1.12**
- **MQTT Namespace Update**: Default MQTT namespace changed to `'mqtt'` to align with AppDaemon defaults.

### **0.1.13**
- **Spelling Correction**: Changed `notify_reciever` → `notify_receiver`.

---

## 📦 Dependencies

Install the required packages using `requirements.txt`:
  - holidays (only needed if you set `country_code`)

`pydantic` is installed with AppDaemon.

Other apps:
  - [Lightwand](https://github.com/Pythm/ad-Lightwand) 2.3.0 or later is required (mode names). Install it with HACS or by cloning it.
  - [Pythm_AppdaemonApps](https://github.com/Pythm/Pythm_AppdaemonApps) is optional, only for `snapshot_directory`. Clone it into your `apps` folder yourself.

This repository is **not** published to HACS (only Lightwand and ClimateCommander are), so it is installed by cloning. Neither `git clone` nor `requirements.txt` installs other repositories automatically, so each repository above has to be installed on its own.

- If you run Appdaemon as a Addon in HA you'll have to specify the python packages manually in configuration in the Addon and restart Appdaemon.

- If your Appdaemon install method does not handle requirements automatically:

```bash
pip install -r requirements.txt
```

---

## 🛠️ Installation
1. **Clone the repository** into your AppDaemon `apps` directory:  
   ```bash
   git clone https://github.com/Pythm/ad-ModeManagement.git /path/to/appdaemon/apps/
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
- **Vacation Mode**: Prevents day to day mode changes from app when `input_boolean.vacation` is active.
- **Holiday Detection**: Define `country_code` to fetch holidays. This will set normal automation instead of morning mode during hollidays and weekends. If not defined, app will call morning mode every day.
- **Light‑Mode Display** – Use a Home Assistant input_text helper configured with (`HALightModeText`) to show the current Light mode.

> [!NOTE]  
> If a light in Lightwand does not contain morning mode, the automagical automation is automagically controlling your light.

---

## 📚 Configurations

### Using different roles for persons
| Role | Description | Door‑Lock / Vacuum Behaviour |
|------|-------------|------------------------------|
| **adult** | Primary role. If no adults are home and a door‑lock is configured, the door will lock and relock; vacuums will start. The door unlocks when an adult arrives only with `unlock_door_when_home`. | |
| **kid** | Keeps doors locked and starts vacuum if only kids are home. | |
| **family** | Extended family; behaves like an adult except does not start vacuum when leaving. | |
| **housekeeper** | Switches Light mode to `wash` and notifies you when the housekeeper arrives while no one else is home. | |

### MQTT Door locks


The door is locked (and auto relock enabled) when the last adult/family member leaves, in away mode and in night mode.

The door is **not** unlocked automatically. To unlock it when an adult or family member arrives home (not in away or night mode) and when morning starts after the night, set `unlock_door_when_home: True`. Auto relock is then disabled until the next lock.

```yaml
  MQTT_door_lock:
    - zigbee2mqtt/NimlyDoor
  unlock_door_when_home: True   # optional, default False
```

> ⚠️ **Safety note** – Think about whether it is safe to leave your door unlocked when you are home before you enable `unlock_door_when_home`.

---

## Vacuum Cleaners

You can automatically start and stop a vacuum cleaner when a person with the *adult* role leaves or returns home.

### What it can do

| Feature | Description |
|---------|-------------|
| **Start when away** | Starts docked vacuums when the last adult/family member has left, between `vacuum_earliest_start` (default `morning_start_listen_time`) and `vacuum_latest_start` (default `18:00:00`). Not while `vacation` is on. |
| **Start after vacation** | When the `vacation` switch is turned off and nobody is home, the vacuums start once. |
| **Return to base** | When an adult or family member arrives, vacuums started by the app go back to their base. A vacuum that was already cleaning when the app looked (started by you) is left alone until it is docked. |
| **Battery** | Vacuums start only above `min_battery` (default 40 %). If the vacuum entity doesn’t expose a battery level, point to a separate battery sensor with `battery`. |
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
- If any of those entities reports a state of **`on`**, the automation will **skip** starting the vacuum.

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

Use either `vacuum:` or `vacuum_event` in ModeManagement, not both.

---

### 📢 Notifications  
- Configure `notify_receiver` with a list of devices (e.g., `mobile_app_your_phone`).  
- You can use a custom notification app instead with `notify_app` that contains the `send_notification` function. If the app is not found, Home Assistant `notify` is used.

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
- Only one notification is sent each 10 minutes.

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

## 📚 Key Definitions  
### **App-Level Configuration**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `country_code`       | country_code | (optional)   | Country code for your location to find hollidays                            |
| `vacation`           | input_boolean | `input_boolean.vacation` if it exists | Input boolean. Vacuums are not started while it is on, and start once when turned off. |
| `HALightModeText`    | input_text | (optional)     | Input text to display current light mode.                                   |
| `notify_receiver`    | list       | (optional)     | List of devices to send notifications to (e.g., `mobile_app_your_phone`).   |
| `MQTT_namespace`     | string     | `"mqtt"`       | MQTT namespace.                                                             |
| `HASS_namespace`     | string     | `"default"`    | Home Assistant namespace.                                                   |
| `morning_start_listen_time` | string | `"06:00:00"` | Time to start listening for morning sensors to change form night to morning.|
| `execute_morning_at` | string     | `"10:00:00"`   | Time to execute morning mode if sensors has not been triggered.             |
| `morning_to_normal`  | string     | `"09:00:00"`   | Time to change mode from morning to normal.                                 |
| `night_start_listen_time` | string | `"22:00:00"` | Time to start listening for night sensors to activate night mode.            |
| `execute_night_at`   | string     | `"02:00:00"`   | Time to execute night mode.                                                 |
| `delay_before_setting_away` | int | `0` | Optional delay in seconds before setting away mode when no one is home.                |
| `keep_mode_when_outside` | input_boolean | (optional) | If on when the last adult leaves, away mode is not set. Turned off at `morning_start_listen_time`. |
| `vacuum_earliest_start` | string  | `morning_start_listen_time` | Earliest time of day vacuums are started when leaving. |
| `vacuum_latest_start` | string    | `"18:00:00"`   | Latest time of day vacuums are started when leaving.                         |
| `notify_app`         | string     | (optional)     | AppDaemon app with `send_notification`. Home Assistant `notify` is used without it. |
| `prevent_vacuum`     | list       | (optional)     | Sensors to prevent vacuum cleaners from running.                            |
| `turn_on_in_the_morning` | list   | (optional)     | Entities to turn on in the morning.                                         |
| `turn_off_at_night`  | list       | (optional)     | Entities to turn off at night.                                              |

### **Mode Triggers**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `morning_sensors`    | list       | (optional)     | Sensors to trigger morning mode.                                            |
| `night_sensors`      | list       | (optional)     | Sensors to trigger night mode.                                              |

### **Presence Tracking**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `presence`           | list       | (optional)     | List of persons with roles (`adult`, `kid`, `housekeeper`)                  |
| `person`             | person/tracker | (optional) | Person or tracker to track.                                                 |
| `role`               | string     | `adult`        | Person role (`adult`, `kid`, `family`, `housekeeper`)                       |
| `outside_switch`     | input_boolean |  (optional) | Manually set person away.                                                   |
| `lock_user`          | int        | (optional)     | Lock user ID for MQTT door lock.                                            |
| `stopMorning`        | bool       | `False`        | Ends morning mode when this person leaves and someone else is home.         |

### **Vacuum Cleaners**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `vacuum`             | list       | (optional)     | List of vacuum cleaners. Each is an entity id or a dict with the keys below. |
| `vacuum` (in list)   | string     |                | Vacuum entity.                                                              |
| `battery`            | string     | (optional)     | Battery sensor.                                                             |
| `daily_routine`      | string     | (optional)     | Button, input_button, script or switch that starts the cleaning.            |
| `min_battery`        | number     | `vacuum_min_battery` | Lowest battery level (exclusive) to start.                            |
| `vacuum_min_battery` | number     | `40`           | App wide minimum battery level to start.                                    |
| `vacuum_event`       | string     | (optional)     | Fire this event with `action: start`/`stop` for the `VacuumManager` app.    |

### **MQTT Door lock**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `MQTT_door_lock`     | list       | (optional)     | List of MQTT door lock topics that are locked when away and at night.       |
| `unlock_door_when_home` | bool    | `False`        | Also unlock the door when an adult/family member arrives and in the morning. |

### **Alarm Sensors**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `alarmsensors`       | list       | (optional)     | Sensors (`on`, `open`, `opening`) to trigger notifications and media playback. Each is an entity id or `sensor:` with an own `camera:` and `play_media: False` for notification only. |
| `alarm_camera`       | camera     | (optional)     | Camera for the picture in the notification.                                 |
| `snapshot_directory` | path       | (optional)     | Save snapshots here with `utils_apps` ([see above](#-picture-with-the-alarm-notification)). |
| `snapshot_keep_days` | number     | (optional)     | Delete saved snapshots older than this.                                     |
| `alarm_media`        | dict       | (optional)     | Playlist and media settings to play when alarmsensors are triggered.        |

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
      battery: sensor.roborock_s8_batteri
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
[MIT License](https://github.com/Pythm/ad-ModeManagement/blob/main/LICENSE)  

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
