
# ModeManagement by Pythm  
**An example of automating modes with AppDaemon to set suitable lights using the [Lightwand](https://github.com/Pythm/ad-Lightwand) AppDaemon app and automate other entities and appliances based on presence.**

---

## 🔍 Features
- **Morning/Night Mode Triggers**: Uses presence, time, and sensor triggers to automatically switch between `normal`, `morning`, and `night` modes.
- **Vacation Mode**: Prevents day to day mode changes when a user-defined `input_boolean.vacation` is active.
- **Door Lock Integration**: Supports MQTT-based door locks (e.g., Nimly) for auto-locking when no adults are home or during nighttime.
- **Vacuum Cleaner Automation**: Triggers vacuum cleaners when no adults are home and stops them if an adult returns.
- **Alarm Notifications**: Sends alerts via `notify_receiver` when sensors are triggered (e.g., open windows, motion) and no one is home.
- **Customizable Schedules**: All times and thresholds are configurable for flexibility.

---

## 🚨 Breaking Changes
### **0.2.1**
- **Morning routine**: Defining `country_code` is now optional and app will not try to find location based on Appdaemon config. Lack of doing so will fire **morning** mode every day.

### **0.2.0**
- **Lightwand translations**: App now uses Lightwand translations singleton. This requires at least one app with Lightwand version 2.0.0 or later running on your system. Check out https://github.com/Pythm/ad-Lightwand?tab=readme-ov-file#-translating-or-changing-modes on how to use your own mode names.

### **0.1.12**
- **MQTT Namespace Update**: Default MQTT namespace changed to `'mqtt'` to align with AppDaemon defaults.

### **0.1.13**
- **Spelling Correction**: Changed `notify_reciever` → `notify_receiver`.

---

## 📦 Dependencies

Install the required packages using `requirements.txt`:
  - holidays

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
| **adult** | Primary role. If no adults are home and a door‑lock is configured, the door will lock and relock; vacuums will start. | |
| **kid** | Keeps doors locked and starts vacuum if only kids are home. | |
| **family** | Extended family; behaves like an adult except does not start vacuum when leaving. | |
| **housekeeper** | Switches Light mode to `wash` and notifies you when the housekeeper arrives while no one else is home. | |

### MQTT Door locks


> ⚠️ **Safety note** – Mqtt door lock will be rewritten to better support id, and only unlock if enabled as a option. 

---

## Vacuum Cleaners

You can automatically start and stop a vacuum cleaner when a person with the *adult* role leaves or returns home.

### What it can do

| Feature | Description |
|---------|-------------|
| **Battery monitoring** | If the vacuum entity doesn’t expose a battery level, you can point to a separate battery sensor. |
| **Custom start routine** | Configure `daily_routine` with an entity that triggers the vacuum (e.g., a button or switch). |

### Example configuration


```yaml
vacuum:
  - vacuum: vacuum.roborock_s8
    battery: sensor.roborock_s8_battery   # optional – only if the vacuum entity lacks a battery attribute
    daily_routine: button.daily_clean     # the entity that starts the cleaning job
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

---

### 📢 Notifications  
- Configure `notify_receiver` with a list of devices (e.g., `mobile_app_your_phone`).  
- You can use a custom notification app instead with `notify_app` that contains the `send_notification` function. 

---

## 📚 Key Definitions  
### **App-Level Configuration**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `country_code`       | country_code | (optional)   | Country code for your location to find hollidays                            |
| `vacation`           | input_boolean | `input_boolean.vacation` | Input boolean to prevent mode changes during vacation.         |
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
| `keep_mode_when_outside` | input_boolean | `input_boolean.keep_mode` | Prevents mode changes when away.                          |
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

### **Vacuum Cleaners**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `vacuum`             | dict       | (optional)     | List of vacuum cleaner entities.                                            |
| `vacuum`             | string     | (optional)     | Name of vacuum.                                                             |
| `battery`            | string     | (optional)     | battery sensor.                                                             |

### **MQTT Door lock**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `MQTT_door_lock`     | list       | (optional)     | List of doorlocks to automatically unlock and disable relock when home.     |

### **Alarm Sensors**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `alarmsensors`       | list       | (optional)     | Sensors to trigger notifications and media playback.                        |
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
  alarmsensors:
    - binary_sensor.entrance_motion_motion_detection
    - cover.garage_door
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
- Capture and send picture with notification on alarm.

---

## 🙋 Contributing  
- Found a bug? Open an issue or submit a PR!  
- Want to add a feature? Discuss in the [GitHub Discussions](https://github.com/Pythm/ad-ModeManagement/discussions).  

---

**ModeManagement by [Pythm](https://github.com/Pythm)**  
[GitHub](https://github.com/Pythm/ad-ModeManagement)
