import logging
from pathlib import Path

from typing import List, Optional

from boards.base_board import BoardBase
from PIL import Image, ImageDraw
from utils import get_file

from . import __board_name__, __description__, __version__
from .data import NFLDataSnapshot, NFLTeam, NFLDataManager

debug = logging.getLogger("scoreboard")

class NFLStandingsBoard(BoardBase):
    """
    NFL Standings board module that displays the current NFL standings.
    Now works independently without requiring NFLBoard to be enabled.
    """

    def __init__(self, data, matrix, sleepEvent):
        super().__init__(data, matrix, sleepEvent)

        # Board metadata from package
        self.board_name = __board_name__
        self.board_version = __version__
        self.board_description = __description__

        # Load config with automatic priority: central config -> board config -> defaults
        self.display_type = self.get_config_value("display_type", "division")  # 'division' or 'conference'

        # Support both single string (backwards compatibility) and list of divisions/conferences
        division_config = self.get_config_value("division", "NFC East")
        if isinstance(division_config, str):
            self.divisions = self._expand_division_config([division_config])
        elif isinstance(division_config, list):
            self.divisions = self._expand_division_config(division_config)
        else:
            debug.warning(f"NFL Standings Board: Invalid division config type: {type(division_config)}, using default")
            self.divisions = ["NFC East"]

        self.current_division_index = 0  # Track which division we're showing
        self.display_seconds = self.get_config_value("display_seconds", 5)
        self.scroll_speed = self.get_config_value("scroll_speed", 0.2)
        self.use_large_font = self.get_config_value("use_large_font", True)
        self.disable_win_pct = self.get_config_value("disable_win_pct", False)

        # Set up font and dimensions based on display size (same as NHL standings)
        if self.use_large_font and self.matrix.width >= 128:
            self.font = data.config.layout.font_large
            self.font_height = 13
            self.width_multiplier = 2
            self.logo_y_offset = 5
        else:
            self.font = data.config.layout.font
            self.font_height = 7
            self.width_multiplier = 1
            self.logo_y_offset = 3

        self.gradient = self._load_gradient()
        self.logo = self._load_nfl_logo()
        if self.logo:
            # Resize logo if needed to fit in header area
            logo_max_height = int(self.matrix.height ** 0.98)
            if self.logo.height > logo_max_height:
                ratio = logo_max_height / self.logo.height
                new_width = int(self.logo.width * ratio)
                self.logo = self.logo.resize((new_width, logo_max_height), Image.Resampling.LANCZOS)

        debug.info(f"NFL Standings Board: Configured for {self.display_type} - {len(self.divisions)} division(s): {', '.join(self.divisions)}")
        debug.info(f"NFL Standings Board: Using {'large' if self.width_multiplier == 2 else 'regular'} font")

        # Initialize shared data manager (works independently of NFLBoard)
        # The data manager is a singleton, so if NFLBoard is also enabled, they'll share the same instance
        data_manager_config = {
            "refresh_seconds": self.get_config_value("refresh_seconds", 300),
            "cache_expiration_seconds": self.get_config_value("cache_expiration_seconds", 300),
            "team_ids": []  # Standings doesn't need favorite teams
        }
        self.data_manager = NFLDataManager.get_instance(data, data_manager_config)

        # Ensure data is loaded (from cache or API)
        self.data_manager.ensure_data_loaded()

        # Start the refresh scheduler if not already running
        if hasattr(data, 'scheduler') and data.scheduler:
            self.data_manager.start_refresh_scheduler(data.scheduler)
            debug.info("NFL Standings Board: Started data refresh scheduler")
        else:
            debug.warning("NFL Standings Board: No scheduler available, data won't auto-refresh")

    def _expand_division_config(self, division_list: List[str]) -> List[str]:
        """
        Expand division config to handle shortcuts.

        If display_type is "division":
        - "AFC" or "NFC" expands to all divisions in that conference
        - "AFC East" stays as "AFC East"

        If display_type is "conference":
        - Everything passes through as-is (handled in render method)

        Args:
            division_list: List of division/conference names from config

        Returns:
            Expanded list of divisions
        """
        if self.display_type != "division":
            # For conference mode, don't expand - let render() handle it
            return division_list

        expanded = []
        for item in division_list:
            # Check if this is a conference shortcut (AFC or NFC without a division)
            if item == "AFC":
                debug.info("NFL Standings Board: Expanding 'AFC' to all AFC divisions")
                expanded.extend(["AFC East", "AFC North", "AFC South", "AFC West"])
            elif item == "NFC":
                debug.info("NFL Standings Board: Expanding 'NFC' to all NFC divisions")
                expanded.extend(["NFC East", "NFC North", "NFC South", "NFC West"])
            else:
                # Regular division name or conference with space
                expanded.append(item)

        return expanded

    def _get_snapshot(self) -> Optional[NFLDataSnapshot]:
        """Get the shared NFL data snapshot (works independently of NFLBoard)."""
        return self.data_manager.get_snapshot()

    def _calculate_contrast_ratio(self, color1: tuple, color2: tuple) -> float:
        """
        Calculate contrast ratio between two colors using WCAG formula.

        Args:
            color1: RGB tuple (r, g, b)
            color2: RGB tuple (r, g, b)

        Returns:
            Contrast ratio (1.0 to 21.0, higher is more contrast)
        """
        def relative_luminance(color):
            """Calculate relative luminance of a color."""
            rgb = [c / 255.0 for c in color]
            rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
            return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

        lum1 = relative_luminance(color1)
        lum2 = relative_luminance(color2)

        lighter = max(lum1, lum2)
        darker = min(lum1, lum2)

        return (lighter + 0.05) / (darker + 0.05)

    def _get_readable_text_color(self, bg_color: tuple, preferred_color: tuple) -> tuple:
        """
        Get a readable text color for the given background.
        Tries to use the preferred color (secondary team color), but falls back to white/black
        if the contrast is too low.

        Args:
            bg_color: Background color RGB tuple
            preferred_color: Preferred text color (team's secondary color) RGB tuple

        Returns:
            RGB tuple for text color
        """
        # WCAG AA standard requires contrast ratio of at least 4.5:1 for normal text
        # We'll use a slightly lower threshold (3.5:1) for LED displays
        MIN_CONTRAST_RATIO = 3.5

        # Check if preferred color has good contrast
        contrast = self._calculate_contrast_ratio(bg_color, preferred_color)

        if contrast >= MIN_CONTRAST_RATIO:
            return preferred_color

        # Preferred color doesn't have enough contrast, try white and black
        white_contrast = self._calculate_contrast_ratio(bg_color, (255, 255, 255))
        black_contrast = self._calculate_contrast_ratio(bg_color, (0, 0, 0))

        # Return whichever has better contrast
        return (255, 255, 255) if white_contrast > black_contrast else (0, 0, 0)

    def _get_division_standings(self, division_name: str) -> List[NFLTeam]:
        """
        Get teams in a division sorted by standings from cached data.
        Uses dynamic division mapping built from API data.

        Args:
            division_name: Division name (e.g., 'AFC East', 'NFC North')

        Returns:
            List of NFLTeam objects sorted by record
        """
        snapshot = self._get_snapshot()
        if not snapshot or not snapshot.all_teams:
            debug.warning("NFL Standings Board: No cached team data available")
            return []

        # Use snapshot's dynamic method to get teams by division
        return snapshot.get_teams_by_division(division_name)

    def _get_conference_standings(self, conference: str) -> List[NFLTeam]:
        """
        Get all teams in a conference sorted by standings from cached data.
        Uses dynamic conference mapping built from API data.

        Args:
            conference: 'AFC' or 'NFC'

        Returns:
            List of NFLTeam objects sorted by record
        """
        snapshot = self._get_snapshot()
        if not snapshot or not snapshot.all_teams:
            debug.warning("NFL Standings Board: No cached team data available")
            return []

        # Use snapshot's dynamic method to get teams by conference
        return snapshot.get_teams_by_conference(conference)

    def _get_board_directory(self) -> Path:
        """Get the directory path for this board plugin."""
        return Path(__file__).parent

    def _load_gradient(self) -> Image.Image:
        """Load appropriate gradient image for current matrix size."""
        if self.matrix.height >= 48:
            gradient_path = get_file('assets/images/128x64_scoreboard_center_gradient.png')
        else:
            gradient_path = get_file('assets/images/64x32_scoreboard_center_gradient.png')

        gradient = Image.open(gradient_path)
        # Ensure it has alpha channel for transparency
        if gradient.mode != 'RGBA':
            gradient = gradient.convert('RGBA')
        return gradient

    def _load_nfl_logo(self) -> Optional[Image.Image]:
        """Load NFL logo from plugin assets directory."""
        try:
            logo_path = self._get_board_directory() / 'assets' / 'images' / 'nfl.png'
            if not logo_path.exists():
                debug.warning(f"NFL Standings Board: NFL logo not found at {logo_path}")
                return None

            logo = Image.open(logo_path)
            if logo.mode != 'RGBA':
                logo = logo.convert('RGBA')
            return logo
        except Exception as e:
            debug.error(f"NFL Standings Board: Failed to load NFL logo: {e}")
            return None

    def render(self):
        """
        Render the NFL standings board with scrolling if needed.
        Cycles through all configured divisions/conferences.
        Uses shared data manager (works independently).
        """
        # Check if we have data available
        snapshot = self._get_snapshot()
        if not snapshot or not snapshot.all_teams:
            debug.warning("NFL Standings Board: No NFL data available")
            self.matrix.clear()
            self.matrix.draw_text((0, 0), "No NFL Data", font=self.font, fill=(255, 255, 255))
            self.matrix.render()
            self.sleepEvent.wait(self.display_seconds)
            return

        # Cycle through all configured divisions/conferences
        for division in self.divisions:
            if self.sleepEvent.is_set():
                break

            # Get standings based on display type
            if self.display_type == "conference":
                # Extract conference from division string
                # Handles both "AFC East" -> "AFC" and "AFC" -> "AFC"
                if " " in division:
                    # Division name like "AFC East", extract conference part
                    conference = division.split()[0]
                else:
                    # Already a conference like "AFC" or "NFC"
                    conference = division

                standings = self._get_conference_standings(conference)
                title = f"{conference} Standings"
            else:
                # Division mode - division should already be expanded by _expand_division_config
                standings = self._get_division_standings(division)
                title = f"{division}"

            if not standings:
                debug.warning(f"NFL Standings Board: No standings data for {division}")
                continue

            # Create standings image
            image = self._create_standings_image(title, standings)

            # If image is taller than display, scroll it
            if image.height > self.matrix.height:
                self._render_with_scroll(image, title)
            else:
                self._render_with_scroll(image, title)
                # Just display it
                # self.matrix.clear()
                # self._draw_header_and_nfl_logo(title)
                # self.matrix.draw_image((0, 0), image)
                # self.matrix.render()
                # self.sleepEvent.wait(self.display_seconds)

            # Add a small delay between divisions if showing multiple
            if len(self.divisions) > 1 and division != self.divisions[-1]:
                self.sleepEvent.wait(0.5)

    def _draw_nfl_logo(self, title: str = "NFL Standings"):
        # Try to add NFL logo and gradient on the right side
        try:
            # get gradient
            gradient = self.gradient

            # get NFL logo
            nfl_logo = self.logo

            logo_x = self.matrix.width - nfl_logo.width - 1
            logo_y = self.logo_y_offset

            self.matrix.draw_image((logo_x, logo_y), nfl_logo)
            if not self.disable_win_pct:
                #self.matrix.draw_image((logo_x - int((self.matrix.width-gradient.width) * .3), 0), gradient)
                self.matrix.draw_image(("8%",0), gradient)
        except Exception as e:
            debug.warning(f"NFL Standings Board: Failed to add logo/gradient: {e}")

    def _create_standings_image(self, title: str, standings: List[NFLTeam], draw_win_pct: bool = True) -> Image.Image:
        """
        Create a PIL Image with the standings table using team colors.
        Includes NFL logo and gradient overlay.

        Args:
            title: Title text (division/conference name)
            standings: List of NFLTeam objects sorted by standings

        Returns:
            PIL Image with standings rendered
        """
        # Use instance font_height and width_multiplier (set in __init__)
        row_height = self.font_height
        top = row_height - 1  # For rectangle drawing

        # Calculate image height
        num_lines = len(standings)
        image_height = row_height + (num_lines * row_height)  # header + teams
        if image_height < self.matrix.height:
            image_height = self.matrix.height  # Ensure at least matrix height
        image_width = self.matrix.width

        # Create base image (RGB for final output)
        image = Image.new("RGB", (image_width, image_height), (0, 0, 0))

        # Draw standings with colored team backgrounds (like NHL)
        draw = ImageDraw.Draw(image)
        row_pos = row_height - 1

        for team in standings:
            # Draw colored rectangle background for team abbreviation
            bg_color = team.color_primary

            # Try to use secondary color for text, but ensure it's readable
            txt_color = self._get_readable_text_color(bg_color, team.color_secondary)

            # Draw background rectangle for team abbreviation (12 * width_multiplier pixels wide)
            draw.rectangle(
                [0, row_pos, 12 * self.width_multiplier, top + row_pos],
                fill=bg_color
            )

            # Draw team abbreviation in colored box
            draw.text(
                (1 * self.width_multiplier, row_pos),
                team.abbreviation,
                fill=txt_color,
                font=self.font
            )

            # Draw record (wins-losses or wins-losses-ties)
            draw.text(
                (14 * self.width_multiplier, row_pos),
                team.record_text,
                font=self.font,
                fill=(255, 255, 255)
            )

            # Draw win percentage (formatted to 3 decimal places like .625)
            if not self.disable_win_pct:
                pct_text = f".{int(team.win_percent * 1000):03d}"
                draw.text(
                    (35 * self.width_multiplier, row_pos),
                    pct_text,
                    font=self.font,
                    fill=(255, 255, 255)
                )

            row_pos += row_height

        # Trim width of image if needed (remove extra space on right)
        image = image.crop((0, 0, image_width, row_pos))

        # Trim Transparency (width only)
        bbox = image.getbbox()
        if bbox:
            image = image.crop((bbox[0], 0, bbox[2], image.height))


        return image

    def _render_with_scroll(self, image: Image.Image, title: str):
        """
        Render image with vertical scrolling animation.

        Args:
            image: PIL Image to scroll
        """
        # Start at top
        y_offset = 0

        # Show top for a moment
        self.matrix.clear()
        # Draw logo, gradient, standings, title
        self._draw_nfl_logo()
        self.matrix.draw_image((0, y_offset), image)
        self.matrix.draw_rectangle((0, 0), (image.width, self.font_height - 1), fill=(0, 0, 0))
        self.matrix.draw_text((1, 0), title, font=self.font, fill=(200, 200, 200))
        self.matrix.render()
        self.sleepEvent.wait(self.display_seconds)

        # Scroll down
        max_offset = -(image.height - self.matrix.height)
        while y_offset > max_offset and not self.sleepEvent.is_set():
            y_offset -= 1
            self.matrix.clear()
            self._draw_nfl_logo()
            self.matrix.draw_image((0, y_offset), image)
            self.matrix.draw_rectangle((0, 0), (image.width, self.font_height - 1), fill=(0, 0, 0))
            self.matrix.draw_text((1, 0), title, font=self.font, fill=(200, 200, 200))
            self.matrix.render()
            self.sleepEvent.wait(self.scroll_speed)

        # Show bottom for a moment
        self.sleepEvent.wait(self.display_seconds)

    def cleanup(self):
        """Clean up resources when board is unloaded."""
        debug.info("NFL Standings Board: Cleaning up resources")

        # Release data manager reference (only stops scheduler when last reference is released)
        NFLDataManager.release_instance()

        # Call parent cleanup
        super().cleanup()
        debug.info("NFL Standings Board: Cleanup complete")
