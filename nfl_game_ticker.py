"""
NFL Game Ticker Board - Displays live, upcoming, and completed NFL games
This board shows a ticker-style display of games based on configured preferences.
"""

import logging
from datetime import datetime, time, timedelta
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


class NFLGameTickerConfig:
    """Configuration for NFL Game Ticker board."""

    def __init__(self, config_data: dict):
        # Team configuration - optional for this board
        self.team_ids = self._parse_team_ids(config_data.get("team_ids", []))

        # Display timing settings
        self.display_seconds = int(config_data.get("display_seconds", 8))
        self.refresh_seconds = int(config_data.get("refresh_seconds", 300))
        self.cache_expiration_seconds = int(config_data.get("cache_expiration_seconds", self.refresh_seconds))

        # Game display configuration
        self.show_all_games = bool(config_data.get("show_all_games", False))
        self.show_previous_games_until_time = self._parse_cutoff_time(
            config_data.get("show_previous_games_until", "06:00")
        )

        # Playoff display configuration
        self.show_upcoming_playoff_games = bool(config_data.get("show_upcoming_playoff_games", False))
        self.playoff_week = config_data.get("playoff_week", None)
        if self.playoff_week is not None:
            self.playoff_week = int(self.playoff_week)

        debug.info(f"NFL Game Ticker: Configured for teams {self.team_ids if self.team_ids else 'all'}")
        debug.info(f"NFL Game Ticker: Show all games = {self.show_all_games}")
        debug.info(f"NFL Game Ticker: Previous games cutoff = {self.show_previous_games_until_time}")
        debug.info(f"NFL Game Ticker: Show upcoming playoff games = {self.show_upcoming_playoff_games}")
        if self.playoff_week:
            debug.info(f"NFL Game Ticker: Using fixed playoff week {self.playoff_week}")

    def _parse_team_ids(self, team_ids_config) -> List[str]:
        """Parse team IDs from configuration."""
        if isinstance(team_ids_config, str):
            team_ids_config = [team_ids_config]
        if not isinstance(team_ids_config, list):
            return []
        return [str(tid).strip() for tid in team_ids_config if str(tid).strip()]

    def _parse_cutoff_time(self, time_string: str) -> time:
        """Parse cutoff time string into time object."""
        try:
            hour, minute = map(int, time_string.split(":"))
            return time(hour, minute)
        except (ValueError, AttributeError):
            debug.warning(f"NFL Game Ticker: Invalid cutoff time '{time_string}', using 06:00")
            return time(6, 0)

    def should_show_previous_game(self, game: NFLGame) -> bool:
        """Determine if a previous day's game should still be shown."""
        if not game.is_final:
            return True

        now = datetime.now()
        if not game.date:
            return False

        game_date = game.date.date()
        today = now.date()

        if game_date >= today:
            return True

        if game_date == today - timedelta(days=1):
            return now.time() < self.show_previous_games_until_time

        return False


class NFLGameTickerBoard(BoardBase):
    """NFL Game Ticker board - displays live, upcoming, and completed games."""

    def __init__(self, data, matrix, sleepEvent):
        super().__init__(data, matrix, sleepEvent)

        # Board metadata
        self.board_name = "NFL Game Ticker"
        self.board_version = __version__
        self.board_description = "NFL live game ticker and scores"

        # Initialize configuration
        try:
            self.config = NFLGameTickerConfig(self.board_config)
        except ValueError as error:
            debug.error(f"NFL Game Ticker configuration error: {error}")
            raise

        # Initialize shared data manager
        data_manager_config = {
            "refresh_seconds": self.config.refresh_seconds,
            "cache_expiration_seconds": self.config.cache_expiration_seconds,
            "team_ids": self.config.team_ids
        }
        self.data_manager = NFLDataManager.get_instance(self.data, data_manager_config)
        self.data_manager.ensure_data_loaded()

        if hasattr(self.data, 'scheduler') and self.data.scheduler:
            self.data_manager.start_refresh_scheduler(self.data.scheduler)
            debug.info(f"NFL Game Ticker: Data refresh scheduler running (every {self.config.refresh_seconds}s)")

        # Initialize logo manager
        logo_cache_dir = self._get_board_directory() / "assets/logos/nfl"
        self.logo_manager = NFLLogoManager(logo_cache_dir)

        # Display state
        self.current_games = []
        self.logo_cache: Dict[str, Image.Image] = {}
        self.logo_offsets = self._load_logo_offsets()
        self.gradient = self._load_gradient()

        debug.info("NFL Game Ticker: Initialization complete")

    def render(self):
        """Main render method - displays games in ticker style."""
        debug.debug("NFL Game Ticker: render() method called")

        try:
            self._refresh_display_games()

            if not self.current_games:
                debug.debug("NFL Game Ticker: No games available")
                #self._render_no_games_available()
                return

            # Loop through all games and display each one
            for game in self.current_games:
                if self.sleepEvent.is_set():
                    break

                # Determine if this is a playoff game that should use playoff layout
                should_use_playoff_layout = self._should_use_playoff_layout(game)

                if game.is_live:
                    self._render_live_game(game)
                elif game.is_final:
                    self._render_completed_game(game)
                elif should_use_playoff_layout:
                    # Upcoming playoff game - use playoff layout
                    self._render_playoff_matchup(game, self._get_playoff_round_name())
                else:
                    self._render_upcoming_game(game)

        except Exception as error:
            debug.error(f"NFL Game Ticker render error: {error}")
            self._render_error_display(str(error))

    def _get_snapshot(self) -> Optional[NFLDataSnapshot]:
        """Get the shared NFL data snapshot."""
        return self.data_manager.get_snapshot()

    def _should_use_playoff_layout(self, game: NFLGame) -> bool:
        """Determine if a game should be rendered using playoff layout."""
        if not self.config.show_upcoming_playoff_games:
            return False

        # Only use playoff layout for upcoming games (not live or final)
        if game.is_live or game.is_final:
            return False

        # Check if this game is in the playoff games list
        snapshot = self._get_snapshot()
        if snapshot and snapshot.playoff_games:
            return game in snapshot.playoff_games

        return False

    def _get_playoff_round_name(self) -> str:
        """Get the current playoff round name."""
        snapshot = self._get_snapshot()
        if snapshot and snapshot.playoff_round_name:
            return snapshot.playoff_round_name
        return "PLAYOFFS"

    def _refresh_display_games(self):
        """Update the list of games that should be displayed."""
        snapshot = self._get_snapshot()
        if not snapshot or not snapshot.all_teams:
            debug.warning("NFL Game Ticker: No valid data snapshot available")
            self.current_games = []
            return

        filtered_games = self._get_games_for_display(snapshot)
        self.current_games = filtered_games

        debug.debug(f"NFL Game Ticker: {len(filtered_games)} games to display")

    def _get_games_for_display(self, snapshot: NFLDataSnapshot) -> List[NFLGame]:
        """Get games that should be displayed based on configuration."""
        games_to_show = []

        # If team_ids configured, prioritize those teams
        if self.config.team_ids:
            # Always include live games involving favorite teams
            for game in snapshot.live_games:
                if any(game.involves_team(team_id) for team_id in self.config.team_ids):
                    games_to_show.append(game)

            # Include favorite team games
            for game in snapshot.favorite_team_games:
                if game not in games_to_show:
                    games_to_show.append(game)

        # Include all games if configured or no teams specified
        if self.config.show_all_games or not self.config.team_ids:
            for game in snapshot.todays_games:
                if game not in games_to_show:
                    games_to_show.append(game)

        # Include yesterday's games if before cutoff time
        current_time = datetime.now().time()
        if current_time < self.config.show_previous_games_until_time:
            for game in snapshot.yesterdays_games:
                if game not in games_to_show:
                    games_to_show.append(game)

        # Include playoff games if the feature is enabled
        if self.config.show_upcoming_playoff_games and snapshot.playoff_games:
            for game in snapshot.playoff_games:
                if game not in games_to_show:
                    games_to_show.append(game)

        # Apply additional filtering for previous games
        filtered_games = [game for game in games_to_show if self.config.should_show_previous_game(game)]

        # Sort games: live first, then by date
        filtered_games.sort(key=lambda g: (not g.is_live, g.date or datetime.min))

        return filtered_games

    def _render_live_game(self, game: NFLGame):
        """Render a live game display."""
        self.matrix.clear()
        layout = self.get_board_layout('nfl_game')

        if not layout:
            self._render_fallback_game_display(game, "LIVE")
            return

        self._render_team_display(layout, game, show_scores=True)

        # Render live game status
        live_status = self._format_live_game_status(game)
        quarter, time_str = live_status.split(" ", 1) if " " in live_status else (live_status, "")
        if hasattr(layout, 'scheduled_date'):
            self.matrix.draw_text_layout(layout.scheduled_date, quarter)
        if hasattr(layout, "scheduled_time") and time_str:
            self.matrix.draw_text_layout(layout.scheduled_time, time_str)

        self.matrix.render()
        self.sleepEvent.wait(self.config.display_seconds)

    def _render_completed_game(self, game: NFLGame):
        """Render a completed game display."""
        self.matrix.clear()
        layout = self.get_board_layout('nfl_game')

        if not layout:
            self._render_fallback_game_display(game, "FINAL")
            return

        self._render_team_display(layout, game, show_scores=True)

        if hasattr(layout, 'scheduled_date'):
            self.matrix.draw_text_layout(layout.scheduled_date, "FINAL")

        self.matrix.render()
        self.sleepEvent.wait(self.config.display_seconds)

    def _render_upcoming_game(self, game: NFLGame):
        """Render an upcoming game display."""
        self.matrix.clear()
        layout = self.get_board_layout('nfl_game')

        if not layout:
            self._render_fallback_game_display(game, self._format_game_datetime(game))
            return

        self._render_team_display(layout, game, show_scores=False)

        if hasattr(layout, 'scheduled_date'):
            self.matrix.draw_text_layout(layout.scheduled_date, "TODAY")
        if hasattr(layout, "scheduled_time"):
            self.matrix.draw_text_layout(
                layout.scheduled_time,
                self._format_game_datetime(game, format_type="time_only")
            )

        if hasattr(layout, "VS"):
            self.matrix.draw_text_layout(layout.VS, "VS")

        self.matrix.render()
        self.sleepEvent.wait(self.config.display_seconds)

    def _render_playoff_matchup(self, game: NFLGame, round_name: str):
        """Render a playoff matchup using the playoff board style."""
        self.matrix.clear()
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
            # Remove period from "Conf. Champ."
            round_name = round_name.replace(".", "")
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
            time_text = self._format_playoff_game_datetime(game)
            time_layout = layout.playoff_game_start_time

            # Get font and measure text
            font = time_layout.font
            bbox = font.getbbox(time_text)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # Create gradient background
            fade_width = 8
            bg_gradient = self._create_text_background_gradient(text_width, text_height, fade_width)

            # Draw gradient and text
            self.matrix.draw_image_layout(time_layout, bg_gradient)
            self.matrix.draw_text_layout(time_layout, time_text)

        self.matrix.render()
        self.sleepEvent.wait(self.config.display_seconds)

    def _format_playoff_game_datetime(self, game: Optional[NFLGame]) -> str:
        """Format game date and time for playoff display (e.g., 'SUN 3:00 PM')."""
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

    def _render_team_display(self, layout, game: NFLGame, show_scores: bool):
        """Render team information (logos, names, scores/records)."""
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
        self.matrix.draw_image([self.matrix.width/2,0], self.gradient, align="center")

        # Render scores or records
        if show_scores:
            if hasattr(layout, 'score'):
                self.matrix.draw_text_layout(layout.score, str(f"{game.away_score}-{game.home_score}"))
        else:
            if hasattr(layout, 'away_team_score'):
                self.matrix.draw_text_layout(layout.away_team_score, game.away_team.record_text)
            if hasattr(layout, 'home_team_score'):
                self.matrix.draw_text_layout(layout.home_team_score, game.home_team.record_text)

    def _render_no_games_available(self):
        """Render display when no games are available."""
        self.matrix.clear()
        layout = self.get_board_layout('nfl_game')

        if layout and hasattr(layout, 'game_status'):
            self.matrix.draw_text_layout(layout.game_status, "No Games Today")
        else:
            font = self.data.config.layout.font
            self.matrix.draw_text_centered(self.display_height // 2, "No Games Today", font)

        self.matrix.render()
        self.sleepEvent.wait(self.config.display_seconds)

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

    def _render_fallback_game_display(self, game: NFLGame, status_text: str):
        """Render game information when no layout is available."""
        font = self.data.config.layout.font
        away_text = f"{game.away_team.abbreviation} {game.away_score}"
        home_text = f"{game.home_team.abbreviation} {game.home_score}"

        self.matrix.draw_text_centered(15, away_text, font)
        self.matrix.draw_text_centered(25, "vs", font)
        self.matrix.draw_text_centered(35, home_text, font)
        self.matrix.draw_text_centered(50, status_text, font)
        self.matrix.render()
        self.sleepEvent.wait(self.config.display_seconds)

    def _format_live_game_status(self, game: NFLGame) -> str:
        """Format status text for live games."""
        if game.quarter in ["1", "2", "3", "4"]:
            quarter_suffix = {"1": "ST", "2": "ND", "3": "RD", "4": "TH"}.get(game.quarter, "TH")
            quarter_text = f"{game.quarter}{quarter_suffix}"
        else:
            quarter_text = f"Q{game.quarter}" if game.quarter else "LIVE"

        if game.quarter and game.time_remaining:
            return f"{quarter_text} {game.time_remaining}"
        elif game.quarter:
            return f"{quarter_text}"
        else:
            return "LIVE"

    def _format_game_datetime(self, game: Optional[NFLGame], format_type: str = "full") -> str:
        """Format game date and time for display."""
        if not game or not game.date:
            return "TBD"
        local_dt = game.date.astimezone()

        if format_type == "time_only":
            hour = local_dt.hour % 12 or 12
            minute = local_dt.minute
            ampm = "AM" if local_dt.hour < 12 else "PM"
            return f"{hour}:{minute:02d} {ampm}"
        elif format_type == "date_only":
            return f"{local_dt.strftime('%a')} {local_dt.month}/{local_dt.day}"
        else:  # "full"
            weekday = local_dt.strftime("%a")
            hour = local_dt.hour % 12 or 12
            minute = local_dt.minute
            ampm = "AM" if local_dt.hour < 12 else "PM"
            return f"{weekday} {local_dt.month}/{local_dt.day} {hour}:{minute:02d} {ampm}"

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
            debug.error(f"NFL Game Ticker: Failed to load logo for {team.abbreviation}: {error}")

        return None

    def _draw_logo(self, layout, element_name: str, logo: Image, team_abbreviation: str):
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
            debug.error(f"NFL Game Ticker: Failed to load image offsets: {error}")

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

    def cleanup(self):
        """Clean up resources when board is unloaded."""
        debug.info("NFL Game Ticker: Cleaning up resources")
        NFLDataManager.release_instance()
        self.logo_cache.clear()
        self.current_games.clear()
        super().cleanup()
        debug.info("NFL Game Ticker: Cleanup complete")
