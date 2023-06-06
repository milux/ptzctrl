# The frontend web page title for clients
WEB_TITLE = "MEINE KIRCHE Regensburg | PTZ Control"
# These two values are used for database initialization
# Provide only the number of cameras with actual PTZ capabilities and a sensible number of buttons
NUM_CAMERAS = 3
NUM_BUTTONS = 18
# You may add additional cameras here, which will only receive global focus/power commands
# However, you MUST put the "real" PTZ cameras first!
CAMERA_IPS = ['10.1.0.31', '10.1.0.32', '10.1.0.33', '10.1.0.34']
VISCA_UDP_PORT = 1259
VISCA_MEMORY_SPEED = 0x18
# The order of these IDs must match the order of CAMERA_IPS w.r.t. your ATEM controller
# Leave empty to disable on air change protection
TALLY_IDS = [4, 5, 3]
TALLY_HOST = "pi.mk"
TALLY_PORT = 7411
# Frequency used for doing a ping-pong to check if tally connection is alive
TALLY_KEEPALIVE_FREQUENCY = 10.0
# The place where to expect/create the SQLite database for button data
DB_FILE = "db/db.sqlite"
# Timeout for most camera operations
VISCA_TIMEOUT = 5.0
# Timeout for recall operations
RECALL_TIMEOUT = 20.0
