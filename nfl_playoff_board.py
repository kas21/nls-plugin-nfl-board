"""
NFL Playoff Board - Displays upcoming NFL playoff matchups in ticker style
Shows the round title, team logos, VS, day of week, start time, and records.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from boards.base_board import BoardBase
from PIL import Image
from utils import get_file

from . import __version__
from .data import NFLDataManager, NFLDataSnapshot, NFLGame, NFLTeam
from .logos import NFLLogoManager

debug = logging.getLogger("scoreboard")

# NFL games are scheduled in US Eastern Time
NFL_TIMEZONE = ZoneInfo("America/New_York")


class NFLPlayoffConfig:
    """Configuration for NFL Playoff board."""

    def __init__(self, config_data: dict):
        # Display timing settings
        self.display_seconds = int(config_data.get("display_seconds", 8))
        self.refresh_seconds = int(config_data.get("refresh_seconds", 300))
        self.cache_expiration_seconds = int(config_data.get("cache_expiration_seconds", self.refresh_seconds))

        # Optional: specific week override (auto-detect by default)
        self.playoff_week = config_data.get("playoff_week", None)
        if self.playoff_week is not None:
            self.playoff_week = int(self.playoff_week)

        debug.info(f"NFL Playoff Board: Configured with display_seconds={self.display_seconds}")
        if self.playoff_week:
            debug.info(f"NFL Playoff Board: Using fixed playoff week {self.playoff_week}")
        else:
            debug.info("NFL Playoff Board: Auto-detecting playoff week")


class NFLPlayoffBoard(BoardBase):
    """NFL Playoff board - displays upcoming playoff matchups in ticker style."""

    def __init__(self, data, matrix, sleepEvent):
        super().__init__(data, matrix, sleepEvent)

        # Board metadata
        self.board_name = "NFL Playoffs"
        self.board_version = __version__
        self.board_description = "NFL playoff matchup ticker"

        # Initialize configuration
        try:
            self.config = NFLPlayoffConfig(self.board_config)
        except ValueError as error:
            debug.error(f"NFL Playoff Board configuration error: {error}")
            raise

        # Initialize shared data manager (singleton pattern)
        data_manager_config = {
            "refresh_seconds": self.config.refresh_seconds,
            "cache_expiration_seconds": self.config.cache_expiration_seconds,
            "team_ids": []  # Playoff board shows all teams
        }
        self.data_manager = NFLDataManager.get_instance(data, data_manager_config)
        self.data_manager.ensure_data_loaded()

        # Start refresh scheduler
        if hasattr(data, 'scheduler') and data.scheduler:
            self.data_manager.start_refresh_scheduler(data.scheduler)
            debug.info(f"NFL Playoff Board: Data refresh scheduler running (every {self.config.refresh_seconds}s)")

        # Initialize logo manager and caches
        logo_cache_dir = self._get_board_directory() / "assets/logos/nfl"
        self.logo_manager = NFLLogoManager(logo_cache_dir)
        self.logo_cache: Dict[str, Image.Image] = {}
        self.logo_offsets = self._load_logo_offsets()
        self.gradient = self._load_gradient()

        debug.info("NFL Playoff Board: Initialization complete")

    def render(self):
        """Main render method - displays playoff matchups in ticker style."""
        debug.debug("NFL Playoff Board: render() method called")

        try:
            snapshot = self._get_snapshot()
            if not snapshot or not snapshot.playoff_games:
                # No playoff games - silently return (off-season or no games)
                debug.debug("NFL Playoff Board: No playoff games available")
                return

            # Filter to only upcoming games (not live or completed - those are shown by game ticker)
            upcoming_games = [g for g in snapshot.playoff_games if not g.is_live and not g.is_final]

            if not upcoming_games:
                debug.debug("NFL Playoff Board: No upcoming playoff games to display")
                return

            debug.debug(f"NFL Playoff Board: Displaying {len(upcoming_games)} upcoming games for {snapshot.playoff_round_name}")

            # Loop through games in ticker style
            for game in upcoming_games:
                if self.sleepEvent.is_set():
                    break

                self.matrix.clear()
                self._render_playoff_matchup(game, snapshot.playoff_round_name)
                self.matrix.render()
                self.sleepEvent.wait(self.config.display_seconds)

        except Exception as error:
            debug.error(f"NFL Playoff Board render error: {error}")
            self._render_error_display(str(error))

    def _get_snapshot(self) -> Optional[NFLDataSnapshot]:
        """Get the shared NFL data snapshot."""
        return self.data_manager.get_snapshot()

    def _render_playoff_matchup(self, game: NFLGame, round_name: str):
        """
        Render a single playoff matchup.
        """
        layout = self.get_board_layout('nfl_game')

        # Render team logos
        if hasattr(layout, 'away_team_logo'):
            away_logo = self._get_team_logo(game.away_team)
            if away_logo:
                self._draw_logo(layout, "away_team_logo", away_logo, game.away_team.abbreviation)

        if hasattr(layout, 'home_team_logo'):
            home_logo = self._get_team_logo(game.home_team)
            if home_logo:
                self._draw_logo(layout, "home_team_logo", home_logo, game.home_team.abbreviation)

        # Render gradient
        self.matrix.draw_image([self.matrix.width / 2, 0], self.gradient, align="center")

        # Render round name at top
        if hasattr(layout, 'playoff_round_name'):
            self.matrix.draw_text_layout(layout.playoff_round_name, round_name.upper())

        # Render "VS" in center
        if hasattr(layout, 'VS'):
            self.matrix.draw_text_layout(layout.VS, "VS")

        # Render team records
        if hasattr(layout, 'away_team_score'):
            self.matrix.draw_text_layout(layout.away_team_score, game.away_team.record_text)
        if hasattr(layout, 'home_team_score'):
            self.matrix.draw_text_layout(layout.home_team_score, game.home_team.record_text)

        # Render game day/time with gradient background
        if hasattr(layout, 'playoff_game_start_time'):
            time_text = self._format_game_datetime(game)
            time_layout = layout.playoff_game_start_time

            # Get font and measure text
            font = time_layout.font
            bbox = font.getbbox(time_text)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # Create gradient background
            fade_width = 8
            bg_gradient = self._create_text_background_gradient(text_width, text_height, fade_width)

            # Draw gradient centered at text position (offset by fade_width)
            text_x, text_y = time_layout.position
            #self.matrix.draw_image((text_x - fade_width, text_y), bg_gradient)
            self.matrix.draw_image_layout(time_layout, bg_gradient)

            # Draw text on top
            self.matrix.draw_text_layout(time_layout, time_text)

    def _format_game_datetime(self, game: Optional[NFLGame]) -> str:
        """Format game date and time for display (e.g., 'SUN 3:00 PM')."""
        if not game or not game.date:
            return "TBD"

        local_dt = game.date.astimezone()
        weekday = local_dt.strftime("%a").upper()
        hour = local_dt.hour % 12 or 12
        minute = local_dt.minute
        ampm = "AM" if local_dt.hour < 12 else "PM"

        return f"{weekday} {hour}:{minute:02d} {ampm}"

    def _create_text_background_gradient(self, text_width: int, text_height: int, fade_width: int = 10) -> Image.Image:
        """
        Create a gradient background for text: black in the middle with fades on left/right edges.

        Args:
            text_width: Width of the text in pixels
            text_height: Height of the text in pixels
            fade_width: Width of the fade effect on each side

        Returns:
            RGBA Image with gradient
        """
        total_width = text_width + (fade_width * 2)
        img = Image.new('RGBA', (total_width, text_height), (0, 0, 0, 0))

        for x in range(total_width):
            if x < fade_width:
                # Left fade: transparent → black
                alpha = int(255 * (x / fade_width))
            elif x >= total_width - fade_width:
                # Right fade: black → transparent
                alpha = int(255 * ((total_width - x) / fade_width))
            else:
                # Middle: solid black
                alpha = 255

            for y in range(text_height):
                img.putpixel((x, y), (0, 0, 0, alpha))

        return img

    def _get_team_logo(self, team: NFLTeam) -> Optional[Image.Image]:
        """Get team logo image with caching."""
        cache_key = f"{team.abbreviation}_logo"

        if cache_key in self.logo_cache:
            return self.logo_cache[cache_key]

        try:
            logo_path = self.logo_manager.get_team_logo_path(team, size=128, download_if_missing=True)
            if logo_path and logo_path.exists():
                logo_image = Image.open(logo_path)
                self.logo_cache[cache_key] = logo_image
                return logo_image
        except Exception as error:
            debug.error(f"NFL Playoff Board: Failed to load logo for {team.abbreviation}: {error}")

        return None

    def _draw_logo(self, layout, element_name: str, logo: Image.Image, team_abbreviation: str):
        """Draw a team logo using element-specific offsets."""
        if not hasattr(layout, element_name) or not logo:
            return

        offsets = self._get_logo_offsets(team_abbreviation, element_name)
        zoom = float(offsets.get("zoom", 1.0))
        offset_x, offset_y = offsets.get("offset", (0, 0))

        max_dimension = 64 if self.matrix.height >= 48 else min(32, self.matrix.height)
        if max(logo.size) > max_dimension:
            logo.thumbnail((max_dimension, max_dimension), self._thumbnail_filter())

        if zoom != 1.0:
            w, h = logo.size
            zoomed = logo.resize(
                (max(1, int(round(w * zoom))), max(1, int(round(h * zoom)))),
                self._thumbnail_filter(),
            )
            logo = zoomed

        element = getattr(layout, element_name).__copy__()
        x, y = element.position
        element.position = (x + offset_x, y + offset_y)
        self.matrix.draw_image_layout(element, logo)

    @staticmethod
    def _thumbnail_filter():
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
        if resampling is None:
            resampling = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
        return resampling

    def _get_logo_offsets(self, team_abbreviation: str, element_name: str) -> dict:
        """Get logo offsets for a team and element."""
        team_offsets = self.logo_offsets.get(team_abbreviation.upper())

        if isinstance(team_offsets, dict):
            if element_name in team_offsets:
                return team_offsets[element_name]
            if "_default" in team_offsets:
                return team_offsets["_default"]

        return self.logo_offsets.get("_default", {"zoom": 1.0, "offset": (0, 0)})

    def _load_logo_offsets(self) -> Dict[str, Dict[str, any]]:
        """Load logo positioning offsets from configuration file."""
        try:
            offsets_path = self._get_board_directory() / "logo_offsets.json"
            if offsets_path.exists():
                import json
                with offsets_path.open() as file:
                    raw_offsets = json.load(file)

                default_offset = raw_offsets.get("_default", {"zoom": 1.0, "offset": (0, 0)})
                processed_offsets = {}

                for key, value in raw_offsets.items():
                    if key != "_default":
                        processed_offsets[key.upper()] = {**default_offset, **value}

                processed_offsets["_default"] = default_offset
                return processed_offsets
        except Exception as error:
            debug.error(f"NFL Playoff Board: Failed to load image offsets: {error}")

        return {"_default": {"zoom": 1.0, "offset": (0, 0)}}

    def _load_gradient(self) -> Image.Image:
        """Load appropriate gradient image for current matrix size."""
        if self.matrix.height >= 48:
            return Image.open(get_file('assets/images/128x64_scoreboard_center_gradient.png'))
        else:
            return Image.open(get_file('assets/images/64x32_scoreboard_center_gradient.png'))

    def _get_board_directory(self) -> Path:
        """Get the directory path for this board plugin."""
        return Path(__file__).parent

    def _render_error_display(self, error_message: str):
        """Render error message display."""
        self.matrix.clear()
        layout = self.get_board_layout('nfl')

        if layout and hasattr(layout, 'game_status'):
            self.matrix.draw_text_layout(layout.game_status, "NFL Error")
        else:
            font = self.data.config.layout.font
            self.matrix.draw_text_centered(self.display_height // 2, "NFL Error", font)

        self.matrix.render()
        self.sleepEvent.wait(self.config.display_seconds)

    def cleanup(self):
        """Clean up resources when board is unloaded."""
        debug.info("NFL Playoff Board: Cleaning up resources")
        NFLDataManager.release_instance()
        self.logo_cache.clear()
        super().cleanup()
        debug.info("NFL Playoff Board: Cleanup complete")
