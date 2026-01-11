# v2026.01.01 - Three Independent Boards

## 🏈 Major Release - Breaking Changes

This release completely refactors the NFL plugin into three independent boards with a shared data manager architecture.

## ⚠️ Breaking Changes

### Board Renaming (Action Required)

The `nfl_board` board ID is **deprecated** and no longer functional. Update your configuration:

**Old Configuration:**
```json
"states": {
    "off_day": [
        "nfl_board", 
        "nfl_standings"
    ]
}
```

**New Configuration:**
```json
"states": {
    "off_day": [
        "nfl_team_summary", 
        "nfl_game_ticker", 
        "nfl_standings"
    ]
}
```

### Migration Guide

1. Replace `nfl_board` with `nfl_team_summary` and/or `nfl_game_ticker` in your `config/config.json` states
2. Your plugin `config.json` file structure remains the same (flat JSON)
3. Restart the scoreboard after making changes

## ✨ What's New

### Three Independent Boards

1. **`nfl_team_summary`** - Team Information Display
   - Team logo and name with team colors
   - Season record (wins-losses-ties)
   - Record comment (division standing, playoff seed)
   - Next scheduled game (date, time, opponent)
   - Last game result (W/L, score, opponent)

2. **`nfl_game_ticker`** - Live Game Ticker
   - Live games with real-time scores and game clock
   - Upcoming games with date and time
   - Completed games with final scores
   - Option to show all games or just your favorite teams

3. **`nfl_standings`** - Division/Conference Standings
   - Division or conference view
   - Win-loss records and win percentage
   - Team-colored backgrounds with smart contrast
   - Automatic scrolling for larger divisions

### Key Improvements

- ✅ **Fully Independent Boards** - Each board works standalone with no dependencies
- ✅ **Shared Data Manager** - All boards share cached data efficiently through NFLDataManager singleton
- ✅ **Flexible Rotations** - Place boards anywhere in your rotation independently
- ✅ **Better Separation of Concerns** - Game ticker vs team summaries are now separate boards
- ✅ **Reference Counting** - Smart lifecycle management prevents premature data cleanup
- ✅ **APScheduler Integration** - Shared data refresh job across all boards

## 🔧 Technical Changes

- Introduced `NFLDataManager` singleton with reference counting
- Removed board dependencies - `nfl_standings` no longer requires `nfl_board`
- Refactored 810 lines of code from `board.py` into focused modules
- Created `nfl_team_summary.py` (810 lines) for team display
- Created `nfl_game_ticker.py` (580 lines) for game ticker
- Updated `nfl_standings_board.py` to use shared data manager
- Deleted deprecated `board.py` file

## 📝 Configuration

Configuration file structure is **unchanged** - still uses flat JSON structure:

```json
{
    "team_ids": ["28", "2"],
    "display_seconds": 5,
    "refresh_seconds": 120,
    "show_all_games": true,
    "show_previous_games_until": "09:00",
    "division": ["NFC East", "AFC East"],
    "display_type": "division",
    "scroll_speed": 0.09,
    "use_large_font": true,
    "disable_win_pct": false
}
```

See [README.md](README.md) for complete configuration documentation.

## 🐛 Bug Fixes

- Fixed issue where standings required main board to be enabled
- Improved error handling in data manager
- Better cache invalidation logic

## 📚 Documentation

- Completely rewritten README with three-board architecture
- Added "Board Overview" section explaining each board
- Updated configuration examples to show flat structure
- Clarified which options are used by which boards

## 🙏 Feedback

Please report any issues or feedback on the [GitHub Issues](https://github.com/kas21/nls-plugin-nfl-board/issues) page.

---

**Full Changelog**: https://github.com/kas21/nls-plugin-nfl-board/compare/v1.x.x...v2.0.0
