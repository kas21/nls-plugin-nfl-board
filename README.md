# NFL Board Plugin

A NFL scoreboard plugin for the [NHL LED Scoreboard](https://github.com/falkyre/nhl-led-scoreboard) that shows live games, scores, team information, schedules, and standings for your favorite NFL teams.

![NFL Team Summary 128x64 - Washington](assets/images/nfl_board_team_summary_128_wsh.jpg)

<a href="https://www.buymeacoffee.com/kas21" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Display Modes](#display-modes)
- [Layouts](#layouts)
- [Logo Customization](#logo-customization)
- [Screenshots](#screenshots)

## Features

- **Live Game Display**: Real-time scores and game status for ongoing NFL games
- **Game Schedules**: Shows upcoming games with dates and times
- **Completed Games**: Displays final scores for finished games
- **Team Summaries**: Shows team records, next game, and last game results
- **Standings Board**: Display current NFL standings by division or conference with team-colored backgrounds
- **Multi-Team Support**: Track multiple favorite teams simultaneously
- **Flexible Display Options**: Show only your favorite team's games or all NFL games happening today
- **Team Logos**: Automatic logo downloading and caching with customizable positioning
- **LED Matrix Sizes**: Supports both 64x32 and 128x64 matrix sizes
- **Smart Caching**: Stale-while-revalidate caching for improved performance and resilience

## Installation

Use the NHL Led Scoreboard's plugin manager python script to install or upgrade:

`python plugins.py sync` if board is in your scoreboard's plugins.json.  This will install or upgrade the plugin.

or

`python plugins.py add https://github.com/kas21/nls-plugin-nfl-board.git`

After the plugin is installed, add `nfl_board` and/or `nfl_standings` to your NHL-LED-Scoreboard's main configuration:

`nano config/config.json`

For example, to add both boards to the off day rotation:

```json
"states": {
    "off_day": [
        "season_countdown",
        "nfl_board",
        "nfl_standings",
        "team_summary",
        "scoreticker",
        "clock"
    ]
}
```

**Note:** You must restart the scoreboard for changes to take effect.

## Configuration

To customize the plugin settings, copy the sample config to create your own configuration file:

```bash
cd src/boards/plugins/nfl_board
cp config.sample.json config.json
nano config.json
```

**Note:** You must restart the scoreboard for changes to take effect.

### Example Configuration

```json
{
    "team_ids": ["28", "2"],
    "display_seconds": 5,
    "refresh_seconds": 180,
    "show_all_games": true,
    "show_previous_games_until": "09:00",
    "enabled": true,
    "division": "NFC East",
    "display_type": "division",
    "scroll_speed": 0.2,
    "use_large_font": true
}
```

### NFL Board Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `team_ids` | Array/String | Required | NFL team IDs to follow (see Team IDs section) |
| `display_seconds` | Integer | 8 | Seconds to display each screen |
| `refresh_seconds` | Integer | 300 | Seconds between data refreshes |
| `show_all_games` | Boolean | false | Show all NFL games, not just favorite teams |
| `show_previous_games_until` | String | "06:00" | Time (HH:MM) until which to show previous day's games |
| `enabled` | Boolean | true | Enable/disable the board (currently not functional) |

**Note:** Cache expiration times are intelligently set based on data type:

- **Team data** (logos, colors, names): 24 hours - rarely changes
- **Schedules**: 12 hours - changes weekly during season
- **Standings/Records**: 4 hours - updates after games
- **Scoreboard data** (dynamic based on game state):
  - Live games: 1 minute - needs frequent updates
  - Games starting within 2 hours: 1 minute - catch when they go live
  - All games completed: 12 hours - final scores don't change
  - All games far in future: 1 hour - game times stable

### NFL Standings Board Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `division` | String | "NFC East" | Division name to display (e.g., "NFC East", "AFC North") |
| `display_type` | String | "division" | Display mode: "division" or "conference" |
| `scroll_speed` | Float | 0.2 | Speed of scrolling for long standings lists (pixels per frame) |
| `use_large_font` | Boolean | true | Use larger font for standings (recommended for 128x64 displays) |

### Finding Team IDs

Team IDs correspond to ESPN's NFL team identifiers. Common team IDs include:

- **AFC East**: Buffalo Bills (2), Miami Dolphins (15), New England Patriots (17), New York Jets (20)
- **AFC North**: Baltimore Ravens (33), Cincinnati Bengals (4), Cleveland Browns (5), Pittsburgh Steelers (23)
- **AFC South**: Houston Texans (34), Indianapolis Colts (11), Jacksonville Jaguars (30), Tennessee Titans (10)
- **AFC West**: Denver Broncos (7), Kansas City Chiefs (12), Las Vegas Raiders (13), Los Angeles Chargers (24)
- **NFC East**: Dallas Cowboys (6), New York Giants (19), Philadelphia Eagles (21), Washington Commanders (28)
- **NFC North**: Chicago Bears (3), Detroit Lions (8), Green Bay Packers (9), Minnesota Vikings (16)
- **NFC South**: Atlanta Falcons (1), Carolina Panthers (29), New Orleans Saints (18), Tampa Bay Buccaneers (27)
- **NFC West**: Arizona Cardinals (22), Los Angeles Rams (14), San Francisco 49ers (25), Seattle Seahawks (26)

## Display Modes

The board intelligently displays different content based on game status:

### Live Games

- Team logos and abbreviations
- Current score
- Quarter and time remaining

### Upcoming Games

- Team logos and abbreviations
- Team records
- Game date and time
- "VS" indicator

### Completed Games

- Team logos and abbreviations
- Final score
- "FINAL" status

### Team Summary (when no games scheduled)

- Team logo
- Team name with team colors
- Season record
- Next scheduled game
- Last game result

### NFL Standings Board

The standings board displays current NFL standings with the following features:

- **Division View**: Shows all teams in a specific division (e.g., "NFC East", "AFC North")
- **Conference View**: Shows all teams in a conference (e.g., "NFC", "AFC")
- **Team-Colored Backgrounds**: Each team entry uses the team's primary color as background
- **Smart Text Colors**: Team abbreviations use secondary team colors with WCAG-compliant contrast checking
- **Win Percentage**: Displays win percentage alongside team records
- **Automatic Scrolling**: Scrolls smoothly when standings exceed display height
- **NFL Logo Overlay**: Features the NFL logo in the header with a gradient background
- **Dynamic Data**: Divisions and conferences are dynamically retrieved from the ESPN API

Standings are sorted by wins (descending), losses (ascending), and ties.

## Layouts

The plugin includes pre-configured layouts for different matrix sizes:

- `layout_64x32.json` - For 64x32 pixel displays
- `layout_128x64.json` - For 128x64 pixel displays

Layouts define the positioning of:

- Team logos
- Team names
- Scores/records
- Game status
- Date/time information

## Logo Customization

Team logo positioning and sizing can be customized in `logo_offsets.json`. The plugin supports element-specific offsets to handle different display contexts (team summary, home team in game, away team in game).

### Configuration Structure

```json
{
    "_default": {
        "zoom": 1.0,
        "offset": [0, 0]
    },
    "WSH": {
        "team_logo": {
            "zoom": 1.1,
            "offset": [-4, 0]
        },
        "home_team_logo": {
            "zoom": 1.4,
            "offset": [0, 7]
        },
        "away_team_logo": {
            "zoom": 1.4,
            "offset": [0, 0]
        }
    }
}
```

### Offset Keys

- **`_default`**: Global fallback settings applied to all teams/elements unless overridden
- **`team_logo`**: Used when displaying team summaries (when no games are scheduled)
- **`home_team_logo`**: Used when the team is the home team in a game display
- **`away_team_logo`**: Used when the team is the away team in a game display

### Parameters

- **`zoom`**: Scale factor for the logo (1.0 = original size, 1.2 = 20% larger, 0.8 = 20% smaller)
- **`offset`**: `[x, y]` pixel offset for fine-tuning logo position

Logos are automatically downloaded from ESPN and cached in the `assets/logos/nfl/` directory.

## Screenshots

### 128x64 Display

#### Game Display

![NFL Game Display 128x64](assets/images/nfl_board_game_128.jpg)

#### Team Summary - Washington Commanders

![NFL Team Summary 128x64 - Washington](assets/images/nfl_board_team_summary_128_wsh.jpg)

#### Team Summary - Buffalo Bills

![NFL Team Summary 128x64 - Buffalo](assets/images/nfl_board_team_summary_128_bills.jpg)

#### Standings - NFC East

![NFL Standings 128x64 - NFC East](assets/images/nfl_board_standings_128.jpg)

### 64x32 Display

#### Upcoming/Live/Completed Game

![NFL Game Display 64x32](assets/images/nfl_board_game_64.jpg)

#### Team Summary

![NFL Team Summary 64x32](assets/images/nfl_board_team_summary_64.jpg)

#### Standings

![NFL Standings 64x32 - NFC East](assets/images/nfl_board_standings_64.jpg)
