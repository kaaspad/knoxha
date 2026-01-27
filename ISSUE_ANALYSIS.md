# Knox Integration - Issue Analysis from Logs

## Timestamp: 2026-01-27 08:28:33 - 08:30:14

### Critical Errors/Warnings Found:

1. **08:30:11.829-831 WARNING - Timeout on 3 zones (8.5% failure rate)**
   ```
   WARNING (SyncWorker_29) Timeout on attempt 1 for command $D30
   WARNING (SyncWorker_33) Timeout on attempt 1 for command $D34
   WARNING (SyncWorker_34) Timeout on attempt 1 for command $D35
   ```
   - **Impact**: Intermittent on/off failures, 3/35 zones timeout
   - **Root Cause**: Race condition or device overload with 35 concurrent connections

2. **08:29:16.125 INFO - Wrong async_reload_entry logic**
   ```
   Only inputs changed, notifying entities without polling
   ```
   - **Impact**: CSV zone imports don't create entities immediately
   - **Root Cause**: async_reload_entry incorrectly detects zone changes vs input changes
   - **File**: __init__.py:109-124

3. **08:30:14.852 DEBUG - Wrong initial state (mute=True zones show as ON)**
   ```
   30: 'input=1, vol=4, mute=True'
   34: 'input=2, vol=4, mute=True'
   35: 'input=1, vol=4, mute=True'
   ```
   - **Impact**: Entities show ON when device is actually OFF (muted)
   - **Root Cause**: media_player.py:132 defaults to ON when no zone_state
   - **File**: media_player.py:128-139

4. **08:30:14.853+ INFO - Entity names show as "Unknown X"**
   ```
   Registered new media_player.knoxcham64i entity: media_player.unknown_1
   Registered new media_player.knoxcham64i entity: media_player.unknown_2
   ```
   - **Impact**: CSV zone names not applied to entities
   - **Root Cause**: Entity name set to None, device name used instead
   - **File**: media_player.py:92

5. **No RestoreEntity implementation**
   - **Impact**: State not remembered after HA reboot
   - **Root Cause**: ChameleonMediaPlayer doesn't inherit RestoreEntity
   - **File**: media_player.py:63

### Timeline of Events:

```
08:28:33 - Integration setup starts, no zones configured
08:29:16 - Input change detected, but entities NOT created (CSV import?)
08:30:02 - Manual reload triggers full zone poll
08:30:06 - 35 zones poll concurrently (good - concurrent optimization working)
08:30:07 - 32 zones complete successfully in ~1s
08:30:11 - 3 zones timeout after 5s, retry initiated
08:30:14 - All 35 zones complete after 12.7s total (should be ~2s)
08:30:14 - Entities registered with wrong names ("Unknown X")
```

### Performance Analysis:
- **Expected**: 35 zones × 1s concurrent = ~2s total
- **Actual**: 12.7s total (6x slower than expected)
- **Cause**: 3 zones timing out (5s each) + retries serializing the batch

### State Consistency Issues:
- Zones 30, 34, 35 report `mute=True` but entities show `state=ON`
- No state restoration after reboot
- Entity names don't match CSV import
