# Terrain Overlay Implementation Plan

## Overview

Build a **read-only** terrain overlay that displays the full map layout on top of POE2, similar to POE2Radar. This approach is more ethical than memory patching - we only READ data, never modify game code.

> **Decision**: Using **Python + PyQt5** to keep everything in one unified codebase.
> C# would be slightly better for overlay performance, but Python is good enough
> and keeps the entire bot in a single application.

---

## Architecture

```
┌─────────────────────────────────────┐
│  Transparent Overlay Window (PyQt5) │  ← Our overlay
│  - Draws terrain grid               │
│  - Click-through, always on top     │
├─────────────────────────────────────┤
│  POE2 Game Window                   │  ← Game underneath
└─────────────────────────────────────┘
```

---

## Components to Build

| # | Component | File | Description |
|---|-----------|------|-------------|
| 1 | AOB Scanner | `terrain_reader.py` | Find GameState root via pattern scan |
| 2 | Pointer Resolver | `terrain_reader.py` | Follow pointer chain to terrain data |
| 3 | Grid Parser | `terrain_reader.py` | Unpack walkable grid (nibble format) |
| 4 | Overlay Window | `map_overlay.py` | Transparent PyQt5 window |
| 5 | Coordinate Transform | `map_overlay.py` | Grid → World → Screen coords |
| 6 | Renderer | `map_overlay.py` | Draw terrain dots/lines |
| 7 | GUI Integration | `gui.py` | Toggle button + hotkey |

---

## Implementation Steps

### Phase 1: Memory Reading (Day 1, ~30 min)

**Step 1.1: Use POE2Radar's AOB Pattern**
- Copy the AOB pattern directly from POE2Radar source code
- No manual Cheat Engine work needed!
- Implement pattern scanner in Python using pymem

**Step 1.2: Implement Pointer Chain**
```
GameState (AOB scan result)
  └─→ InGameState (offset 0x30)
        └─→ AreaInstance (offset 0xF8)
              └─→ TerrainMetadata (offset 0x8A0)
                    └─→ GridWalkableData (offset 0xD0)
```

**Step 1.3: Read Grid Data**
- Grid is packed as nibbles (4 bits per cell)
- BytesPerRow at offset 0x130
- TotalTiles at offset 0x18
- Each nibble: 0 = wall, 1+ = walkable

### Phase 2: Overlay Window (Day 1, ~1.5 hours)

**Step 2.1: Create PyQt5 Transparent Window**
```python
# Key flags for overlay:
Qt.WindowStaysOnTopHint      # Always on top
Qt.FramelessWindowHint       # No title bar
Qt.Tool                      # Not in taskbar
Qt.WA_TranslucentBackground  # Transparent
Qt.WA_TransparentForMouseEvents  # Click-through
```

**Step 2.2: Position Over Game Window**
- Use win32gui to find POE2 window rect
- Match overlay size and position to game window
- Handle window resize/move events

**Step 2.3: Render Loop**
- 30-60 FPS update loop
- Read terrain data each frame
- Draw walkable cells as colored dots

### Phase 3: Coordinate System (Day 2, ~30 min)

**Step 3.1: Grid to World Coordinates**
```python
world_x = grid_x * tile_size
world_y = grid_y * tile_size
```

**Step 3.2: World to Screen Coordinates**
- Read camera matrix from game memory
- Apply perspective transformation
- Map to overlay window coordinates

### Phase 4: Integration (Day 2, ~30 min)

**Step 4.1: GUI Toggle**
- Add "Terrain Overlay" checkbox in GUI
- Hotkey to toggle (e.g., F9)

**Step 4.2: Settings**
- Overlay opacity
- Dot size
- Color scheme (walkable vs walls)

---

## Key Offsets (from POE2Radar)

```python
class Poe2Offsets:
    # From GameState
    InGameState = 0x30
    
    # From InGameState  
    AreaInstance = 0xF8
    
    # From AreaInstance
    TerrainMetadata = 0x8A0
    
    # From TerrainMetadata
    GridWalkableData = 0xD0
    GridLandscapeData = 0xE8
    BytesPerRow = 0x130
    TotalTiles = 0x18
```

---

## Dependencies to Add

```
PyQt5>=5.15.0    # For transparent overlay window
```

---

## Time Estimate

| Phase | Task | Time |
|-------|------|------|
| 1.1 | Copy AOB + Implement Scanner | 15 min |
| 1.2 | Pointer Chain | 15 min |
| 1.3 | Grid Parser | 10 min |
| 2.1 | PyQt5 Window | 45 min |
| 2.2 | Window Positioning | 20 min |
| 2.3 | Render Loop | 30 min |
| 3 | Coordinate Transform | 30 min |
| 4 | GUI Integration | 15 min |
| **Total** | | **~3 hours** |

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `terrain_reader.py` | Expand (already started) |
| `map_overlay.py` | Create new |
| `gui.py` | Add toggle button |
| `requirements.txt` | Add PyQt5 |

---

## Notes

- **Ethical Approach**: Read-only memory access, no game modification
- **Reference Code**: [POE2Radar](https://github.com/Sikaka/POE2Radar)
- **Alternative**: Keep using `41 80 7F 58 00` patch if overlay is too complex

---

## Why Python (Not C#)

| Consideration | Decision |
|---------------|----------|
| **Unified codebase** | ✅ Everything stays in one app |
| **Overlay quality** | Good enough (30fps is fine for map) |
| **Maintenance** | ✅ One language to maintain |
| **User experience** | ✅ Single app, single config |

**Trade-offs accepted:**
- Slightly higher CPU usage than C#/Direct2D
- May need to limit to 30fps instead of 60fps
- PyQt5 adds ~50MB to app size

---

## Implementation Checklist

- [x] **Step 1**: Copy AOB pattern from POE2Radar source code ✅
- [x] **Step 2**: Implement AOB scanner + pointer chain in Python ✅
- [x] **Step 3**: Create basic PyQt5 transparent window ✅
- [x] **Step 4**: Read and draw terrain grid ✅
- [x] **Step 5**: Add coordinate transformation ✅
- [x] **Step 6**: Integrate with GUI (toggle button) ✅
- [x] **Step 7**: Unit tests ✅ (31 tests passing)

> **Status**: Implementation complete! Ready for testing with POE2.

---

## Quick Start / Testing

```powershell
# Install dependencies
pip install PyQt5 pytest

# Run unit tests
py run_tests.py

# Test terrain reader (requires POE2 running)
py terrain_reader.py

# Test overlay window (demo mode)
py map_overlay.py

# Run the full GUI
py gui.py
```

---

## Files Created

| File | Description |
|------|-------------|
| `terrain_reader.py` | AOB scanner, pointer chain, terrain data reading |
| `map_overlay.py` | PyQt5 transparent overlay, coordinate transformer |
| `tests/test_terrain_reader.py` | Unit tests for terrain reader |
| `tests/test_map_overlay.py` | Unit tests for overlay |
| `run_tests.py` | Test runner script |

---

## Hotkeys

| Key | Function |
|-----|----------|
| F9 | Toggle Map Reveal (memory patch) |
| F10 | Toggle Atlas Fog (memory patch) |
| **F11** | **Toggle Terrain Overlay (read-only)** |

---

*Created: 2026-06-06*
*Status: ✅ Implementation Complete*
*Approach: Python + PyQt5 (unified codebase)*
*Tests: 31 passing*
