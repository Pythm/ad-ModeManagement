# Wall switches and remotes with ModeManagement: notes for an AI assistant

Read this with [LLM.md](LLM.md) and [README.md](README.md). Use it when the user wants a button, wall switch or remote in a room to also move the **whole house** through the day: from night to morning or normal, to a bedroom night mode in the evening, and to night. The user writes (or you write for them) a small AppDaemon app per controller. ModeManagement does not read buttons itself.

## The day cycle a controller follows

The house goes `night` → `morning` → normal (`automagical`, or the `family` mode) → bedroom night (`night<Room>`) → `night`. A room button may move the house one step forward. It never moves the house back to night in the morning, and it never touches the door.

Example from a working setup (a kid's room, two buttons, Lightwand room app `lys-kid`):

| Press | When | House mode | Fires |
|---|---|---|---|
| ON | 06:35-12:00 | any night mode (starts with the night word) | `reset_lys-kid`, then 2 s later the house wake mode from `wake_mode()` |
| ON | 21:00-06:35 | plain `night` | a dim light mode (`nightlight`), back to `night` after 15 min if nothing else changed the mode |
| ON | otherwise | | `reset_lys-kid` (room only) |
| OFF | 06:50-20:00 | | `off_lys-kid` (room only) |
| OFF | 20:00-06:50 | | `nightKid` (bedroom night: the house is going to bed, this room sleeps) |
| double press | any | | toggles a lamp, no mode |

The times are the user's. Ask for them, and suggest the ModeManagement times (`morning_start_listen_time`, `morning_to_normal`, `night_start_listen_time`) as a start.

## What ModeManagement does with the modes a controller fires

So the controller does not repeat it:

- **A whole-house mode starting with the night word** (`night`, `nightKid`, `nightlight`) between `night_start_listen_time` and `execute_night_at`: turns off `turn_off_at_night` and locks the door. From `execute_night_at` until `morning_start_listen_time` it only locks the door (it never unlocks). At `execute_night_at` it fires plain `night` if the house is in a night variant.
- **`morning` or normal after night** (between `morning_start_listen_time` and `execute_morning_at`): the mode is set for the whole house and `turn_on_in_the_morning` goes on. With `morning_sensors` configured the door is **not** unlocked by the mode: the first morning sensor unlocks it (opt-in `unlock_door_when_home`). Lightwand keeps rooms where people are still in bed in their own mode.
- **The first morning sensor** sets the wake mode only if the house is still in a night mode (a mode a button has set is kept), and unlocks the door if the house has been in night since the last unlock.
- **Room modes** (`<mode>_<room>`, for example `off_lys-kid`, `reset_lys-kid`) never change the house mode, and never change the door.
- **`reset`** (without a room) stores the normal mode. **`away`** arms the alarm and locks the door.

## Rules for the code

1. **Mode names come from the translations, never as English text.** `from translations_lightmodes import translations`, then `translations.morning`, `translations.automagical`, `translations.night`, `translations.off`, `translations.reset` and `translations.MODE_CHANGE`. A user with translated names (Norwegian: `morgen`, `automagisk`, `natt`, `av`) would otherwise get a mode nobody knows. ModeManagement then stores it as the house mode, the house is no longer in night, and the morning unlock is skipped. This happened. Only the user's own custom names (`nightlight`, `nightKid`) are written as text, and they must not contain `_`.
2. **Ask ModeManagement, do not copy its rules.** `mm = self.ADapi.get_app(<ModeManagement app name>)`:
   - `mm.current_mode`: the house mode (correct after a restart, room modes already filtered out).
   - `mm.wake_mode()`: `morning` on workdays until `morning_to_normal`, else the normal mode (holidays with `country_code`, the `family` mode). Do not use a separate workday sensor.
   - Keep a fallback when `get_app` returns None (track `MODE_CHANGE` yourself and ignore modes that contain `_`).
3. **Night is `mode.startswith(translations.night)`,** never `==`, except where the table above says plain `night`.
4. **Never lock, unlock or publish to a door lock, and never fire `away`** from a controller. ModeManagement owns the door.
5. **Delayed modes:** store the timer handle, cancel it when another house mode arrives, and check that the mode is still the one you set before firing (`nightlight` → `night` must not send a woken house back to night).
6. **Room modes are `<mode>_<room>`** with the Lightwand room app name after the `_`.
7. **Fire and listen in the same namespace** (`HASS_namespace`, default `default`).
8. **Portable style:** `ADBase` with `self.ADapi`, every entity id and the ModeManagement app name from `apps.yaml`, `dependencies` only on apps that exist.

## ALWAYS ask the user

- Which device, and how a press shows up in Home Assistant: a Z-Wave `event.*` entity (attribute `value`: 0 single, 2 double...), a Zigbee2MQTT `action` on an MQTT topic, or a `zha_event`. Look it up in the index, then ask which press does what.
- The Lightwand room app name of the room the controller is in.
- Each time window, and whether a press in the morning should wake the whole house or only the room.
- The name of the bedroom night mode and of a dim night light mode (if any), and how long the night light lasts. The names must exist in their Lightwand rooms.
- The name of the ModeManagement app in `apps.yaml`.

## Skeleton (ADBase, Z-Wave scene event entities)

```python
""" Room controller that also moves the house through the day. See ad-ModeManagement/LLM_CONTROLLERS.md """
from appdaemon import adbase as ad

from translations_lightmodes import translations


class RoomController(ad.ADBase):

    def initialize(self):
        self.ADapi = self.get_ad_api()
        self.HASS_namespace = self.args.get('HASS_namespace', 'default')
        self.room = self.args['room']                          # Lightwand room app name
        self.mode_app = self.args.get('mode_app', 'manageModes')
        self.bedroom_night = self.args['bedroom_night_mode']   # starts with the night word, no '_'
        self.night_light = self.args.get('night_light_mode')   # optional
        self.night_light_seconds = int(self.args.get('night_light_seconds', 900))
        self.tracked_mode = ''
        self.night_timer = None
        self.ADapi.listen_state(self.on_pressed, self.args['on_button'], namespace = self.HASS_namespace)
        self.ADapi.listen_state(self.off_pressed, self.args['off_button'], namespace = self.HASS_namespace)
        self.ADapi.listen_event(self.mode_event, translations.MODE_CHANGE, namespace = self.HASS_namespace)

    def mode_event(self, event_name, data, **kwargs):
        mode = data.get('mode')
        if not isinstance(mode, str) or '_' in mode:
            return  # room modes do not change the house mode
        self.tracked_mode = mode
        if mode != self.night_light:
            self._cancel_night_timer()

    def on_pressed(self, entity, attribute, old, new, **kwargs):
        if self.ADapi.get_state(entity, attribute = 'value', namespace = self.HASS_namespace) != 0:
            return
        house = self._house_mode()
        if house.startswith(translations.night) and self.ADapi.now_is_between('06:35:00', '12:00:00'):
            self._cancel_night_timer()
            self._fire(f"{translations.reset}_{self.room}")
            self.ADapi.run_in(self._fire_later, 2, mode = self._wake_mode())
        elif house == translations.night:
            if self.night_light and self.ADapi.now_is_between('21:00:00', '06:35:00'):
                self._fire(self.night_light)
                self._cancel_night_timer()
                self.night_timer = self.ADapi.run_in(self._back_to_night, self.night_light_seconds)
        else:
            self._fire(f"{translations.reset}_{self.room}")

    def off_pressed(self, entity, attribute, old, new, **kwargs):
        if self.ADapi.get_state(entity, attribute = 'value', namespace = self.HASS_namespace) != 0:
            return
        if self.ADapi.now_is_between('06:50:00', '20:00:00'):
            self._fire(f"{translations.off}_{self.room}")
        else:
            self._fire(self.bedroom_night)

    def _fire(self, mode):
        self.ADapi.fire_event(translations.MODE_CHANGE, mode = mode, namespace = self.HASS_namespace)

    def _fire_later(self, **kwargs):
        self._fire(kwargs['mode'])

    def _back_to_night(self, **kwargs):
        self.night_timer = None
        if self._house_mode() == self.night_light:
            self._fire(translations.night)

    def _cancel_night_timer(self):
        if self.night_timer is not None:
            self.ADapi.cancel_timer(self.night_timer, silent = True)
            self.night_timer = None

    def _house_mode(self):
        mm = self.ADapi.get_app(self.mode_app)
        mode = getattr(mm, 'current_mode', None) if mm is not None else None
        return mode if isinstance(mode, str) else self.tracked_mode

    def _wake_mode(self):
        mm = self.ADapi.get_app(self.mode_app)
        if mm is not None and hasattr(mm, 'wake_mode'):
            return mm.wake_mode()
        return translations.automagical
```

```yaml
kid_switch:
  module: room_controller
  class: RoomController
  dependencies:
    - mode_translation        # only if that app exists
  room: lys-kid
  mode_app: manageModes
  on_button: event.kid_switch_scene_002
  off_button: event.kid_switch_scene_001
  bedroom_night_mode: nightKid
  night_light_mode: nightlight   # optional
  night_light_seconds: 900
```

The times in the skeleton are the example's. Make them args if the user wants to change them.

## Test before handing over

- Every row of the table: press at a time inside and outside each window, with the house in `night`, a night variant, `morning`, normal and `away`. Check the `MODE_CHANGE` values in the log.
- A press in the morning sets the house mode but sends no door command. The first morning sensor afterwards unlocks (with `unlock_door_when_home`).
- After an AppDaemon restart during the night, a morning press still wakes the house (the mode comes from ModeManagement).
- The night light goes back to night only if nothing else changed the mode.
