"""
NFL Board Data Management - Clean Implementation
Handles API calls and data processing using APScheduler for background refresh.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

# Temporary handling for cache import while we transition to drop privs version
try:
    from utils import get_or_create_cache
    sb_cache = get_or_create_cache()
except ImportError:
    from utils import sb_cache

debug = logging.getLogger("scoreboard")

# NFL games are scheduled in US Eastern Time
NFL_TIMEZONE = ZoneInfo("America/New_York")

def parse_espn_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ESPN datetime strings which typically end with Z."""
    if not value:
        return None
    try:
        # ESPN dates are UTC with "Z", convert to format that works with fromisoformat
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        debug.error(f"NFL Board: Could not parse datetime '{value}'")
        return None


def safe_int_conversion(value: Optional[str]) -> Optional[int]:
    """Safely convert ESPN score strings to integers."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_get_score_value(score_data) -> int:
    """Safely extract score value from various ESPN API formats."""
    if not score_data:
        return 0

    # Handle string format (direct score value)
    if isinstance(score_data, str):
        return safe_int_conversion(score_data) or 0

    # Handle dict format ({"value": "14"})
    if isinstance(score_data, dict) and "value" in score_data:
        return safe_int_conversion(score_data.get("value")) or 0

    return 0


@dataclass
class NFLTeam:
    """Represents an NFL team with all relevant information."""
    team_id: str
    name: str
    abbreviation: str
    display_name: str
    location: str
    color_primary: tuple  # RGB tuple like (255, 255, 255)
    color_secondary: tuple  # RGB tuple like (0, 0, 0)
    logo_url: Optional[str] = None
    record_wins: int = 0
    record_losses: int = 0
    record_ties: int = 0
    record_summary: str = ""
    record_comment: Optional[str] = "---"
    win_percent: float = 0.0
    # Division/Conference info from groups API
    division_id: Optional[str] = None
    conference_id: Optional[str] = None
    division_name: Optional[str] = None  # Extracted from standingSummary

    @property
    def has_detailed_record(self) -> bool:
        """Check if this team has detailed record information loaded."""
        return bool(self.record_summary or self.record_wins > 0 or self.record_losses > 0)

    @property
    def record_text(self) -> str:
        """Format team record for display with safe fallback."""
        # Use detailed record if available
        if self.record_summary:
            return self.record_summary

        # Fallback to basic wins/losses if we have that data
        if self.has_detailed_record:
            if self.record_ties > 0:
                return f"{self.record_wins}-{self.record_losses}-{self.record_ties}"
            return f"{self.record_wins}-{self.record_losses}"

        # No record data available
        return "---"


@dataclass
class NFLGame:
    """Represents an NFL game with complete information."""
    game_id: str
    date: Optional[datetime]
    home_team: NFLTeam
    away_team: NFLTeam
    home_score: int = 0
    away_score: int = 0
    status_state: str = "pre"
    status_detail: str = "Scheduled"
    quarter: Optional[str] = None
    time_remaining: Optional[str] = None
    is_final: bool = False
    is_live: bool = False
    venue: Optional[str] = None

    def involves_team(self, team_id: str) -> bool:
        """Check if this game involves the specified team."""
        return self.home_team.team_id == team_id or self.away_team.team_id == team_id

    def get_opposing_team(self, team_id: str) -> Optional[NFLTeam]:
        """Get the opposing team for the specified team ID."""
        if self.home_team.team_id == team_id:
            return self.away_team
        elif self.away_team.team_id == team_id:
            return self.home_team
        return None

    @property
    def winning_team(self) -> Optional[NFLTeam]:
        """Get the team that is currently winning."""
        if self.home_score > self.away_score:
            return self.home_team
        elif self.away_score > self.home_score:
            return self.away_team
        return None


class NFLApiClient:
    """
    Handles all NFL API communication with ESPN endpoints.
    Provides clean methods for different data needs.

    Division/conference mappings are now dynamically built from API data
    and stored in NFLDataSnapshot.get_teams_by_division() method.
    """

    def __init__(self, cache_expiration_seconds: int = 300):
        self.base_url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
        self.teams_cache: Dict[str, NFLTeam] = {}
        self.last_teams_fetch: Optional[datetime] = None

        # Different cache expiration times for different data types
        # These can be overridden by config, but we use smart defaults
        self.cache_expiration_seconds = cache_expiration_seconds

        # Team data (logos, colors, names) - rarely changes
        self.cache_teams_seconds = 86400  # 24 hours

        # Team schedules - changes weekly during season
        self.cache_schedule_seconds = 43200  # 12 hours

        # Team standings/records - updates after games
        self.cache_standings_seconds = 14400  # 4 hours

        # Scoreboard data - depends on game state (calculated dynamically)
        self.cache_live_game_seconds = 60  # 1 minute for live games
        self.cache_completed_game_seconds = 43200  # 12 hours for completed games
        self.cache_upcoming_game_seconds = 3600  # 1 hour for upcoming games

        debug.info("NFL API Client: Initialized with cache expiration times:")
        debug.info(f"  Teams: {self.cache_teams_seconds}s (24h)")
        debug.info(f"  Schedules: {self.cache_schedule_seconds}s (12h)")
        debug.info(f"  Standings: {self.cache_standings_seconds}s (4h)")
        debug.info(f"  Live games: {self.cache_live_game_seconds}s (1m)")
        debug.info(f"  Completed games: {self.cache_completed_game_seconds}s (12h)")
        debug.info(f"  Upcoming games: {self.cache_upcoming_game_seconds}s (1h)")

    def get_scoreboard_for_date(self, date: datetime) -> List[NFLGame]:
        """
        Get all games for a specific date using ESPN scoreboard endpoint.
        Date format: YYYYMMDD

        Uses stale-while-revalidate pattern: returns cached data (even if expired)
        for fast startup, then fetches fresh data if cache is expired.

        Note: ESPN API expects dates in US Eastern Time, so we normalize the date
        to Eastern Time to ensure we fetch the correct day's games.
        """
        # Normalize to Eastern Time for ESPN API
        # If date is naive, assume it's in local time and convert to ET
        if date.tzinfo is None:
            date = date.replace(tzinfo=ZoneInfo("localtime")).astimezone(NFL_TIMEZONE)
        else:
            date = date.astimezone(NFL_TIMEZONE)

        date_string = date.strftime("%Y%m%d")
        cache_key = f"nfl_scoreboard_{date_string}"

        # Try to get from cache first
        # Note: diskcache automatically evicts expired entries, so we only get valid cache
        cached_data = sb_cache.get(cache_key, default=None)
        if cached_data is not None:
            debug.debug(f"NFL Board: Using cached scoreboard data for {date_string}")
            # Parse cached data back into game objects
            games = []
            for game_dict in cached_data:
                game = self._dict_to_game(game_dict)
                if game:
                    games.append(game)

            return games

        url = f"{self.base_url}/scoreboard?dates={date_string}"

        debug.debug(f"NFL Board: Fetching scoreboard for {date_string} from API")

        try:
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            games = []
            events = data.get("events", [])

            for event in events:
                game = self._parse_game_from_event(event)
                if game:
                    games.append(game)

            # Sort games by start time
            games.sort(key=lambda g: g.date or datetime.min.replace(tzinfo=timezone.utc))

            debug.debug(f"NFL Board: Found {len(games)} games for {date_string}")

            # Determine cache expiration based on game states
            # Priority order (shortest expiration wins):
            # 1. Any games live → 1 minute (need frequent updates)
            # 2. Any games starting within 2 hours OR started within last 30 min → 1 minute (catch when they go live and during transition)
            # 3. All games completed → 12 hours (scores won't change)
            # 4. All games far in future → 1 hour (times are stable)

            has_live = any(game.is_live for game in games)
            all_completed = all(game.is_final for game in games) if games else False

            # Check if any games are starting soon (within 2 hours) OR started recently (within last 30 minutes)
            # This ensures we keep refreshing frequently during the transition when games start
            now = datetime.now(timezone.utc)
            has_starting_soon_or_recently_started = False
            for game in games:
                if game.date and not game.is_final:
                    time_until_game = (game.date - now).total_seconds()
                    # Game starts within 2 hours OR started within last 30 minutes (1800 seconds)
                    if -1800 <= time_until_game <= 7200:
                        has_starting_soon_or_recently_started = True
                        break

            if has_live:
                cache_expire = self.cache_live_game_seconds
                expire_desc = "live games"
            elif has_starting_soon_or_recently_started:
                cache_expire = self.cache_live_game_seconds
                expire_desc = "games starting soon or recently started"
            elif all_completed:
                cache_expire = self.cache_completed_game_seconds
                expire_desc = "all completed"
            else:
                cache_expire = self.cache_upcoming_game_seconds
                expire_desc = "upcoming games"

            # Cache the results as dicts
            games_as_dicts = [self._game_to_dict(game) for game in games]
            sb_cache.set(cache_key, games_as_dicts, expire=cache_expire, read=False)
            debug.debug(f"NFL Board: Cached scoreboard for {date_string} ({cache_expire}s expiration - {expire_desc})")

            return games

        except Exception as exc:
            debug.error(f"NFL Board: Failed to fetch scoreboard for {date_string}: {exc}")
            return []

    def get_current_scoreboard(self) -> List[NFLGame]:
        """Get current/today's games in NFL Eastern Time."""
        return self.get_scoreboard_for_date(datetime.now(NFL_TIMEZONE))

    def get_all_teams(self) -> Dict[str, NFLTeam]:
        """
        Get basic NFL teams information (no detailed records).
        Use get_team_details() to populate full details for specific teams.

        Uses stale-while-revalidate pattern: returns cached data (even if expired)
        for fast startup, then fetches fresh data if cache is expired.
        """
        cache_key = "nfl_all_teams"

        # Try to get from cache first
        # Note: diskcache automatically evicts expired entries
        cached_data = sb_cache.get(cache_key, default=None)
        if cached_data is not None:
            debug.debug("NFL Board: Using cached teams data")
            teams = {}
            for team_id, team_dict in cached_data.items():
                team = self._dict_to_team(team_dict)
                if team:
                    teams[team_id] = team

            self.teams_cache = teams
            self.last_teams_fetch = datetime.now()
            return teams

        try:
            url = f"{self.base_url}/teams"
            debug.info("NFL Board: Fetching basic teams data from API")

            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            teams = {}
            sports = data.get("sports", [])
            if sports:
                leagues = sports[0].get("leagues", [])
                if leagues:
                    team_list = leagues[0].get("teams", [])

                    for team_item in team_list:
                        team_data = team_item.get("team", {})
                        team = self._parse_basic_team_data(team_data)
                        if team:
                            teams[team.team_id] = team

            self.teams_cache = teams
            self.last_teams_fetch = datetime.now()

            # Cache the teams as dicts
            teams_as_dicts = {team_id: self._team_to_dict(team) for team_id, team in teams.items()}
            sb_cache.set(cache_key, teams_as_dicts, expire=self.cache_teams_seconds, read=False)
            debug.info(f"NFL Board: Cached {len(teams)} basic teams ({self.cache_teams_seconds}s / 24h expiration)")

            return teams

        except Exception as exc:
            debug.error(f"NFL Board: Failed to fetch teams: {exc}")
            return self.teams_cache if self.teams_cache else {}

    def get_team_schedule(self, team_id: str) -> List[NFLGame]:
        """
        Get schedule for a specific team.
        Returns recent and upcoming games.

        Uses stale-while-revalidate pattern: returns cached data (even if expired)
        for fast startup, then fetches fresh data if cache is expired.
        """
        cache_key = f"nfl_schedule_{team_id}"

        # Try to get from cache first
        # Note: diskcache automatically evicts expired entries
        cached_data = sb_cache.get(cache_key, default=None)
        if cached_data is not None:
            debug.debug(f"NFL Board: Using cached schedule data for team {team_id}")
            games = []
            for game_dict in cached_data:
                game = self._dict_to_game(game_dict)
                if game:
                    games.append(game)

            return games

        try:
            url = f"{self.base_url}/teams/{team_id}/schedule"
            debug.debug(f"NFL Board: Fetching schedule for team {team_id} from API")

            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            games = []
            events = data.get("events", [])

            for event in events:
                game = self._parse_game_from_event(event)
                if game:
                    games.append(game)

            # Sort games by start time
            games.sort(key=lambda g: g.date or datetime.min.replace(tzinfo=timezone.utc))

            debug.debug(f"NFL Board: Found {len(games)} scheduled games for team {team_id}")

            # Cache the schedule as dicts
            games_as_dicts = [self._game_to_dict(game) for game in games]
            sb_cache.set(cache_key, games_as_dicts, expire=self.cache_schedule_seconds, read=False)
            debug.debug(f"NFL Board: Cached schedule for team {team_id} ({self.cache_schedule_seconds}s / 12h expiration)")

            return games

        except Exception as exc:
            debug.error(f"NFL Board: Failed to fetch schedule for team {team_id}: {exc}")
            return []

    def _parse_basic_team_data(self, team_data: Dict[str, Any]) -> Optional[NFLTeam]:
        """Parse basic team information from ESPN /teams endpoint (no detailed records)."""
        try:
            team_id = team_data.get("id")
            if not team_id:
                return None

            # Extract logo URL
            logo_url = None
            logos = team_data.get("logos", [])
            if logos:
                logo_url = logos[0].get("href")

            # Convert colors to RGB tuples
            color_primary = self._hex_to_rgb(team_data.get("color", "000000"))
            color_secondary = self._hex_to_rgb(team_data.get("alternateColor", "FFFFFF"))

            return NFLTeam(
                team_id=team_id,
                name=team_data.get("name", ""),
                abbreviation=team_data.get("abbreviation", ""),
                display_name=team_data.get("displayName", ""),
                location=team_data.get("location", ""),
                color_primary=color_primary,
                color_secondary=color_secondary,
                logo_url=logo_url,
                # Note: No detailed record data - use get_team_details() to populate
                record_wins=0,
                record_losses=0,
                record_ties=0,
                record_summary="",
                record_comment="---"
            )

        except Exception as exc:
            debug.error(f"NFL Board: Failed to parse basic team data: {exc}")
            return None

    def _parse_team_data(self, team_data: Dict[str, Any]) -> Optional[NFLTeam]:
        """Parse team information from ESPN API response."""
        try:
            team_id = team_data.get("id")
            if not team_id:
                return None

            # Extract logo URL
            logo_url = None
            logos = team_data.get("logos", [])
            if logos:
                logo_url = logos[0].get("href")

            # Extract team record
            wins = losses = ties = 0
            win_percent = 0.0
            record_summary = ""
            # The record object has a list of record types
            # The first item in the list should be the TOTAL record
            record_items = team_data.get("record", {}).get("items", [])
            #debug.info(record_items)
            if record_items:
                # Get the summary from first record item
                summary = record_items[0].get("summary")
                if summary:
                    record_summary = summary

                # Also extract individual stats for our internal tracking
                stats = record_items[0].get("stats", [])
                for stat in stats:
                    stat_name = stat.get("name")
                    if stat_name == "wins":
                        wins = int(stat.get("value", 0))
                    elif stat_name == "losses":
                        losses = int(stat.get("value", 0))
                    elif stat_name == "ties":
                        ties = int(stat.get("value", 0))
                    elif stat_name == "winPercent":
                        win_percent = float(stat.get("value", 0.0))
                #debug.info(f"RECORD!!! {wins}-{losses}-{ties}")

            # Extract standing summary for record_comment
            record_comment = team_data.get("standingSummary")

            # Extract division/conference info from groups
            division_id = None
            conference_id = None
            division_name = None

            groups = team_data.get("groups", {})
            if groups:
                division_id = groups.get("id")
                parent = groups.get("parent", {})
                conference_id = parent.get("id")

            # Parse division name from standingSummary (e.g., "2nd in NFC East")
            if record_comment:
                import re
                match = re.search(r'in (.+)$', record_comment)
                if match:
                    division_name = match.group(1)

            # Convert colors to RGB tuples (old implementation expected tuples)
            color_primary = self._hex_to_rgb(team_data.get("color", "000000"))
            color_secondary = self._hex_to_rgb(team_data.get("alternateColor", "FFFFFF"))

            return NFLTeam(
                team_id=team_id,
                name=team_data.get("name", ""),
                abbreviation=team_data.get("abbreviation", ""),
                display_name=team_data.get("displayName", ""),
                location=team_data.get("location", ""),
                color_primary=color_primary,
                color_secondary=color_secondary,
                logo_url=logo_url,
                record_wins=wins,
                record_losses=losses,
                record_ties=ties,
                record_summary=record_summary,
                record_comment=record_comment,
                win_percent=win_percent,
                division_id=division_id,
                conference_id=conference_id,
                division_name=division_name
            )

        except Exception as exc:
            debug.error(f"NFL Board: Failed to parse team data: {exc}")
            return None

    def _parse_game_from_event(self, event_data: Dict[str, Any]) -> Optional[NFLGame]:
        """Parse game information from ESPN event data."""
        try:
            game_id = event_data.get("id", "")

            # Parse game date
            game_date = parse_espn_datetime(event_data.get("date"))

            # Parse competitions (should be one for NFL)
            competitions = event_data.get("competitions", [])
            if not competitions:
                return None

            competition = competitions[0]
            competitors = competition.get("competitors", [])

            if len(competitors) < 2:
                return None

            # Find home and away teams
            home_competitor = None
            away_competitor = None

            for competitor in competitors:
                if competitor.get("homeAway") == "home":
                    home_competitor = competitor
                elif competitor.get("homeAway") == "away":
                    away_competitor = competitor

            if not home_competitor or not away_competitor:
                return None

            # Parse team data from competitors
            home_team = self._parse_competitor_team(home_competitor)
            away_team = self._parse_competitor_team(away_competitor)

            if not home_team or not away_team:
                return None

            # Parse scores safely (handles both string and dict formats)
            home_score_data = home_competitor.get("score")
            away_score_data = away_competitor.get("score")

            home_score = safe_get_score_value(home_score_data)
            away_score = safe_get_score_value(away_score_data)

            # Parse game status
            status = competition.get("status", {})
            status_type = status.get("type", {})
            status_state = status_type.get("state", "pre")
            status_detail = status_type.get("shortDetail", "Scheduled")

            is_final = status_type.get("completed", False)
            is_live = status_state == "in"

            # Parse live game details
            quarter = None
            time_remaining = None
            if is_live:
                quarter = str(status.get("period", ""))
                time_remaining = status.get("displayClock")

            # Parse venue
            venue = None
            venue_data = competition.get("venue")
            if venue_data:
                venue = venue_data.get("fullName")

            return NFLGame(
                game_id=game_id,
                date=game_date,
                home_team=home_team,
                away_team=away_team,
                home_score=home_score,
                away_score=away_score,
                status_state=status_state,
                status_detail=status_detail,
                quarter=quarter,
                time_remaining=time_remaining,
                is_final=is_final,
                is_live=is_live,
                venue=venue
            )

        except Exception as exc:
            debug.error(f"NFL Board: Failed to parse game data: {exc}")
            import traceback
            debug.error(traceback.print_exc())
            return None

    def _parse_competitor_team(self, competitor: Dict[str, Any]) -> Optional[NFLTeam]:
        """Parse team data from competitor information."""
        team_data = competitor.get("team", {})
        team_id = team_data.get("id")

        if not team_id:
            return None

        # Check if we have this team in cache
        if team_id in self.teams_cache:
            return self.teams_cache[team_id]

        # Create basic team info from competitor data
        logo_url = None
        logos = team_data.get("logos", [])
        if logos:
            logo_url = logos[0].get("href")

        return NFLTeam(
            team_id=team_id,
            name=team_data.get("name", ""),
            abbreviation=team_data.get("abbreviation", ""),
            display_name=team_data.get("displayName", ""),
            location=team_data.get("location", ""),
            color_primary=(255, 255, 255),  # Default white for competitor data
            color_secondary=(0, 0, 0),      # Default black for competitor data
            logo_url=logo_url
        )

    def get_team_details(self, team_id: str) -> bool:
        """
        Fetch detailed team information and update the cached team.
        Returns True if successful, False otherwise.

        Uses stale-while-revalidate pattern: returns cached data (even if expired)
        for fast startup, then fetches fresh data if cache is expired.
        """
        cache_key = f"nfl_team_details_{team_id}"

        # Try to get from cache first
        # Note: diskcache automatically evicts expired entries
        cached_data = sb_cache.get(cache_key, default=None)
        if cached_data is not None:
            debug.debug(f"NFL Board: Using cached detailed data for team {team_id}")
            detailed_team = self._dict_to_team(cached_data)
            if detailed_team and team_id in self.teams_cache:
                self.teams_cache[team_id] = detailed_team
                return True

        try:
            url = f"{self.base_url}/teams/{team_id}"
            debug.debug(f"NFL Board: Fetching detailed data for team {team_id} from API")

            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            detailed_team = self._parse_team_data(data.get("team", {}))
            if detailed_team and team_id in self.teams_cache:
                # Update the cached team with detailed information
                self.teams_cache[team_id] = detailed_team

                # Cache the detailed team data (standings/records)
                team_dict = self._team_to_dict(detailed_team)
                sb_cache.set(cache_key, team_dict, expire=self.cache_standings_seconds, read=False)
                debug.debug(f"NFL Board: Updated and cached team {team_id} with detailed record data ({self.cache_standings_seconds}s / 4h expiration)")
                return True
            else:
                debug.warning(f"NFL Board: Failed to get detailed data for team {team_id}")
                return False

        except Exception as exc:
            debug.error(f"NFL Board: Failed to fetch team details for {team_id}: {exc}")
            return False

    def populate_team_details(self, team_ids: List[str]) -> int:
        """
        Populate detailed information for specified teams.
        Returns count of successfully updated teams.
        """
        success_count = 0
        debug.info(f"NFL Board: Populating details for {len(team_ids)} teams")

        for team_id in team_ids:
            if self.get_team_details(team_id):
                success_count += 1

        debug.info(f"NFL Board: Successfully populated details for {success_count}/{len(team_ids)} teams")
        return success_count

    def _hex_to_rgb(self, hex_color: str) -> tuple:
        """Convert hex color to RGB tuple."""
        try:
            # Strip leading '#' if present
            hex_color = hex_color.lstrip('#')
            # Convert to RGB tuple
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except (ValueError, TypeError):
            return (255, 255, 255)  # Default to white

    def _team_to_dict(self, team: NFLTeam) -> dict:
        """Convert NFLTeam dataclass to dict for caching."""
        return {
            'team_id': team.team_id,
            'name': team.name,
            'abbreviation': team.abbreviation,
            'display_name': team.display_name,
            'location': team.location,
            'color_primary': team.color_primary,
            'color_secondary': team.color_secondary,
            'logo_url': team.logo_url,
            'record_wins': team.record_wins,
            'record_losses': team.record_losses,
            'record_ties': team.record_ties,
            'record_summary': team.record_summary,
            'record_comment': team.record_comment,
            'win_percent': team.win_percent,
            'division_id': team.division_id,
            'conference_id': team.conference_id,
            'division_name': team.division_name,
        }

    def _dict_to_team(self, data: dict) -> Optional[NFLTeam]:
        """Convert dict to NFLTeam dataclass from cache."""
        try:
            return NFLTeam(
                team_id=data['team_id'],
                name=data['name'],
                abbreviation=data['abbreviation'],
                display_name=data['display_name'],
                location=data['location'],
                color_primary=tuple(data['color_primary']),
                color_secondary=tuple(data['color_secondary']),
                logo_url=data.get('logo_url'),
                record_wins=data.get('record_wins', 0),
                record_losses=data.get('record_losses', 0),
                record_ties=data.get('record_ties', 0),
                record_summary=data.get('record_summary', ''),
                record_comment=data.get('record_comment'),
                win_percent=data.get('win_percent', 0.0),
                division_id=data.get('division_id'),
                conference_id=data.get('conference_id'),
                division_name=data.get('division_name'),
            )
        except Exception as exc:
            debug.error(f"NFL Board: Failed to convert dict to team: {exc}")
            return None

    def _game_to_dict(self, game: NFLGame) -> dict:
        """Convert NFLGame dataclass to dict for caching."""
        return {
            'game_id': game.game_id,
            'date': game.date.isoformat() if game.date else None,
            'home_team': self._team_to_dict(game.home_team),
            'away_team': self._team_to_dict(game.away_team),
            'home_score': game.home_score,
            'away_score': game.away_score,
            'status_state': game.status_state,
            'status_detail': game.status_detail,
            'quarter': game.quarter,
            'time_remaining': game.time_remaining,
            'is_final': game.is_final,
            'is_live': game.is_live,
            'venue': game.venue,
        }

    def _dict_to_game(self, data: dict) -> Optional[NFLGame]:
        """Convert dict to NFLGame dataclass from cache."""
        try:
            home_team = self._dict_to_team(data['home_team'])
            away_team = self._dict_to_team(data['away_team'])

            if not home_team or not away_team:
                return None

            return NFLGame(
                game_id=data['game_id'],
                date=datetime.fromisoformat(data['date']) if data.get('date') else None,
                home_team=home_team,
                away_team=away_team,
                home_score=data.get('home_score', 0),
                away_score=data.get('away_score', 0),
                status_state=data.get('status_state', 'pre'),
                status_detail=data.get('status_detail', 'Scheduled'),
                quarter=data.get('quarter'),
                time_remaining=data.get('time_remaining'),
                is_final=data.get('is_final', False),
                is_live=data.get('is_live', False),
                venue=data.get('venue'),
            )
        except Exception as exc:
            debug.error(f"NFL Board: Failed to convert dict to game: {exc}")
            return None


class NFLDataSnapshot:
    """
    Pure data container for NFL data that gets stored on the scheduler refresh.
    Contains only data storage, no business logic.
    """

    def __init__(self):
        self.timestamp = datetime.now()
        self.error_message: Optional[str] = None

        # Teams data
        self.all_teams: Dict[str, NFLTeam] = {}
        self.favorite_teams: Dict[str, NFLTeam] = {}

        # Games data organized by category
        self.todays_games: List[NFLGame] = []
        self.yesterdays_games: List[NFLGame] = []
        self.favorite_team_games: List[NFLGame] = []
        self.live_games: List[NFLGame] = []

        # Team schedules for favorite teams
        self.team_schedules: Dict[str, List[NFLGame]] = {}

        # Dynamic division/conference mappings (built from API data)
        self._division_map: Optional[Dict[str, List[str]]] = None
        self._conference_map: Optional[Dict[str, List[str]]] = None

    def get_teams_by_division(self, division_name: str) -> List[NFLTeam]:
        """
        Get all teams in a division, dynamically built from team data.

        Args:
            division_name: Division name like "AFC East", "NFC North"

        Returns:
            List of NFLTeam objects in that division, sorted by record
        """
        teams = [
            team for team in self.all_teams.values()
            if team.division_name == division_name
        ]

        # Sort by record (wins desc, losses asc, ties asc)
        return sorted(teams, key=lambda t: (-t.record_wins, t.record_losses, t.record_ties))

    def get_teams_by_conference(self, conference: str) -> List[NFLTeam]:
        """
        Get all teams in a conference (AFC or NFC).

        Args:
            conference: "AFC" or "NFC"

        Returns:
            List of NFLTeam objects in that conference, sorted by record
        """
        teams = [
            team for team in self.all_teams.values()
            if team.division_name and team.division_name.startswith(conference)
        ]

        # Sort by record
        return sorted(teams, key=lambda t: (-t.record_wins, t.record_losses, t.record_ties))

    def get_all_divisions(self) -> List[str]:
        """
        Get list of all division names found in the data.

        Returns:
            List of division names like ["AFC East", "AFC North", ...]
        """
        divisions = set()
        for team in self.all_teams.values():
            if team.division_name:
                divisions.add(team.division_name)

        # Sort: AFC divisions first, then NFC
        return sorted(divisions, key=lambda d: (not d.startswith('AFC'), d))

    def get_all_conferences(self) -> List[str]:
        """
        Get list of all conferences found in the data.

        Returns:
            List of conference names ["AFC", "NFC"]
        """
        conferences = set()
        for team in self.all_teams.values():
            if team.division_name:
                if team.division_name.startswith('AFC'):
                    conferences.add('AFC')
                elif team.division_name.startswith('NFC'):
                    conferences.add('NFC')

        return sorted(conferences)
