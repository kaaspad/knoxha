# Knox Chameleon64i Home Assistant Integration

## Project Overview
Home Assistant custom integration for controlling Knox Chameleon64i video routing switchers via ethernet-to-serial adapters.

## Development Guidelines

### Commit Standards
- Always commit changes after completing tasks
- Use descriptive commit messages that explain the "why" not just "what"  
- Include Claude Code signature in all commits
- Batch related changes into logical commits

### Testing Commands
- **Lint**: `python3 -m py_compile *.py` (check syntax)
- **Debug Services**: Use the knox_* services for testing device communication
- **Volume Test**: `knox_test_volume_conversion` service validates HA↔Knox scaling

### Knox API Details
- **Inputs**: Numbered 1-64 (confirmed from manual)
- **Zones**: Numbered 1-64  
- **Volume**: Knox uses 0-63 (0=loudest, 63=quietest), HA uses 0.0-1.0 (0=quietest, 1=loudest)
- **Communication**: TCP port 8899 via ethernet-to-serial adapter
- **Commands**: ASCII strings with \r terminator (e.g., "B0102\r" for zone 1 input 2)

### Architecture
- `pyknox/`: Knox device communication library
- `media_player.py`: Home Assistant media player entity
- `config_flow.py`: Configuration UI (zones/inputs setup)
- `services.yaml`: Debug and testing services

### Recent Fixes
- ✅ Input 1 now available in configuration dropdown
- ✅ Fixed HA 2025.12 deprecation warning in config flow
- ✅ Added comprehensive debug logging and testing services
- ✅ Confirmed API input indexing starts from 1 (not 2)

## Auto-Commit Setup
Claude Code should automatically commit changes. If manual commits are needed:

```bash
# Use git alias (already configured):
git claude-commit "Your commit message here"

# Or use the shell function:
source ./claude-commit.sh
claude-commit "Your commit message here"
```

## Debug Services Available
1. `knox_debug_command` - Send raw commands
2. `knox_test_all_functions` - Test all device operations  
3. `knox_get_device_info` - Get device state and config
4. `knox_start_debug_polling` - Monitor state changes
5. `knox_stop_debug_polling` - Stop monitoring
6. `knox_test_volume_conversion` - Test volume scaling