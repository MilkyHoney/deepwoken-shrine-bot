# 🏛️ Deepwoken Shrine Bot

A Discord bot that simulates the **Shrine of Order** mechanic from [Deepwoken](https://www.roblox.com/games/4111023553/Deepwoken). Give it your pre-shrine build and it instantly calculates your post-shrine stats. I plan on making it an automatic builder.

---

## Commands

| Command | Description |
|--------|-------------|
| `?shrine <race> <stats> [points_left=N]` | Simulate Shrine of Order on your build |
| `?races` | List all races and their stat bonuses |
| `?help` | Show usage instructions |

### Example
```
?shrine khan str=40 fort=50 agi=25 will=40 cha=55 light=1 flame=100
```

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

Shrine of Order evenly redistributes all your invested stat points across every stat you've put points into. Non-attunement stats cannot be reduced by more than **25 points**. Attunements (Flamecharm, Frostdraw, etc.) are exempt from this cap and can be reduced freely.
