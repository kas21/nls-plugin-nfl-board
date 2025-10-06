"""
NFL Logo Management
Handles logo downloading, caching, and file ownership management.
"""

import logging
import requests
import platform
import os
from pathlib import Path
from typing import Optional, List
from PIL import Image
import io

from .data import NFLTeam

debug = logging.getLogger("scoreboard")

# Get UID/GID for file ownership fixes (when running as root)
try:
    uid = int(os.stat("./VERSION").st_uid)
    gid = int(os.stat("./VERSION").st_uid)
except:
    uid = None
    gid = None


class NFLLogoManager:
    """
    Manages NFL team logo downloads and caching.
    Handles file permissions when running as root.
    """

    def __init__(self, logo_cache_directory: Optional[Path] = None):
        """
        Initialize the logo manager.

        Args:
            logo_cache_directory: Directory to cache logos (default: assets/logos/nfl)
        """
        self.logo_cache_directory = logo_cache_directory or Path("assets/logos/nfl")

        # Ensure logo cache directory exists
        self.logo_cache_directory.mkdir(parents=True, exist_ok=True)
        self.change_ownership(self.logo_cache_directory)

    def change_ownership(self, path: Path):
        """
        Fix file ownership for files created by root.
        Recursively changes ownership of files and directories.
        """
        # If we're not on a Unix distro, this won't do anything
        if platform.system() == 'Linux':
            if hasattr(os, "chown") and uid is not None and gid is not None:
                for root, dirs, files in os.walk(str(path)):
                    for d in dirs:
                        try:
                            os.chown(os.path.join(root, d), uid, gid)
                        except Exception as exc:
                            debug.warning(f"NFL Logo Manager: Failed to chown directory {d}: {exc}")
                    for f in files:
                        try:
                            os.chown(os.path.join(root, f), uid, gid)
                        except Exception as exc:
                            debug.warning(f"NFL Logo Manager: Failed to chown file {f}: {exc}")

    def download_team_logo(self, team: NFLTeam, size: int = 64) -> Optional[Path]:
        """
        Download and cache a team logo as a PNG file.

        Args:
            team: NFLTeam object with logo_url
            size: Target size for the logo (default 64px)

        Returns:
            Path to cached logo file, or None if download failed
        """
        if not team.logo_url:
            debug.warning(f"NFL Logo Manager: No logo URL for team {team.abbreviation}")
            return None

        # Generate cache filename
        cache_filename = f"{team.abbreviation.lower()}_{size}px.png"
        cache_path = self.logo_cache_directory / cache_filename

        # Return existing cached file if it exists
        if cache_path.exists():
            return cache_path

        try:
            debug.debug(f"NFL Logo Manager: Downloading logo for {team.abbreviation} from {team.logo_url}")

            # Download the logo
            response = requests.get(team.logo_url, timeout=10)
            response.raise_for_status()

            # Open and resize the image
            image = Image.open(io.BytesIO(response.content))

            # Convert to RGBA if not already (for transparency support)
            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            # Trim Transparency
            bbox = image.getbbox()
            image = image.crop(bbox)
            # Keep aspect ratio but ensure the longest edge is equal to size.
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
            if resampling is None:
                resampling = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
            image.thumbnail((size, size), resampling)

            # Create a square canvas and center the logo
            square_image = Image.new('RGBA', (size, size), (255, 255, 255, 0))

            # Calculate position to center the logo
            x = (size - image.width) // 2
            y = (size - image.height) // 2

            square_image.paste(image, (x, y), image)

            # Save as PNG
            square_image.save(cache_path, 'PNG')

            # Fix file ownership if running as root
            self.change_ownership(cache_path.parent)

            debug.debug(f"NFL Logo Manager: Cached logo for {team.abbreviation} at {cache_path}")
            return cache_path

        except Exception as exc:
            debug.error(f"NFL Logo Manager: Failed to download logo for {team.abbreviation}: {exc}")
            return None

    def get_team_logo_path(self, team: NFLTeam, size: int = 128, download_if_missing: bool = True) -> Optional[Path]:
        """
        Get the local path to a team's logo, optionally downloading if missing.

        Args:
            team: NFLTeam object
            size: Target logo size (default 128px)
            download_if_missing: Whether to download the logo if not cached

        Returns:
            Path to logo file, or None if not available
        """
        cache_filename = f"{team.abbreviation.lower()}_{size}px.png"
        cache_path = self.logo_cache_directory / cache_filename

        # Return existing cached file
        if cache_path.exists():
            return cache_path

        # Download if requested and URL available
        if download_if_missing and team.logo_url:
            return self.download_team_logo(team, size)

        return None

    def preload_logos_for_teams(self, teams: List[NFLTeam], size: int = 64) -> int:
        """
        Preload logos for a list of teams.

        Args:
            teams: List of NFLTeam objects
            size: Target logo size (default 64px)

        Returns:
            Number of logos successfully downloaded/cached
        """
        success_count = 0

        for team in teams:
            logo_path = self.get_team_logo_path(team, size, download_if_missing=True)
            if logo_path:
                success_count += 1

        debug.debug(f"NFL Logo Manager: Preloaded {success_count}/{len(teams)} team logos")
        return success_count
