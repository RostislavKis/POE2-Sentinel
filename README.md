# 🛡️ POE2 Sentinel

A feature-rich companion tool for Path of Exile 2 with auto flask bot, terrain overlay, and map reveal features.

> 🌐 Languages: **English** · [Русский](README.ru.md)

## Features

- **Flask Bot** - Automatically uses flasks when HP/Mana drops below threshold
  - **Structure Mode** (Recommended) - Auto-updates across game patches!
  - **Memory Mode** - Fast pointer-chain reading
  - **OCR Mode** - Screen capture fallback
- **Terrain Overlay** - Transparent radar showing map layout, monsters, NPCs, and chests
- **Atlas Fog Reveal** - Toggle map fog of war
- **Shader Reveal** - Permanent minimap visibility (requires game restart)
- **Auto Updates** - Automatically checks for and installs new versions

## Requirements

- Windows 10/11 (64-bit)
- Path of Exile 2 (Steam version)
- **Run as Administrator** (required for memory reading)
- .NET Runtime (only for Shader Reveal feature)

## Quick Start

1. Launch POE2 and enter the game
2. Run `POE2Sentinel.exe` as Administrator
3. Select detection mode (Structure recommended)
4. Adjust thresholds as needed
5. Click **START**

## Hotkeys

| Key | Function |
|-----|----------|
| F9  | Toggle Flask Bot |
| F10 | Toggle Terrain Overlay |
| F11 | Toggle Atlas Fog Reveal |

*Hotkeys can be rebound in Settings*

## Detection Modes

| Mode | Description |
|------|-------------|
| **Structure** | Uses AOB scanning - survives game patches! |
| Memory | Fast pointer chains - may break after patches |
| OCR | Screen capture fallback - always works |

## Building from Source

```powershell
# Install dependencies
pip install -r requirements.txt

# Run directly
py gui.py

# Build executable
py build/build_exe.py
```

## Project Structure

```
POE2-Sentinel/
├── gui.py              # Main application
├── flask_bot.py        # Flask bot logic + memory reading
├── terrain_reader.py   # Terrain/entity memory reading
├── map_overlay.py      # PyQt5 overlay window
├── map_shader_patch.py # Shader modification
├── build/              # Build scripts
├── tests/              # Unit tests
└── libggpk/            # .NET libraries for shader patch
```

## Configuration

Settings are stored in `config.json`. Copy `config.example.json` to get started.

Key settings:
- `detection_mode`: "structure", "memory", or "ocr"
- `life.threshold_percent`: HP threshold for flask trigger
- `life.pool_type`: "hp", "es", or "combined" (for ES builds)

## Disclaimer

This tool reads game memory. Use at your own risk. The developers are not responsible for any bans or issues.

## License

MIT License - See LICENSE file

## Credits

- Created by Ace047
- Inspired by [POE2Radar](https://github.com/Sikaka/POE2Radar)
