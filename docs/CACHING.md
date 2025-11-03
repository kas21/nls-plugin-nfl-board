# NFL Board Caching System

The NFL Board uses an intelligent multi-tier caching system to optimize API usage while ensuring data freshness. This document explains what data is cached, where it's stored, and how expiration times are determined.

## Quick Reference

| Cache Key | Data Type | Count | Expiration | Size |
|-----------|-----------|-------|------------|------|
| `nfl_all_teams` | Basic team info | 32 teams | 24 hours | ~6 KB |
| `nfl_team_details_{id}` | Team records | 32 entries | 4 hours | ~400 bytes each |
| `nfl_scoreboard_{YYYYMMDD}` | Daily games | 1-16 games | Dynamic* | ~1-5 KB |
| `nfl_schedule_{id}` | Team schedule | Per favorite team | 12 hours | ~2-5 KB |

\* Scoreboard expiration: 1 min (live), 1 min (starting soon), 12h (completed), 1h (future)

## Cache Location

All cache data is stored using `diskcache` in `/tmp/sb_cache/`.

## Cache Architecture

The caching system uses a **stale-while-revalidate** pattern:

1. On startup, load data from cache immediately (even if expired)
2. Background jobs refresh data before cache expires
3. If API fails, serve stale cache data

## Cache Keys and Data Structure

### Team Data

#### `nfl_all_teams`

- **Contains**: Basic information for all 32 NFL teams
- **Data Structure**: Dictionary mapping team_id → team dict

  ```python
  {
    "team_id": str,
    "name": str,              # "Buffalo Bills"
    "abbreviation": str,      # "BUF"
    "display_name": str,      # "Bills"
    "location": str,          # "Buffalo"
    "color_primary": tuple,   # RGB (0, 51, 141)
    "color_secondary": tuple, # RGB (198, 12, 48)
    "logo_url": str,
    # Basic record info (may be incomplete without details)
    "record_wins": int,
    "record_losses": int,
    "record_ties": int,
    "record_summary": str,
    "record_comment": str,
    "win_percent": float,
    "division_id": str,
    "conference_id": str,
    "division_name": str
  }
  ```

- **Expiration**: 24 hours (86400 seconds)
- **Rationale**: Team metadata rarely changes (names, colors, logos)
- **Refreshed by**: `NFLApiClient.get_all_teams()`

#### `nfl_team_details_{team_id}`

- **Contains**: Detailed standings/record information for a specific team
- **Data Structure**: Single team dict (same structure as above, but with complete record data)

  ```python
  {
    # ... all fields from nfl_all_teams ...
    "record_wins": int,       # Complete and accurate
    "record_losses": int,
    "record_ties": int,
    "record_summary": str,    # "10-3" or "10-3-1"
    "record_comment": str,    # "1st in NFC East, 3rd in NFC"
    "win_percent": 0.769,
    "division_name": "NFC East"
  }
  ```

- **Expiration**: 4 hours (14400 seconds)
- **Rationale**: Standings change after each game, need fresher data than basic team info
- **Refreshed by**: `NFLApiClient.get_team_details(team_id)`
- **Example Keys**: `nfl_team_details_2` (Bills), `nfl_team_details_28` (Commanders)

### Game Data

#### `nfl_scoreboard_{YYYYMMDD}`

- **Contains**: All games for a specific date
- **Data Structure**: List of game dicts

  ```python
  [
    {
      "game_id": str,
      "date": str,              # ISO format datetime
      "home_team": dict,        # Full team dict
      "away_team": dict,        # Full team dict
      "home_score": int,
      "away_score": int,
      "status_state": str,      # "pre", "in", "post"
      "status_detail": str,     # "Scheduled", "1st Quarter", "Final"
      "quarter": str,           # "1", "2", "3", "4", "OT"
      "time_remaining": str,    # "12:34"
      "is_final": bool,
      "is_live": bool,
      "venue": str
    }
  ]
  ```

- **Expiration**: **Dynamic based on game state**
  - Live games: 60 seconds (1 minute)
  - Games starting within 2 hours: 60 seconds
  - All games completed: 43200 seconds (12 hours)
  - All games far in future: 3600 seconds (1 hour)
- **Rationale**:
  - Live games need frequent updates for scores
  - Pre-game needs frequent updates to catch when game goes live
  - Completed games are stable and can be cached long-term
- **Refreshed by**: `NFLApiClient.get_scoreboard_for_date(date)`
- **Example Keys**: `nfl_scoreboard_20251031`, `nfl_scoreboard_20251030`

### Schedule Data

#### `nfl_schedule_{team_id}`

- **Contains**: Recent past and upcoming games for a specific team
- **Data Structure**: List of game dicts (same structure as scoreboard)
- **Expiration**: 12 hours (43200 seconds)
- **Rationale**: Team schedules change weekly during season, don't need minute-by-minute updates
- **Refreshed by**: `NFLApiClient.get_team_schedule(team_id)`
- **Example Keys**: `nfl_schedule_2` (Bills schedule), `nfl_schedule_28` (Commanders schedule)

## Cache Expiration Strategy

### Smart Scoreboard Expiration

The scoreboard cache uses intelligent expiration based on game state:

```python
# Priority order (shortest expiration wins):
# 1. Any games live → 1 minute
if has_live_games:
    expire = 60 seconds

# 2. Any games starting within 2 hours → 1 minute
elif has_games_starting_soon:
    expire = 60 seconds

# 3. All games completed → 12 hours
elif all_games_completed:
    expire = 43200 seconds

# 4. All games far in future → 1 hour
else:
    expire = 3600 seconds
```

This ensures:

- Live game scores update every minute
- Pre-game transitions to live are caught immediately (2-hour window)
- Completed games don't waste API calls
- Future games check occasionally for schedule changes

### Two-Tier Team Data

Team data uses a two-tier approach:

#### Tier 1: Basic Data (24h)

- Team names, colors, logos
- Changes very rarely (team relocations, rebrands)
- Long cache reduces API load

#### Tier 2: Detailed Records (4h)

- Win/loss records, standings, division rank
- Changes after each game
- Shorter cache ensures standings are current

## Cache Loading Behavior

### On Application Start

1. **Check for snapshot in memory**: `self.data.nfl_board_snapshot`
2. **If no snapshot**, attempt to load from cache:
   - Load `nfl_all_teams` (basic team data)
   - Load `nfl_team_details_{id}` for each team (detailed records)
   - Load `nfl_scoreboard_{today}` and `nfl_scoreboard_{yesterday}`
   - Load `nfl_schedule_{id}` for favorite teams
3. **If cache exists**: Use it immediately (even if expired)
4. **If no cache**: Perform full API refresh
5. **Schedule background refresh**: APScheduler job runs every `refresh_seconds`

### Background Refresh

Background jobs update cache at these intervals:

- Scheduled refresh: Every 180 seconds (configurable via `refresh_seconds`)
- Each API call checks cache and updates if expired
- Stale cache served if API fails

## Cache Utilities

### Inspecting Cache

Use the cache inspector tool:

```bash
uv run scripts/check_cache.py
```

Shows:

- All NFL cache entries
- Expiration status (time remaining or time since expired)
- Data size (number of items)
- Cache validity and accessibility

### Clearing Cache

```bash
rm -rf /tmp/sb_cache
```

Cache will be rebuilt on next app start.

### Cache Issues

If you see missing data on startup:

1. Run `uv run scripts/check_cache.py` to check cache state
2. Look for entries with very short expiration (< 1 minute)
3. Check if detailed team records (`nfl_team_details_*`) exist
4. Verify cache files have proper permissions

## Implementation Details

### Cache Storage Format

All data is stored using `diskcache.Cache.set()` with `read=False`:

```python
sb_cache.set(cache_key, data_as_dict, expire=expiration_seconds, read=False)
```

The `read=False` parameter forces inline storage in the database rather than as separate files, preventing cache corruption issues.

### Cache Retrieval

**In API methods (`data.py`)**: Standard cache retrieval respects expiration:

```python
cached_data = sb_cache.get(cache_key, default=None)
```

If cache exists and is not expired, return it. Otherwise, fetch from API.

**On startup (`board.py`)**: Cache-only loading ignores expiration:

```python
cached_data = sb_cache.get(cache_key, default=None, expire_time=False)
```

This allows loading stale cache on startup for fast boot, then background jobs refresh the data.

**Note**: Despite `expire_time=False`, diskcache evicts expired entries after a period, so very old cache may still be missing. This is why proper expiration times (4-24 hours) are critical.

### Data Serialization

Objects are converted to dicts for caching:

- `NFLTeam` → dict via `_team_to_dict()`
- `NFLGame` → dict via `_game_to_dict()`
- Dicts → objects via `_dict_to_team()`, `_dict_to_game()`

Dates are stored as ISO format strings and parsed back to datetime objects.

## Performance Benefits

### With Caching

- **Startup time**: < 1 second (loads from cache)
- **API calls on start**: 0 (uses cache)
- **Live game updates**: Every 60 seconds
- **Static data updates**: Every 24 hours

### Without Caching

- **Startup time**: 5-10 seconds (waits for all API calls)
- **API calls on start**: 40+ calls (teams + schedules + scoreboards)
- **Every restart**: Full API refresh required

### Cache Hit Rates

Expected hit rates:

- **Morning (off-day)**: ~95% cache hits
- **Game day (pre-game)**: ~80% cache hits (frequent scoreboard updates)
- **Game day (live)**: ~60% cache hits (scoreboard updates every minute)
- **Post-game**: ~90% cache hits

## Troubleshooting

### Data Shows "---" or "NO DATA"

**Problem**: Team records or standings show as missing

**Cause**: Detailed team records not loaded from cache

**Solution**: Check if `nfl_team_details_*` entries exist:

```bash
uv run scripts/check_cache.py | grep team_details
```

If missing, cache was cleared or never populated. Wait for background refresh or restart app.

### Cache Not Persisting Between Restarts

**Problem**: App always fetches from API on startup

**Cause**: Cache expiring too quickly or being evicted

**Solution**:

1. Check expiration times with cache inspector
2. Verify cache entries have hours (not seconds) remaining
3. If all entries show expired, check system time

### "No cache available" on Startup

**Problem**: Log shows "No cached teams data available"

**Cause**: First run or cache was cleared

**Solution**: Normal behavior - app will fetch from API and populate cache for next run

## Configuration

While cache expiration times are built-in, you can influence caching behavior:

- **`refresh_seconds`**: How often background job runs (default: 120)
  - Shorter = more API calls, fresher data
  - Longer = fewer API calls, but relies more on cache

Cache expiration times are hardcoded based on data characteristics and not user-configurable to maintain optimal behavior.
