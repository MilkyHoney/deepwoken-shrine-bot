# Deepwoken Shrine Bot

A Discord bot that simulates the **Shrine of Order** mechanic from [Deepwoken](https://www.roblox.com/games/4111023553/Deepwoken). Run `/shrine` and walk through a guided flow to see exactly how your build gets redistributed. I plan on adding an automated builder.

---

## Commands

| Command | Description |
|---------|-------------|
| `/shrine` | Start the interactive Shrine of Order simulator |
| `/races` | List all races and their stat bonuses |
| `/help` | Show usage instructions and stat shortcuts |

---

## How `/shrine` Works

The bot walks you through the build step-by-step:

1. **Pick your race** — type the name or let fuzzy matching catch your typo
2. **Enter base stats** — `40 50 25 0 40 55` or `str=40 fort=50 agi=25 int=0 will=40 cha=55`
3. **Enter attunements** (or skip) — `flame=80 thunder=35 frost=40`
4. **Enter weapon** (or skip) — `med=85` or `light=60` or `heavy=70`

The bot validates caps and budget at every step, then outputs a clean embed showing your pre-shrine → post-shrine stat changes.

---

## Stat Shortcuts

| Shortcut | Stat |
|----------|------|
| `str` | Strength |
| `fort` | Fortitude |
| `agi` | Agility |
| `int` | Intelligence |
| `will` | Willpower |
| `cha` | Charisma |
| `flame` | Flamecharm |
| `frost` | Frostdraw |
| `thunder` | Thundercall |
| `gale` | Galebreathe |
| `shadow` | Shadowcast |
| `iron` | Ironsing |
| `blood` | Bloodrend |
| `light` | LightWeapon |
| `med` | MediumWeapon |
| `heavy` | HeavyWeapon |

---

## Supported Races

| Race | Bonuses |
|------|---------|
| Adret | +3 Charisma, +2 Willpower |
| Canor | +3 Strength, +2 Charisma |
| Capra | +3 Intelligence, +2 Willpower |
| Celtor | +3 Charisma, +2 Intelligence |
| Chrysid | +3 Charisma, +2 Agility |
| Etrean | +3 Intelligence, +2 Agility |
| Felinor | +3 Agility, +2 Charisma |
| Ganymede | +3 Willpower, +2 Intelligence |
| Gremor | +3 Fortitude, +2 Strength |
| Khan | +3 Strength, +2 Agility |
| Kiron | +3 Agility, +2 Intelligence |
| Tiran | +3 Agility, +2 Willpower |
| Vesperian | +3 Fortitude, +2 Willpower |
| Lightborn | +2 to all base stats |
| Drakkard | +3 Agility, +2 Fortitude |
| None | No bonuses |

---

## How Shrine of Order Works

Shrine of Order **evenly redistributes** all your invested stat points across every stat you've put points into.

- **Base stats** cannot drop by more than **25 points** from their pre-shrine value.
- **Attunements** (Flamecharm, Frostdraw, Thundercall, Galebreathe, Shadowcast, Ironsing, Bloodrend) are **exempt** from the −25 reduction cap and can be reduced freely.
- **Weapon stats** follow the same −25 cap as base stats.

The bot handles the math, racial bonuses, and 330-point budget cap automatically.

---

## Tech

- `discord.py` with app commands (slash commands)
- `rapidfuzz` for typo-tolerant race matching
- Hosted on Replit with `keep_alive` ping monitor
