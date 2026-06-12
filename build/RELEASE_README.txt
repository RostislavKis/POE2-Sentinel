================================================================================
                          POE2 SENTINEL v1.0.0
================================================================================

A memory-based auto flask bot for Path of Exile 2 with a terrain/entity radar
overlay, atlas fog reveal, and a permanent minimap Shader Reveal.

FEATURES:
---------
- Flask Bot: Structure-based HP/Mana reading that auto-updates across patches!
  Also supports Memory pointer chains and OCR screen-capture as fallbacks.
- Entity Overlay: Transparent radar showing terrain layout, player, and
  monster/NPC dots (toggle categories in the Overlay panel)
- Atlas Fog Reveal: Toggles atlas/map fog of war
- Shader Reveal: Permanently reveals the minimap layout by patching the game's
  shader bundle (Map Tools panel; requires the game closed to apply/remove)
- Configurable life/mana thresholds and rebindable hotkeys
- Modern dark-themed GUI

REQUIREMENTS:
-------------
- Windows 10/11 (64-bit)
- Path of Exile 2 (Steam version)
- Run as Administrator (required for memory reading)
- Shader Reveal only: the .NET runtime on the PC. If it's missing, every other
  feature still works and Shader Reveal simply reports it can't run.

QUICK START:
------------
1. Launch POE2 and enter the game
2. Run POE2Sentinel.exe as Administrator
3. Adjust life/mana thresholds as needed
4. Click START to begin monitoring
5. Use the hotkeys below to toggle the overlay / atlas fog

DETECTION MODES:
----------------
Structure (Recommended):
  - Uses AOB scanning to find game structures automatically
  - Works across game patches without manual pointer updates!
  - Supports HP, ES (Energy Shield), and combined pools

Memory:
  - Fastest detection, works even when game is minimized
  - May break after game patches (pointer chains change)

OCR (Fallback):
  - Uses screen capture to read HP/Mana values
  - More reliable after patches but requires game window visible
  - Use Tools > Set Life/Mana Region to configure capture areas

HOTKEYS (default - rebindable in Settings > Hotkeys):
-----------------------------------------------------
F9  - Start/Stop the flask bot
F10 - Toggle the entity overlay
F11 - Toggle atlas fog reveal

TROUBLESHOOTING:
----------------
- "Game not running": Make sure POE2 is running before starting the bot
- HP/Mana shows 0: Try Structure mode first, or switch to OCR mode
- OCR not working: Use Tools > Set Life/Mana Region to configure capture areas
- Overlay won't show: Run as Administrator and confirm you're in a zone
- Shader Reveal fails: Close POE2 before applying/removing; it also needs the
  .NET runtime installed on the PC

DISCLAIMER:
-----------
This tool modifies game memory. Use at your own risk.
The developers are not responsible for any bans or issues.

================================================================================
                          Created by Ace047
================================================================================
