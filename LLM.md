# ad-ModeManagement: notes for an AI assistant

Read this with [README.md](README.md). The workflow for finding the user's real entity ids (token, `ha_snapshot.py`, asking when several match) is in the [Pythm_AppdaemonApps LLM guide](https://github.com/Pythm/Pythm_AppdaemonApps/blob/master/LLM_GUIDE.md). Follow its rules: ids from the index only, ask when several match, one app per `apps.yaml` edit, back up first, no commit or push unasked.

## What the app does

Keeps one house mode (`automagical`, `morning`, `night`, `away`, `wash`, and an optional family mode) from presence, time and sensors, and fires `MODE_CHANGE` so Lightwand rooms follow. It also **acts on its own**: locks (and, opt-in, unlocks) MQTT door locks, starts and stops robot vacuums, turns entities on in the morning and off at night, and sends alarm notifications (optionally with a camera picture and loud media) when sensors trigger while nobody is home.

Mode names come from Lightwand's translations. If the user has translated them, use their names everywhere below.

## Config (apps.yaml)

No app-level key is required. Required keys inside list entries are marked.

```yaml
manageModes:                        # FireAlarm finds the app by this name (its modeManagementApp)
  module: modeManagement
  class: ModeManagement
  dependencies:                     # only names of apps that exist in apps.yaml
    - mode_translation              # only if that app is configured
    - notify_mobiles                # only if notify_app is used
  HASS_namespace: default
  MQTT_namespace: mqtt              # namespace of the plugin named MQTT in appdaemon.yaml
  country_code: '<ISO code>'        # needs the holidays package
  vacation: input_boolean.xxx       # default input_boolean.vacation if it exists. Old name away_state wins if both are set
  HALightModeText: input_text.xxx
  notify_app: notify_mobiles
  notify_receiver: [<receiver>]     # meaning depends on notify_app, see table
  family: <light mode name>
  keep_mode_when_outside: input_boolean.xxx
  delay_before_setting_away: 0      # seconds
  morning_start_listen_time: '06:00:00'
  morning_to_normal: '09:00:00'     # unset: same as execute_morning_at
  execute_morning_at: '10:00:00'
  night_start_listen_time: '22:00:00'
  execute_night_at: '02:00:00'
  morning_sensors: [binary_sensor.xxx]
  night_sensors: [binary_sensor.xxx]
  turn_on_in_the_morning: [switch.xxx]
  turn_off_at_night: [media_player.xxx]
  presence:
    - person: person.xxx            # REQUIRED in each entry
      role: adult                   # adult (default), kid, family, housekeeper, tenant
      outside_switch: input_boolean.xxx   # old name: outside
      lock_user: 1                  # user slot in the door lock
      stopMorning: false
  alarm_camera: camera.xxx
  alarmsensors:
    - binary_sensor.xxx
    - sensor: cover.xxx             # 'sensor' is the key name, any domain fits
      camera: camera.xxx
      play_media: false             # notification only
  alarm_media:
    - player: media_player.xxx      # REQUIRED
      playlist: '<id the player understands>'   # REQUIRED
      amp: media_player.xxx         # needed for source, volume and normal_volume
      source: '<source name>'
      volume: 0.5
      normal_volume: 0.3
  snapshot_directory: <folder inside HA www>    # needs utils_apps
  snapshot_keep_days: 7
  MQTT_door_lock: [zigbee2mqtt/<lock name>]
  unlock_door_when_home: false
  vacuum:                           # use vacuum OR vacuum_event, never both
    - vacuum: vacuum.xxx            # REQUIRED (a plain entity id as list item also works)
      battery: sensor.xxx
      daily_routine: button.xxx
      min_battery: 50
      prevent_vacuum: [input_boolean.xxx]   # replaces the global list for this vacuum
  prevent_vacuum: [input_boolean.xxx]
  vacuum_min_battery: 40
  vacuum_earliest_start: '06:00:00' # default: morning_start_listen_time
  vacuum_latest_start: '18:00:00'
  vacuum_event: VACUUM_CONTROL      # only with a separate VacuumManager app
```

Separate vacuum app (instead of `vacuum:` above):

```yaml
vacuums:
  module: vacuum_manager
  class: VacuumManager
  vacuum: [...]                     # same format as above
  prevent_vacuum: [...]
  min_battery: 40                   # min_battery here, not vacuum_min_battery
  vacuum_event: VACUUM_CONTROL
  HASS_namespace: default
```

Times are `HH:MM:SS` (quoted is clearest, unquoted numbers from YAML are converted). A time that cannot be parsed falls back to its default with a WARNING. Unknown keys inside `presence` and `vacuum` entries are silently ignored, so check spelling. An `alarm_media` entry without `player` or `playlist`, or with `source`, `volume` or `normal_volume` but no `amp`, is logged as an ERROR and skipped. Never set `home`, `outside_activated`, `manual_start` or `started`: they are runtime fields.

## Which entities fit each key

| Key | Entity or value | Hints when searching the index |
|---|---|---|
| `presence[].person` | `person.*` (or `device_tracker.*`) | State must be `home` when home. Prefer `person`. A `binary_sensor` does not work. |
| `presence[].outside_switch`, `keep_mode_when_outside` | `input_boolean` helper | Usually does not exist yet. Tell the user what to create. |
| `presence[].lock_user` | Number, not an entity | The user slot in the lock. Not in the index, ask. |
| `vacation` | `input_boolean` helper | Search `vacation`, `ferie`, `holiday`. |
| `HALightModeText` | `input_text` helper | Created by the user. |
| `notify_receiver` | Without `notify_app`: `kind` `notify_service` named `mobile_app_...`. With `notify_mobiles`: the `person` labels from that app. | Check which of the two applies before searching. |
| `morning_sensors`, `night_sensors` | Anything that turns exactly `on`: `binary_sensor` (motion, occupancy, presence, door), `input_boolean`, `switch` | A numeric `sensor` never fires. |
| `turn_on_in_the_morning`, `turn_off_at_night` | `switch`, `light`, `media_player`, `input_boolean` | Only turned on from exactly `off`, off from exactly `on`. A `playing` media player is not turned off. |
| `alarmsensors` | `binary_sensor` (motion, occupancy, door, window, opening), `switch`, `cover` | Triggers on `on`, `open`, `opening`. |
| `alarm_camera`, `alarmsensors[].camera` | `camera.*` | Pick the camera that sees that sensor. |
| `alarm_media[].amp`, `player` | `media_player.*` | `source` must be one of the amp's sources. `playlist` is not in the index, ask. |
| `MQTT_door_lock` | MQTT topic, not in the index | Zigbee2MQTT: `<base_topic>/<lock friendly name>`. Say it is a guess and ask. The lock must report `last_unlock_user` and accept `auto_relock` (for example Nimly). |
| `vacuum[].vacuum` | `vacuum.*` | |
| `vacuum[].battery` | `sensor` with `device_class` `battery` of the same device | Only needed if the vacuum has no `battery_level` attribute. |
| `vacuum[].daily_routine` | `button`, `input_button`, `script`, or a `switch` | A routine from the vacuum integration. |
| `prevent_vacuum` | Anything whose state is exactly `on` when the vacuum must wait | `input_boolean`, `switch`, `binary_sensor`. |

## ALWAYS ask the user

Do not decide these from names, rooms or defaults. Wait for the answer before writing the block.

- **Role of each person:** adult, kid, family (extended family, for example grandparents), housekeeper or tenant. Roles change what happens when they come and go (see below).
- **Lock user slots:** which person has which `lock_user` number in the door lock. A wrong number sends wrong notifications, and for a housekeeper it can set `wash` mode.
- **Outside switches:** what each switch means to them (for example "I am in the garden"). While it is on, that person counts as away: the door locks, vacuums may start, and away may be set.
- **Notifications:** who gets them, and whether `notify_mobiles` is used (it changes what `notify_receiver` must contain).
- **Door unlock:** should the door unlock by itself when people come home (`unlock_door_when_home`, default off)? Explain that it controls both parts: disabling auto relock and sending UNLOCK, when an adult or family member arrives (also from `away`, not in `night`) and in the morning after night mode. Kids and housekeepers never change the door. Without it the door only locks.
- **Vacuums:** may they start by themselves when the adults leave, also when only kids are home? Which window (`vacuum_earliest_start` to `vacuum_latest_start`)? Anything that must block them (`prevent_vacuum`)?
- **Morning and night sensors:** which sensors mean "the house is waking up" or "going to bed"? The first one that turns `on` sets the mode for the **whole house**. Two sensors of one kind: is the second a backup for the first, or in another room (for example a kid's room that should not wake the house)? Only put sensors here that should change the house mode.
- **Alarm sensors:** which sensors should notify while nobody is home, which camera belongs to each, and whether loud `alarm_media` should play for each one (`play_media: false` for outdoor sensors, for example).
- **Vacation switch:** what it means to them. Here it only blocks vacuums, starts them once when turned off, and gives `away` (alarm armed) if AppDaemon starts with it on. It does not change the mode by itself.
- **Language:** are the mode names translated? If so, the `mode_translation` app (Lightwand) must exist, and this app gets `dependencies: mode_translation`. With English names, add nothing.
- **Family mode:** do they want a separate light mode while family is home without any adult? If yes, the mode must already exist in their Lightwand rooms.
- **morning, night and holidays:** set `country_code` so that weekends and holidays give the normal mode instead of `morning`?

## Behaviour to know (do not "fix")

- **Roles:**
  - `adult` and `family` behave the same for door, vacuum and away.
  - `kid` keeps the house out of `away` and silences the alarm, but kids alone at home still get a locked door and running vacuums. Kids at home do not block the vacuum start after the vacation switch is turned off.
  - `housekeeper` silences the alarm but does not count as home for mode, door and vacuums. Unlocking the door with their `lock_user` in `away` sets `wash`.
  - `tenant` is ignored, except by `anyone_home()`.
- **Stored mode at restart:** `away`, `morning` or `night` restored from `HALightModeText` is kept until the next change. This is intended: a phone left at home does not prove someone is home, and Lightwand keeps its mode too. Do not add a re-evaluation.
- **Night modes:** only plain `night` is the whole-house night mode. At `execute_night_at` the app fires plain `night` even if a `night*` variant is active. Do not change this.
- **Presence:**
  - A tracker changing to `unavailable` or `unknown` is ignored.
  - At startup a tracker that is not `home` counts as away.
- **Old name wins:** `away_state` is the old name of `vacation` and wins when both are set.
- **Alarm sensors:**
  - A sensor changing from `unavailable`/`unknown` does not trigger. This is deliberate since 0.3.1. Ask before changing it.
  - One notification per 10 minutes. Media has its own 10 minute pause.
  - A door unlock while nobody is home pauses both for 20 seconds and never shortens a longer pause.
- **Door:**
  - Locks about 10 seconds after auto relock is enabled. Unlocks about 3 seconds after it is disabled, and only with `unlock_door_when_home`. That option gates both the unlock and disabling auto relock.
  - Only an adult or family arrival changes the door. A kid or housekeeper arriving never does, not even while an adult is home.
  - The `execute_night_at` and `execute_morning_at` fallbacks run the same night and morning actions as the sensors.
  - A person with `stopMorning` leaving during `morning` while an adult is still home only sets the normal mode.
  - The door state is tracked per topic and only changes count: after LOCK to UNLOCK the app waits 2 s for `last_unlock_user`, notifies at once if user or source changes within 10 s, otherwise after the wait. Unlocks with source `self` and the app's own UNLOCK are not notified. Do not change this to notify on every `UNLOCK` message: Zigbee2MQTT repeats the cached state.
- **Fire modes:**
  - `fire` is never stored as the mode, it only goes into `HALightModeText`.
  - `false-alarm` fires the stored mode again.
- **Room modes:** room modes like `off_kitchen` do not change the stored mode.
- **Vacuums:**
  - Start only when `docked` or `charging`, and only if the battery is above the limit. An unknown battery level still starts.
  - A vacuum found already cleaning is left alone until it docks.
  - `prevent_vacuum` uses the exact state `on`.
- **Do not edit the constants** at the top of `modeManagement.py` (pauses and delays), the role tuples, or `ALARM_STATES` unless the user asks.

## Events and methods other apps use

- `MODE_CHANGE` (name from the translations) on `HASS_namespace`, data `mode`. Fired by this app. It also listens to the same event from Lightwand, FireAlarm, Siri shortcuts and the user's automations.
- `vacuum_event` (usually `VACUUM_CONTROL`) with `action: start` or `stop`. Fired only when `vacuum_event` is set. `VacuumManager` listens to it, and HA automations may fire it too.
- `anyone_home()` (public): `True` if any person in `presence`, whatever the role, is home and not marked outside. FireAlarm (Pythm_AppdaemonApps) calls it through `get_app(<modeManagementApp>)`. Do not rename or remove it, and keep the app name matching FireAlarm's `modeManagementApp`.
- `HALightModeText` is written with the current mode. Dashboards may read it.

## Dependencies and order

- **Lightwand must be cloned** into `apps/` even without Lightwand rooms. This app imports `translations_lightmodes` from it. Without it, it fails to load.
- **Never add a name to `dependencies` that is not an app in `apps.yaml`.** It prevents that app and every app that depends on it from starting. Add `mode_translation` only if that app is configured, and `notify_mobiles` only if it is configured.
- **Without `dependencies: mode_translation`,** translated mode names depend on the order AppDaemon happens to start apps in.
- **`snapshot_directory`** needs Pythm_AppdaemonApps (`utils_apps`) cloned into `apps/`. Without it the app warns and uses the camera proxy.
- **`country_code`** needs the Python package `holidays`, and the app needs pydantic 2. With the HA add-on, list packages in `python_packages`.
- **Door lock:** the MQTT plugin must be named `MQTT` in `appdaemon.yaml`, and `MQTT_namespace` must be its namespace. Otherwise the door lock is disabled with a WARNING.
- **Vacuums:** use `vacuum:` or `vacuum_event`, never both with a `VacuumManager` for the same vacuums. Each start and stop would run twice.

## Rules for the assistant

- **Entity ids** come from the index only. Topics, playlists, lock user numbers and mode names come from the user.
- **Editing `apps.yaml`:** back it up, edit one app per change, show the block, and explain in one or two sentences what it will do.
- **Get an explicit yes before adding any part that acts alone:**
  - `MQTT_door_lock`, and separately `unlock_door_when_home`
  - `vacuum` or `vacuum_event` or the `VacuumManager` app
  - `alarm_media`
  - `turn_on_in_the_morning` and `turn_off_at_night`
- **Test door and vacuum changes** while the user is at home.
- **Do not copy this app's sensors into Lightwand rooms,** or Lightwand modes into `family`, without asking.
- **Do not commit or push** unless asked.
- **Check the log after a change:**
  - Look for `Calling initialize() for <app name>`. With translations, also `Mode translation ready. Language: ...` before it.
  - There should be no WARNING or ERROR from this app, such as `does not exist`, `Could not use presence entry`, `MQTT plugin not found`, `Not able to convert`, `has no sensor`, `holidays' is not installed`, `utils_apps ... is not installed`, `Not able to get battery level`, or `No vacuum configured` (VacuumManager).
  - There should be no `failed to start`.
