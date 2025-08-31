
# ModeManagement by Pythm  
**An example of automating modes with AppDaemon to set suitable lights using the [Lightwand](https://github.com/Pythm/ad-Lightwand) AppDaemon app and automate other entities and appliances based on presence.**  

---

## 🔍 Features  
- **Light Mode Automation**: Listens to the `MODE_CHANGE` event in Home Assistant to set different light modes (e.g., `normal`, `night`, `wash`) using the [Lightwand](https://github.com/Pythm/ad-Lightwand) app.  
- **Morning/Night Mode Triggers**: Uses presence, time, and sensor triggers to automatically switch between `normal`, `morning`, and `night` modes.  
- **Vacation Mode**: Prevents mode changes when a user-defined `input_boolean.vacation` is active.  
- **Door Lock Integration**: Supports MQTT-based door locks (e.g., Nimly) for auto-locking when no adults are home or during nighttime.  
- **Vacuum Cleaner Automation**: Triggers vacuum cleaners when no adults are home and stops them if an adult returns.  
- **Alarm Notifications**: Sends alerts via `notify_receiver` when sensors are triggered (e.g., open windows, motion) and no one is home.  
- **Customizable Schedules**: All times and thresholds are configurable for flexibility.  

---

## 🚨 Breaking Changes  
### **1.2.0**  
- **MQTT Namespace Update**: Default MQTT namespace changed to `'mqtt'` to align with AppDaemon defaults. 

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

## 📌 Notes 
- **Vacation Mode**: Prevents mode changes when `input_boolean.vacation` is active.  
- **Holiday Detection**: Uses `country_code` to fetch holidays. If not defined, it attempts to find latitude/longitude from AppDaemon configuration.  
- **MQTT Door Lock**: Tested with Nimly locks (use at your own risk due to potential MQTT bugs).  
- **Vacuum Cleaner Behavior**: Vacuums start when no adults are home and return to dock if an adult returns.  

---

## 📚 Key Definitions  
### **App-Level Configuration**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `vacation`           | input_boolean | `input_boolean.vacation` | Input boolean to prevent mode changes during vacation.                      |
| `HALightModeText`    | input_text | `input_text.lightmode` | Input text to display current light mode.                                   |
| `notify_receiver`    | list       | (optional)     | List of devices to send notifications to (e.g., `mobile_app_your_phone`).   |
| `MQTT_namespace`     | string     | `"mqtt"`       | MQTT namespace (optional).                             |
| `HASS_namespace`     | string     | `"default"`    | Home Assistant namespace (optional).                                        |
| `morning_start_listen_time` | string | `"06:00:00"` | Time to start listening for morning sensors.                                |
| `execute_morning_at` | string     | `"10:00:00"`   | Time to execute morning mode.                                               |
| `morning_to_normal`  | string     | `"09:00:00"`   | Time to switch to normal mode after morning.                                |
| `night_start_listen_time` | string | `"22:00:00"` | Time to start listening for night sensors.                                  |
| `execute_night_at`   | string     | `"02:00:00"`   | Time to execute night mode.                                                 |
| `delay_before_setting_away` | int | `0` | Optional delay in seconds before setting away mode when no one is home.             |
| `keep_mode_when_outside` | input_boolean | `input_boolean.keep_mode` | Prevents mode changes when away.                  |

### **Mode Triggers**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `morning_sensors`    | list       | (optional)     | Sensors to trigger morning mode.                                            |
| `night_sensors`      | list       | (optional)     | Sensors to trigger night mode.                                              |
| `turn_on_in_the_morning` | list | (optional)     | Entities to turn on in the morning.                                         |
| `turn_off_at_night`  | list       | (optional)     | Entities to turn off at night.                                              |

### **Presence Tracking**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `presence`           | list       | (optional)     | List of persons with roles (`adult`, `kid`, `housekeeper`)                  |
| `outside`            | string     | input_boolean  | Manually set person away.                                                   |
| `lock_user`          | int        | (optional)     | Lock user ID for Nimly door locks.                                          |

### **Vacuum Cleaners**  
| Key                  | Type       | Default        | Description                                                                 |
|----------------------|------------|----------------|-----------------------------------------------------------------------------|
| `vacuum`             | list       | (optional)     | List of vacuum cleaner entities.                                            |
| `prevent_vacuum`     | list       | (optional)     | Sensors to prevent vacuum cleaners from running.                            |

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
  notify_receiver:
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
  alarm_media:
    - amp: media_player.denon_avr_x3000
      source: Roon
      volume: 0.5
      normal_volume: 0.33
      player: media_player.yourplayer
      playlist: 'Library/Artists/Alarm/Alarm'
```

---

## 📌 Tips & Best Practices  
- Use **`input_boolean`** to toggle automation on/off with `vacation`. 
- **Vacuum cleaners** will not run if `prevent_vacuum` sensors are active.  
- Use **`input_text`** (`HALightModeText`) to display the current light mode.
- Supports the same translation on Modes as Lightwand. Check out the documentation for Lightwand in the translation section to listen for another event than "MODE_CHANGE" or use your own names for the predefined mode names.
- Define morning_start_listen_time and night_start_listen_time to align with your household’s schedule.

---

## 📢 Notifications  
- Configure `notify_receiver` with a list of devices (e.g., `mobile_app_your_phone`).  
- Use a custom notification app with the `send_notification` method.  

---

## 📌 License  
[MIT License](https://github.com/Pythm/ad-ModeManagement/blob/main/LICENSE)  

---

## 📈 Roadmap  
- Nothing planned

---

## 🙋 Contributing  
- Found a bug? Open an issue or submit a PR!  
- Want to add a feature? Discuss in the [GitHub Discussions](https://github.com/Pythm/ad-ModeManagement/discussions).  

---

**ModeManagement by [Pythm](https://github.com/Pythm)**  
[GitHub](https://github.com/Pythm/ad-ModeManagement)
