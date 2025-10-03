"""
NFL Board to show basic info about your favorite team
"""

# Board metadata using standard Python package conventions
__plugin_id__ = "nfl_board"  # Canonical folder name for installation
__version__ = "1.0.0"
__description__ = "NFL Team Board"
__board_name__ = "NFL Board"
__author__ = "NHL LED Scoreboard"

# Board requirements (optional)
__requirements__ = []

# Minimum application version required (optional)
__min_app_version__ = "1.0.0"

# Files to preserve during plugin updates/removals (optional)
# The plugin manager will preserve these files when updating or removing with --keep-config
# Supports glob patterns like *.csv, data/*, custom_*
# Default if not specified: ["config.json", "*.csv", "data/*", "custom_*"]
__preserve_files__ = [
    "config.json",
    "logo_offsets.json",
    # Add other user-modifiable files here, e.g.:
    # "custom_data.csv",
    # "data/*.json",
]
