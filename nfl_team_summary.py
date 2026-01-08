"""
NFL Team Summary Board
This is an alias for NFLBoard to support the new naming convention.
The old 'nfl_board' name continues to work for backward compatibility.
"""

# Import the original NFLBoard class with a new name
from .board import NFLBoard as NFLTeamSummaryBoard

# Re-export for use by the plugin system
__all__ = ['NFLTeamSummaryBoard']
