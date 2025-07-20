"""Constants for the Knox Chameleon64i integration."""

DOMAIN = "knoxcham64i"

DEFAULT_PORT = 8899
DEFAULT_NAME = "Knox Chameleon64i"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_ZONES = "zones"
CONF_INPUTS = "inputs"

# Zone configuration
CONF_ZONE_NAME = "name"
CONF_ZONE_ID = "id"

# Input configuration
CONF_INPUT_NAME = "name"
CONF_INPUT_ID = "id"

# Default zone names
DEFAULT_ZONE_NAMES = {
    1: "Zone 1",
    2: "Zone 2",
    # ... add all zones up to 64
    64: "Zone 64"
}

# Default input names
DEFAULT_INPUT_NAMES = {
    1: "Input 1",
    2: "Input 2",
    # ... add all inputs
    64: "Input 64"
}

DEFAULT_INPUT = {"id": 1, "name": "Default Input"} 