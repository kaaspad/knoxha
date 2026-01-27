# Knox Integration - Complete Issue Analysis

## Summary Table

| Issue # | Issue | Repro Steps | Root Cause (File:Line) | Fix Summary | Status |
|---------|-------|-------------|----------------------|-------------|---------|
| 1 | CSV load does nothing | Import CSV → No entities appear | `__init__.py:119` - Compares updated config against itself | Store zone IDs in hass.data before update | Not Fixed |
| 2 | New devices show ON when OFF | Add zones → Muted zones show as ON | `media_player.py:132` - Defaults to ON when no state | Fetch real state OR use None/Unknown | Not Fixed |
| 3 | State not restored after reboot | Reboot HA → All state lost | `media_player.py:63` - No RestoreEntity | Inherit RestoreEntity, implement restore logic | Not Fixed |
| 4 | Intermittent on/off | Toggle zones → 8.5% timeout rate | `connection_blocking.py` - 35 concurrent connections overwhelm device | Add connection pooling/throttling | Not Fixed |
| 5 | General bugs | Various | Multiple locations | Strict parsing, better error handling | Not Fixed |

---

## ISSUE #1: CSV Load Does Nothing Until Manual Reload

### Repro Steps:
1. Open Knox integration config
2. Choose "Import Zones from CSV"
3. Paste CSV data with 35 zones
4. Click Submit
5. **Expected**: 35 new entities appear
6. **Actual**: Nothing happens, must manually reload integration

### Root Cause:
**File**: `custom_components/knoxcham64i/__init__.py`
**Lines**: 119-120

```python
old_zones = set(zone["id"] for zone in coordinator.config_entry.data.get(CONF_ZONES, []))
new_zones = set(zone["id"] for zone in entry.data.get(CONF_ZONES, []))
```

**The Bug**:
- `coordinator.config_entry` and `entry` are the SAME object reference
- When `config_flow.py` calls `async_update_entry(entry, data=new_data)`, it updates the entry IN-PLACE
- By the time `async_reload_entry` fires, BOTH variables point to the updated data
- Therefore `old_zones == new_zones` is ALWAYS True
- System thinks "nothing changed" → logs "Only inputs changed" → no reload → no entities

**Evidence from logs**:
```
2026-01-27 08:29:16.125 INFO Only inputs changed, notifying entities without polling
```
This fires even though 35 zones were just imported via CSV.

### Proposed Fix:
Store previous zone IDs in `hass.data` before the update, or always reload when zone count changes.

```python
async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when zones change."""
    data = hass.data[DOMAIN].get(entry.entry_id)
    if not data:
        await hass.config_entries.async_reload(entry.entry_id)
        return

    # Get ACTUAL old zones from runtime data (before update)
    coordinator = data["coordinator"]
    old_zone_ids = set(coordinator.data.keys()) if coordinator.data else set()

    # Get new zones from updated entry
    new_zone_ids = set(zone["id"] for zone in entry.data.get(CONF_ZONES, []))

    if old_zone_ids != new_zone_ids:
        _LOGGER.info(f"Zones changed: {len(old_zone_ids)} → {len(new_zone_ids)}, performing full reload")
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        _LOGGER.info("Only inputs changed, notifying entities without polling")
        coordinator.async_set_updated_data(coordinator.data)
```

---

## ISSUE #2: New Devices Show ON When Actually OFF

### Repro Steps:
1. Add zones via CSV or config
2. Zones 30, 34, 35 are muted on device (OFF)
3. Integration creates entities
4. **Expected**: Entities show state=OFF
5. **Actual**: Entities show state=ON

### Root Cause:
**File**: `custom_components/knoxcham64i/media_player.py`
**Lines**: 128-139

```python
@property
def state(self) -> MediaPlayerState | None:
    """Return the state of the zone."""
    zone_state = self.coordinator.data.get(self._zone_id)
    if not zone_state:
        return MediaPlayerState.ON  # Default to ON if no data yet  ← BUG!

    # Zone is OFF if explicitly muted, otherwise ON
    if zone_state.is_muted is True:
        return MediaPlayerState.OFF
    else:
        return MediaPlayerState.ON
```

**The Bug**:
- When entities are first created, `coordinator.data` may not have zone state yet
- Code defaults to `MediaPlayerState.ON`
- But device might actually be muted/off
- Entities show incorrect state until first poll completes

**Evidence from logs**:
```
2026-01-27 08:30:14.852 DEBUG Got states: {..., 30: 'input=1, vol=4, mute=True', ...}
```
Zones 30, 34, 35 report `mute=True` but entities would default to ON.

### Proposed Fix:
Return `None` or `MediaPlayerState.IDLE` when state unknown, forcing HA to show "Unknown" until real state fetched.

```python
@property
def state(self) -> MediaPlayerState | None:
    """Return the state of the zone."""
    zone_state = self.coordinator.data.get(self._zone_id)
    if not zone_state or zone_state.is_muted is None:
        return None  # Unknown state until fetched

    return MediaPlayerState.OFF if zone_state.is_muted else MediaPlayerState.ON
```

---

## ISSUE #3: State Not Restored After HA Reboot

### Repro Steps:
1. Set zone to specific input, volume, mute state
2. Reboot Home Assistant
3. **Expected**: Entity shows last known state
4. **Actual**: All state lost, shows defaults

### Root Cause:
**File**: `custom_components/knoxcham64i/media_player.py`
**Line**: 63

```python
class ChameleonMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
```

**The Bug**:
- Class doesn't inherit from `RestoreEntity`
- No `async_added_to_hass()` implementation to restore state
- No `extra_restore_state_data` implementation to save state
- All state lost on HA restart

### Proposed Fix:
1. Inherit from `RestoreEntity`
2. Implement state restoration
3. Prefer device state over restored state when available

```python
from homeassistant.helpers.restore_state import RestoreEntity

class ChameleonMediaPlayer(CoordinatorEntity, MediaPlayerEntity, RestoreEntity):

    async def async_added_to_hass(self) -> None:
        """Restore state when added to hass."""
        await super().async_added_to_hass()

        # Try to get last state
        if (last_state := await self.async_get_last_state()) is not None:
            # Restore will be overwritten by coordinator refresh if device online
            self._attr_state = last_state.state

            if last_state.attributes:
                # Restore attributes
                pass  # Coordinator will update from device
```

---

## ISSUE #4: Intermittent On/Off (8.5% Timeout Rate)

### Repro Steps:
1. Integration polls 35 zones concurrently
2. 3 out of 35 zones timeout on first attempt
3. Retries succeed but add 5s delay each
4. **Expected**: All commands complete in ~2s
5. **Actual**: Takes 12.7s due to timeouts

### Root Cause:
**File**: `custom_components/knoxcham64i/chameleon_client/connection_blocking.py`
**Lines**: Various

**The Bug**:
- Removed lock for concurrent execution (my recent optimization)
- Now 35 connections open simultaneously to device
- HF2211A ethernet-to-serial adapter gets overwhelmed
- 8.5% failure rate (3/35 zones timeout)

**Evidence from logs**:
```
2026-01-27 08:30:11.829 WARNING Timeout on attempt 1 for command $D30
2026-01-27 08:30:11.830 WARNING Timeout on attempt 1 for command $D34
2026-01-27 08:30:11.831 WARNING Timeout on attempt 1 for command $D35
```

### Proposed Fix:
Add semaphore to limit concurrent connections (e.g., max 10 at a time).

```python
class ChameleonConnectionBlocking:
    def __init__(self, ...):
        self._connection_semaphore = asyncio.Semaphore(10)  # Max 10 concurrent

    async def send_command(self, command: str) -> str:
        async with self._connection_semaphore:  # Throttle connections
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._send_command_blocking, command)
```

---

## ISSUE #5: General Bugs

### Multiple Issues:
1. **Entity naming**: Entities created as "Unknown X" instead of zone names
2. **No strict parsing**: Invalid responses not validated
3. **Poor error messages**: Generic exceptions don't help debugging
4. **No graceful degradation**: One zone failure affects others

### Root Causes:
1. **Entity naming** - `media_player.py:92`: `self._attr_name = None` uses device name
2. **Parsing** - `client.py`: No validation of response format
3. **Errors** - Multiple files: Catch-all `except Exception`
4. **Isolation** - `client.py`: `asyncio.gather(*tasks, return_exceptions=True)` not used

### Proposed Fixes:
- Set proper entity names from zone config
- Add response validation with clear errors
- Replace generic exceptions with specific ones
- Better exception isolation in batch operations

---

## Testing Strategy Decision Point

Given the scope, I recommend:

**Option A**: Implement all 5 fixes now, verify with live device, THEN build comprehensive test suite
**Option B**: Build full test infrastructure (fake device, pytest setup) THEN fix each issue
**Option C**: Fix issues 1-2 (blocking), verify, commit, THEN address 3-5

**Estimated time**:
- Option A: 2-3 hours (fixes + verification)
- Option B: 5-6 hours (infrastructure + fixes + tests)
- Option C: 1 hour per issue (5 hours total)

**Recommendation**: Option A - Ship fixes faster, prevent test infrastructure from blocking user.

What would you prefer?
