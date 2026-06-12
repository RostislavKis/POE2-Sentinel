"""
Map Overlay Module - Transparent overlay window for displaying terrain data.

Uses PyQt5 for the transparent, click-through overlay window.
Draws terrain grid on top of the game window.
"""

import sys
import logging
import ctypes
from typing import Optional, Tuple, List
from dataclasses import dataclass
import struct

# PyQt5 imports
try:
    from PyQt5.QtWidgets import QApplication, QWidget, QMainWindow, QDesktopWidget
    from PyQt5.QtCore import Qt, QTimer, QPoint, QRect
    from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QImage
    PYQT5_AVAILABLE = True
except ImportError:
    PYQT5_AVAILABLE = False
    print("PyQt5 not installed. Run: pip install PyQt5")
    # Define stubs so the code can be parsed
    QImage = None

# Win32 imports for window handling
try:
    import win32gui
    import win32con
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

from terrain_reader import TerrainReader, TerrainData, Poe2Offsets, EntityDot, EntityCategory, Rarity

logger = logging.getLogger(__name__)


@dataclass
class CameraData:
    """Camera transformation data."""
    matrix: List[float]  # 4x4 matrix (16 floats)
    zoom: float


def hex_to_rgba(hex_color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    """Convert hex color string to RGBA tuple."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (r, g, b, alpha)
    return (0x50, 0x64, 0x82, alpha)  # Default fallback


@dataclass
class OverlayConfig:
    """Configuration for the overlay - matches POE2Radar styling."""
    # Terrain colors (POE2Radar style)
    # Interior: #506482 @ 11.8% opacity (30/255)
    # Edge: #3CDCFF @ 70.6% opacity (180/255)
    interior_color: Tuple[int, int, int, int] = (0x50, 0x64, 0x82, 30)    # Dark bluish, low opacity
    edge_color: Tuple[int, int, int, int] = (0x3C, 0xDC, 0xFF, 180)       # Cyan, brighter
    player_color: Tuple[int, int, int, int] = (0x4D, 0xF2, 0xFF, 255)     # Cyan, solid (POE2Radar player)

    def to_dict(self) -> dict:
        """Convert config to dict for multiprocessing."""
        return {
            'interior_color': self.interior_color,
            'edge_color': self.edge_color,
            'player_color': self.player_color,
            'monster_normal_color': self.monster_normal_color,
            'monster_magic_color': self.monster_magic_color,
            'monster_rare_color': self.monster_rare_color,
            'monster_unique_color': self.monster_unique_color,
            'npc_color': self.npc_color,
            'chest_color': self.chest_color,
            'transition_color': self.transition_color,
            'show_entities': self.show_entities,
            'show_monsters': self.show_monsters,
            'show_npcs': self.show_npcs,
            'show_chests': self.show_chests,
            'show_transitions': self.show_transitions,
            'show_friendly': self.show_friendly,
            'show_normal_monsters': self.show_normal_monsters,
            'show_magic_monsters': self.show_magic_monsters,
            'show_rare_monsters': self.show_rare_monsters,
            'show_unique_monsters': self.show_unique_monsters,
            'monster_size': self.monster_size,
            'npc_size': self.npc_size,
            'chest_size': self.chest_size,
            'transition_size': self.transition_size,
            'update_interval': self.update_interval,
            'entity_poll_interval': self.entity_poll_interval,
            'max_repaint_fps': self.max_repaint_fps,
            'show_player': self.show_player,
            'show_terrain': self.show_terrain,
            'scale_mul': self.scale_mul,
            'offset_x': self.offset_x,
            'offset_y': self.offset_y,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'OverlayConfig':
        """Create config from dict (for multiprocessing)."""
        return cls(
            interior_color=tuple(d.get('interior_color', (0x50, 0x64, 0x82, 30))),
            edge_color=tuple(d.get('edge_color', (0x3C, 0xDC, 0xFF, 180))),
            player_color=tuple(d.get('player_color', (0x4D, 0xF2, 0xFF, 255))),
            monster_normal_color=tuple(d.get('monster_normal_color', (0xFF, 0x00, 0x00, 200))),
            monster_magic_color=tuple(d.get('monster_magic_color', (0x00, 0x00, 0xFF, 220))),
            monster_rare_color=tuple(d.get('monster_rare_color', (0xFF, 0xFF, 0x00, 220))),
            monster_unique_color=tuple(d.get('monster_unique_color', (0xFF, 0xA5, 0x00, 255))),
            npc_color=tuple(d.get('npc_color', (0x00, 0xFF, 0x00, 200))),
            chest_color=tuple(d.get('chest_color', (0xFF, 0xD7, 0x00, 200))),
            transition_color=tuple(d.get('transition_color', (0x00, 0xFF, 0xFF, 200))),
            show_entities=d.get('show_entities', True),
            show_monsters=d.get('show_monsters', True),
            show_npcs=d.get('show_npcs', True),
            show_chests=d.get('show_chests', True),
            show_transitions=d.get('show_transitions', True),
            show_friendly=d.get('show_friendly', False),
            show_normal_monsters=d.get('show_normal_monsters', True),
            show_magic_monsters=d.get('show_magic_monsters', True),
            show_rare_monsters=d.get('show_rare_monsters', True),
            show_unique_monsters=d.get('show_unique_monsters', True),
            monster_size=d.get('monster_size', 4),
            npc_size=d.get('npc_size', 5),
            chest_size=d.get('chest_size', 4),
            transition_size=d.get('transition_size', 6),
            update_interval=d.get('update_interval', 16),
            entity_poll_interval=d.get('entity_poll_interval', 2),
            max_repaint_fps=d.get('max_repaint_fps', 45),
            show_player=d.get('show_player', True),
            show_terrain=d.get('show_terrain', True),
            scale_mul=d.get('scale_mul', 1.0),
            offset_x=d.get('offset_x', 0.0),
            offset_y=d.get('offset_y', 0.0),
            width=d.get('width', 1920),
            height=d.get('height', 1080),
        )

    # Entity colors (based on POE2Radar defaults)
    monster_normal_color: Tuple[int, int, int, int] = (0xFF, 0x00, 0x00, 200)   # Red - normal monsters
    monster_magic_color: Tuple[int, int, int, int] = (0x00, 0x00, 0xFF, 220)    # Blue - magic monsters
    monster_rare_color: Tuple[int, int, int, int] = (0xFF, 0xFF, 0x00, 220)     # Yellow - rare monsters
    monster_unique_color: Tuple[int, int, int, int] = (0xFF, 0xA5, 0x00, 255)   # Orange - unique/boss
    npc_color: Tuple[int, int, int, int] = (0x00, 0xFF, 0x00, 200)              # Green - NPCs
    chest_color: Tuple[int, int, int, int] = (0xFF, 0xD7, 0x00, 200)            # Gold - chests
    transition_color: Tuple[int, int, int, int] = (0x00, 0xFF, 0xFF, 200)       # Cyan - transitions/portals

    # Entity visibility
    show_entities: bool = True
    show_monsters: bool = True
    show_npcs: bool = True
    show_chests: bool = True
    show_transitions: bool = True
    show_friendly: bool = False  # Friendly monsters (minions, etc)

    # Monster rarity filters
    show_normal_monsters: bool = True
    show_magic_monsters: bool = True
    show_rare_monsters: bool = True
    show_unique_monsters: bool = True

    # Entity rendering sizes
    monster_size: int = 4        # Radius in pixels
    npc_size: int = 5
    chest_size: int = 4
    transition_size: int = 6

    # Rendering
    update_interval: int = 16    # ~60 FPS — smooth radar without starving the game's GPU
    entity_poll_interval: int = 2  # Read entities every Nth frame (~30 Hz at 60 FPS)
    max_repaint_fps: int = 45    # Cap actual repaints (compositor passes) while moving
    show_player: bool = True
    show_terrain: bool = True

    # Calibration (can be adjusted with hotkeys like POE2Radar)
    scale_mul: float = 1.0       # Overall scale multiplier
    offset_x: float = 0.0        # X offset in pixels
    offset_y: float = 0.0        # Y offset in pixels

    # Window size (used by multiprocessing startup)
    width: int = 1920
    height: int = 1080

    @classmethod
    def from_config_dict(cls, config_dict: dict) -> 'OverlayConfig':
        """Create OverlayConfig from a config dictionary (loaded from JSON)."""
        overlay_cfg = config_dict.get("overlay", {})

        interior_hex = overlay_cfg.get("interior_color", "#506482")
        edge_hex = overlay_cfg.get("edge_color", "#3CDCFF")
        player_hex = overlay_cfg.get("player_color", "#4DF2FF")

        # Entity colors from config
        monster_normal_hex = overlay_cfg.get("monster_normal_color", "#FF0000")
        monster_magic_hex = overlay_cfg.get("monster_magic_color", "#0000FF")
        monster_rare_hex = overlay_cfg.get("monster_rare_color", "#FFFF00")
        monster_unique_hex = overlay_cfg.get("monster_unique_color", "#FFA500")
        npc_hex = overlay_cfg.get("npc_color", "#00FF00")
        chest_hex = overlay_cfg.get("chest_color", "#FFD700")
        transition_hex = overlay_cfg.get("transition_color", "#00FFFF")

        # Entity visibility flags
        show_entities = overlay_cfg.get("show_entities", True)
        show_monsters = overlay_cfg.get("show_monsters", True)
        show_npcs = overlay_cfg.get("show_npcs", True)
        show_chests = overlay_cfg.get("show_chests", True)
        show_transitions = overlay_cfg.get("show_transitions", True)
        show_friendly = overlay_cfg.get("show_friendly", False)

        # Monster rarity filters
        show_normal_monsters = overlay_cfg.get("show_normal_monsters", True)
        show_magic_monsters = overlay_cfg.get("show_magic_monsters", True)
        show_rare_monsters = overlay_cfg.get("show_rare_monsters", True)
        show_unique_monsters = overlay_cfg.get("show_unique_monsters", True)

        return cls(
            interior_color=hex_to_rgba(interior_hex, alpha=30),
            edge_color=hex_to_rgba(edge_hex, alpha=180),
            player_color=hex_to_rgba(player_hex, alpha=255),
            monster_normal_color=hex_to_rgba(monster_normal_hex, alpha=200),
            monster_magic_color=hex_to_rgba(monster_magic_hex, alpha=220),
            monster_rare_color=hex_to_rgba(monster_rare_hex, alpha=220),
            monster_unique_color=hex_to_rgba(monster_unique_hex, alpha=255),
            npc_color=hex_to_rgba(npc_hex, alpha=200),
            chest_color=hex_to_rgba(chest_hex, alpha=200),
            transition_color=hex_to_rgba(transition_hex, alpha=200),
            show_entities=show_entities,
            show_monsters=show_monsters,
            show_npcs=show_npcs,
            show_chests=show_chests,
            show_transitions=show_transitions,
            show_friendly=show_friendly,
            show_normal_monsters=show_normal_monsters,
            show_magic_monsters=show_magic_monsters,
            show_rare_monsters=show_rare_monsters,
            show_unique_monsters=show_unique_monsters,
        )


class CoordinateTransformer:
    """Transforms between grid, world, and screen coordinates."""
    
    def __init__(self, terrain_reader: TerrainReader):
        self.reader = terrain_reader
        self._camera_matrix: Optional[List[float]] = None
        self._zoom: float = 1.0
    
    def update_camera(self) -> bool:
        """Read camera matrix from game memory."""
        igs = self.reader.find_ingame_state()
        if not igs:
            return False
        
        # Camera at InGameState + 0x368
        camera_ptr = self.reader._read_ptr(igs + Poe2Offsets.InGameState.CAMERA)
        if not camera_ptr:
            return False
        
        # Read 4x4 matrix (16 floats = 64 bytes)
        matrix_data = self.reader._read_bytes(
            camera_ptr + Poe2Offsets.Camera.WORLD_TO_SCREEN_MATRIX, 
            64
        )
        if not matrix_data:
            return False
        
        # Unpack 16 floats
        self._camera_matrix = list(struct.unpack('<16f', matrix_data))
        
        # Read zoom
        zoom = self.reader._read_float(camera_ptr + Poe2Offsets.Camera.ZOOM)
        if zoom:
            self._zoom = zoom
        
        return True
    
    def grid_to_world(self, grid_x: int, grid_y: int) -> Tuple[float, float, float]:
        """Convert grid coordinates to world coordinates."""
        # World = Grid * WorldToGridRatio
        world_x = grid_x * Poe2Offsets.WORLD_TO_GRID_RATIO
        world_y = grid_y * Poe2Offsets.WORLD_TO_GRID_RATIO
        world_z = 0.0  # Assume ground level
        return (world_x, world_y, world_z)
    
    def world_to_screen(self, world_x: float, world_y: float, world_z: float) -> Optional[Tuple[int, int]]:
        """Transform world coordinates to screen coordinates using camera matrix."""
        if not self._camera_matrix:
            return None
        
        m = self._camera_matrix
        
        # Matrix multiplication: screen = world * M
        # Row-major 4x4 matrix
        w = m[3] * world_x + m[7] * world_y + m[11] * world_z + m[15]
        
        if abs(w) < 0.001:  # Avoid division by zero
            return None
        
        x = (m[0] * world_x + m[4] * world_y + m[8] * world_z + m[12]) / w
        y = (m[1] * world_x + m[5] * world_y + m[9] * world_z + m[13]) / w
        
        return (int(x), int(y))
    
    def grid_to_screen(self, grid_x: int, grid_y: int) -> Optional[Tuple[int, int]]:
        """Convert grid coordinates directly to screen coordinates."""
        world = self.grid_to_world(grid_x, grid_y)
        return self.world_to_screen(*world)


def find_game_window() -> Optional[Tuple[int, int, int, int]]:
    """Find POE2 game window and return its rect (x, y, width, height)."""
    if not WIN32_AVAILABLE:
        return None

    window_names = ["Path of Exile 2", "Path of Exile"]

    for name in window_names:
        hwnd = win32gui.FindWindow(None, name)
        if hwnd:
            rect = win32gui.GetWindowRect(hwnd)
            x, y, right, bottom = rect
            return (x, y, right - x, bottom - y)

    return None


def is_game_window_active() -> bool:
    """Check if POE2 game window is the active/foreground window."""
    if not WIN32_AVAILABLE:
        return True  # Assume active if we can't check

    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return False

        title = win32gui.GetWindowText(hwnd)
        return title in ["Path of Exile 2", "Path of Exile"]
    except Exception:
        return False


if PYQT5_AVAILABLE:
    class TerrainRenderer:
        """Renders terrain bitmap matching POE2Radar style.

        POE2Radar draws the terrain as:
        - Interior cells (walkable, not at edge): faint wash color
        - Edge cells (walkable, adjacent to blocked): brighter outline
        - Blocked cells: transparent (shows through to game map)
        """

        def __init__(self, config: OverlayConfig):
            self.config = config
            self._cached_image: Optional[QImage] = None
            self._cached_terrain_hash: Optional[int] = None
            self._cached_width: int = 0
            self._cached_height: int = 0

        def _is_edge_cell(self, terrain: TerrainData, x: int, y: int) -> bool:
            """Check if a walkable cell is at the edge (adjacent to blocked)."""
            # Check all 8 neighbors
            for dy in range(-1, 2):
                ny = y + dy
                if ny < 0 or ny >= terrain.height:
                    return True  # At grid boundary = edge
                for dx in range(-1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    nx = x + dx
                    if nx < 0 or nx >= terrain.width:
                        return True  # At grid boundary = edge
                    if not terrain.is_walkable(nx, ny):
                        return True  # Adjacent to blocked cell = edge
            return False

        def _build_terrain_image(self, terrain: TerrainData) -> QImage:
            """Build RGBA image of the terrain bitmap."""
            import time
            t0 = time.time()

            w, h = terrain.width, terrain.height

            # Create image with alpha channel
            image = QImage(w, h, QImage.Format_ARGB32)
            image.fill(Qt.transparent)

            interior_color = QColor(*self.config.interior_color)
            edge_color = QColor(*self.config.edge_color)

            # Draw each cell
            for y in range(h):
                for x in range(w):
                    if terrain.is_walkable(x, y):
                        if self._is_edge_cell(terrain, x, y):
                            image.setPixelColor(x, y, edge_color)
                        else:
                            image.setPixelColor(x, y, interior_color)
                    # Blocked cells stay transparent

            t1 = time.time()
            print(f"[TERRAIN] Built image {w}x{h} in {(t1-t0)*1000:.0f}ms")

            return image

        def get_terrain_image(self, terrain: TerrainData) -> QImage:
            """Get terrain image (cached)."""
            # Simple hash based on dimensions (area changes = new image)
            terrain_hash = hash((terrain.width, terrain.height, terrain.tiles_x, terrain.tiles_y))

            if (self._cached_image is None or
                self._cached_terrain_hash != terrain_hash or
                self._cached_width != terrain.width or
                self._cached_height != terrain.height):

                self._cached_image = self._build_terrain_image(terrain)
                self._cached_terrain_hash = terrain_hash
                self._cached_width = terrain.width
                self._cached_height = terrain.height

            return self._cached_image

        # POE2 camera angle constants (from POE2Radar MapProjection.cs)
        CAMERA_ANGLE_RAD = 38.7 * 3.14159265 / 180.0
        CAMERA_COS = 0.7804  # cos(38.7°)
        CAMERA_SIN = 0.6252  # sin(38.7°)

        def render_terrain(self, terrain: TerrainData, painter: QPainter,
                           center: Tuple[float, float], scale: float,
                           player_grid_pos: Optional[Tuple[float, float]] = None):
            """Render terrain aligned with the game map using POE2's isometric projection.

            Args:
                terrain: The terrain data to render
                painter: QPainter to draw with
                center: Screen position of the map center (where player is)
                scale: Map zoom scale
                player_grid_pos: Player's position in grid coordinates
            """
            cx, cy = center

            # Terrain wash/edges are optional. Draw them only when enabled; the
            # player marker below is always drawn so it stays a usable reference
            # point even when the terrain layer is disabled (entity-icons-only mode).
            if terrain and self.config.show_terrain:
                # Get or build terrain image
                terrain_image = self.get_terrain_image(terrain)

                # Calculate player position
                if player_grid_pos:
                    player_gx, player_gy = player_grid_pos
                else:
                    player_gx = terrain.width / 2
                    player_gy = terrain.height / 2

                # POE2Radar's isometric projection formula:
                # screen_x = scale * (grid_delta_x - grid_delta_y) * cos(38.7°)
                # screen_y = scale * (0 - (grid_delta_x + grid_delta_y)) * sin(38.7°)

                # For the terrain bitmap, we need to transform it using the same projection
                # Calculate transformation matrix for isometric view

                # Project terrain corner points relative to player
                # (0,0) corner
                dx0, dy0 = 0 - player_gx, 0 - player_gy
                p00_x = cx + scale * (dx0 - dy0) * self.CAMERA_COS
                p00_y = cy + scale * (-(dx0 + dy0)) * self.CAMERA_SIN

                # (width, 0) corner
                dx1, dy1 = terrain.width - player_gx, 0 - player_gy
                p10_x = cx + scale * (dx1 - dy1) * self.CAMERA_COS
                p10_y = cy + scale * (-(dx1 + dy1)) * self.CAMERA_SIN

                # (0, height) corner
                dx2, dy2 = 0 - player_gx, terrain.height - player_gy
                p01_x = cx + scale * (dx2 - dy2) * self.CAMERA_COS
                p01_y = cy + scale * (-(dx2 + dy2)) * self.CAMERA_SIN

                # Calculate the transformation matrix from the projected corners
                # ex = (p10 - p00) / width, ey = (p01 - p00) / height
                ex_x = (p10_x - p00_x) / terrain.width
                ex_y = (p10_y - p00_y) / terrain.width
                ey_x = (p01_x - p00_x) / terrain.height
                ey_y = (p01_y - p00_y) / terrain.height

                # Save painter state
                painter.save()
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

                # Apply transformation: Transform = [ex_x, ex_y, ey_x, ey_y, p00_x, p00_y]
                from PyQt5.QtGui import QTransform
                transform = QTransform(ex_x, ex_y, ey_x, ey_y, p00_x, p00_y)
                painter.setTransform(transform)

                # Draw the terrain image
                painter.drawImage(0, 0, terrain_image)

                painter.restore()

            # Draw player indicator at center (independent of the terrain layer)
            if self.config.show_player:
                player_color = QColor(*self.config.player_color)
                painter.setBrush(QBrush(player_color))
                painter.setPen(QPen(Qt.black, 1))
                painter.drawEllipse(int(cx) - 4, int(cy) - 4, 8, 8)

    class OverlayWindow(QWidget):
        """Full-screen transparent overlay that aligns with the game map."""

        def __init__(self, terrain_reader: TerrainReader, config: Optional[OverlayConfig] = None):
            super().__init__()

            self.reader = terrain_reader
            self.config = config or OverlayConfig()
            self.transformer = CoordinateTransformer(terrain_reader)
            self.renderer = TerrainRenderer(self.config)

            self._terrain: Optional[TerrainData] = None
            self._player_grid_pos: Optional[Tuple[float, float]] = None
            self._smooth_player_pos: Optional[Tuple[float, float]] = None  # Smoothed position
            self._game_rect: Optional[Tuple[int, int, int, int]] = None
            self._map_visible: bool = True  # Assume map is open
            self._map_shift_x: float = 0.0  # Map pan offset from arrows
            self._map_shift_y: float = 0.0  # Map pan offset from arrows
            self._map_zoom: float = 0.5     # Map zoom level
            self._world_update_counter: int = 0  # For throttling slow updates
            self._entity_poll_counter: int = 0   # For throttling entity reads
            self._last_paint_sig = None          # Last rendered frame signature
            self._paint_dirty: bool = False      # A visible change awaits painting
            self._last_paint_time: float = 0.0   # perf_counter of last actual repaint
            self._entities: List[EntityDot] = []  # Entity list for radar

            # Pre-load data immediately so overlay shows instantly
            self._preload_data()

            self._setup_window()
            self._setup_timer()
            self._setup_hotkeys()

        def _preload_data(self):
            """Pre-load terrain and player position for instant display."""
            try:
                # Get game window
                self._game_rect = find_game_window()

                # Read terrain immediately
                self._terrain = self.reader.read_terrain()

                # Get player position
                if self._terrain:
                    player_pos = self.reader.get_player_grid_position()
                    if player_pos:
                        self._player_grid_pos = player_pos
                        self._smooth_player_pos = player_pos
                    else:
                        # Center of map as fallback
                        self._player_grid_pos = (self._terrain.width / 2, self._terrain.height / 2)
                        self._smooth_player_pos = self._player_grid_pos

                # Get map state
                map_state = self.reader.get_map_state()
                if map_state:
                    is_visible, shift_x, shift_y, zoom = map_state
                    self._map_visible = is_visible
                    self._map_shift_x = shift_x
                    self._map_shift_y = shift_y
                    self._map_zoom = zoom

                # Pre-load entities
                if self.config.show_entities:
                    self._entities = self.reader.get_entities()

            except Exception as e:
                logger.debug(f"Preload error (non-fatal): {e}")

        def _setup_window(self):
            """Configure window as full-screen transparent overlay."""
            # Window flags for transparent, click-through overlay
            self.setWindowFlags(
                Qt.FramelessWindowHint |
                Qt.WindowStaysOnTopHint |
                Qt.Tool |
                Qt.WindowTransparentForInput
            )

            # Enable transparency
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            # Start with screen size (will resize to game window)
            from PyQt5.QtWidgets import QDesktopWidget
            screen = QDesktopWidget().screenGeometry()
            self.resize(screen.width(), screen.height())
            self.move(0, 0)

            # Make window click-through on Windows
            if WIN32_AVAILABLE:
                hwnd = int(self.winId())
                ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(
                    hwnd,
                    win32con.GWL_EXSTYLE,
                    ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT
                )

        def _setup_timer(self):
            """Setup update timer."""
            self.update_timer = QTimer(self)
            self.update_timer.timeout.connect(self._on_update)
            self.update_timer.start(self.config.update_interval)

        def _on_update(self):
            """Called periodically to update terrain and player data.

            Runs at ~60 FPS (update_interval=16ms). Per-frame: player position,
            map visibility, entity radar. Slow path (every ~30th frame, ~2 Hz):
            terrain data and game window position.
            """
            self._world_update_counter += 1

            # Only show overlay when POE2 window is active
            if not is_game_window_active():
                self._map_visible = False
                self._maybe_repaint()
                return

            # Track last area instance to detect zone changes (like POE2Radar)
            if not hasattr(self, '_last_area_instance'):
                self._last_area_instance = None

            # get_area_instance() reads fresh every call - zone changes are auto-detected
            current_area = self.reader.get_area_instance()
            if current_area and current_area != self._last_area_instance:
                if self._last_area_instance is not None:
                    logger.info(f"Zone changed - clearing terrain")
                    self._terrain = None
                    self._entities = []
                self._last_area_instance = current_area

            # Fast path: always update player position and map state (visibility, shift, zoom)
            if self._terrain:
                player_pos = self.reader.get_player_grid_position()
                if player_pos:
                    self._player_grid_pos = player_pos
                    # Use raw position for instant response (no smoothing delay)
                    self._smooth_player_pos = player_pos

            # Get full map state including shift/zoom for arrow panning
            map_state = self.reader.get_map_state()
            if map_state:
                is_visible, shift_x, shift_y, zoom = map_state
                self._map_visible = is_visible
                self._map_shift_x = shift_x
                self._map_shift_y = shift_y
                self._map_zoom = zoom
            else:
                self._map_visible = False

            # Entity path: only read memory when the radar would actually draw
            # something, and throttle to ~15 Hz (every Nth frame). The full
            # entity-map traversal is the dominant per-frame CPU cost, and
            # monster dots don't need a 60 Hz refresh to look smooth.
            if self._entities_wanted():
                self._entity_poll_counter += 1
                if self._entity_poll_counter >= self.config.entity_poll_interval:
                    self._entity_poll_counter = 0
                    try:
                        self._entities = self.reader.get_entities()
                    except Exception as e:
                        logger.debug(f"Error reading entities: {e}")
                        self._entities = []
            elif self._entities:
                # Nothing renderable is enabled — drop any stale dots.
                self._entities = []

            # Slow path: update terrain and window every 30th frame (~2 Hz at 60 FPS)
            # BUT: read terrain immediately if we don't have any (new area or startup)
            need_terrain_now = self._terrain is None
            if self._world_update_counter >= 30 or need_terrain_now:
                if not need_terrain_now:
                    self._world_update_counter = 0

                # Update game window position
                self._game_rect = find_game_window()
                if self._game_rect:
                    game_x, game_y, game_w, game_h = self._game_rect
                    self.setGeometry(game_x, game_y, game_w, game_h)

                # Read terrain
                try:
                    new_terrain = self.reader.read_terrain()
                    if new_terrain:
                        self._terrain = new_terrain
                except Exception as e:
                    logger.debug(f"Error reading terrain: {e}")

                # Fallback player position if none available
                if not self._player_grid_pos and self._terrain:
                    self._player_grid_pos = (self._terrain.width / 2, self._terrain.height / 2)

            # Repaint only when the rendered frame actually changed.
            self._maybe_repaint()

        def _entities_wanted(self) -> bool:
            """True only if the radar would draw at least one entity type.

            Lets us skip the expensive entity-map read entirely when the user
            has toggled every category off (only the player dot is shown).
            """
            c = self.config
            if not c.show_entities:
                return False
            monsters = c.show_monsters and (
                c.show_normal_monsters or c.show_magic_monsters
                or c.show_rare_monsters or c.show_unique_monsters
            )
            return bool(monsters or c.show_npcs or c.show_chests
                        or c.show_transitions)

        def _frame_signature(self):
            """Cheap fingerprint of everything that affects the drawn frame.

            Used to skip redundant repaints (and the full-screen compositor
            cost they incur) when nothing visible has changed.
            """
            if not (self._terrain and self._map_visible):
                return (False,)
            pos = self._smooth_player_pos or self._player_grid_pos or (0.0, 0.0)
            sig = (
                True,
                id(self._terrain),
                self.width(), self.height(),
                round(self._map_shift_x), round(self._map_shift_y),
                round(self._map_zoom, 3),
                round(self.config.scale_mul, 3),
                round(self.config.offset_x), round(self.config.offset_y),
                round(pos[0], 2), round(pos[1], 2),
            )
            if self.config.show_entities and self._entities:
                # Movement-sensitive fingerprint of the rendered dots.
                sx = sy = 0
                for e in self._entities:
                    sx += int(e.grid_x)
                    sy += int(e.grid_y)
                sig += (len(self._entities), sx, sy)
            return sig

        def _maybe_repaint(self):
            """Repaint only when the frame changed, capped to max_repaint_fps.

            Repainting a full-screen transparent overlay forces a desktop
            compositor pass, so a static frame costs nothing (no change ->
            no repaint) and a moving frame is capped to limit how much GPU we
            take from the game. A throttled change is flushed on a later tick.
            """
            import time
            sig = self._frame_signature()
            if sig != self._last_paint_sig:
                self._last_paint_sig = sig
                self._paint_dirty = True
            if not self._paint_dirty:
                return
            min_interval = 1.0 / max(1, self.config.max_repaint_fps)
            now = time.perf_counter()
            if (now - self._last_paint_time) < min_interval:
                return  # throttled — a later tick flushes the latest state
            self._last_paint_time = now
            self._paint_dirty = False
            self.update()

        def paintEvent(self, event):
            """Paint the overlay."""
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)

            # Don't fill background - keep it fully transparent

            if self._terrain and self._map_visible:
                # Calculate map center position on screen
                # POE2Radar formula: center = (windowWidth * 0.5 + shiftX, windowHeight * 0.5 + shiftY - 20)
                window_w = self.width()
                window_h = self.height()

                # Map center is at screen center with shift from arrow panning
                # The -20 matches POE2Radar's default map shift
                center_x = window_w * 0.5 + self._map_shift_x + self.config.offset_x
                center_y = window_h * 0.5 + self._map_shift_y - 20 + self.config.offset_y

                # Calculate scale (POE2Radar: zoom * (windowHeight / 677) * scaleMul)
                # Use actual zoom from game UI
                base_scale = window_h / 677.0
                scale = base_scale * self.config.scale_mul * self._map_zoom

                # Render terrain using smoothed player position to reduce jitter
                render_player_pos = self._smooth_player_pos or self._player_grid_pos
                self.renderer.render_terrain(
                    self._terrain,
                    painter,
                    (center_x, center_y),
                    scale,
                    render_player_pos
                )

                # Render entities (also uses smoothed position)
                if self.config.show_entities and self._entities:
                    self._render_entities(painter, center_x, center_y, scale)

        def _setup_hotkeys(self):
            """Setup global hotkeys for calibration (POE2Radar style)."""
            try:
                import keyboard

                # Scale: Numpad + / - (key names vary by system, try common ones)
                keyboard.add_hotkey('+', lambda: self._adjust_scale(1.1))
                keyboard.add_hotkey('-', lambda: self._adjust_scale(0.9))
                # Alternative: use page up/down
                keyboard.add_hotkey('page up', lambda: self._adjust_scale(1.1))
                keyboard.add_hotkey('page down', lambda: self._adjust_scale(0.9))
                # Offset: Arrow keys with ctrl
                keyboard.add_hotkey('ctrl+up', lambda: self._adjust_offset(0, -10))
                keyboard.add_hotkey('ctrl+down', lambda: self._adjust_offset(0, 10))
                keyboard.add_hotkey('ctrl+left', lambda: self._adjust_offset(-10, 0))
                keyboard.add_hotkey('ctrl+right', lambda: self._adjust_offset(10, 0))
                # Reset: Home
                keyboard.add_hotkey('home', self._reset_calibration)

                print("Hotkeys: PageUp/Down or +/- = scale, Ctrl+Arrows = offset, Home = reset")
            except ImportError:
                print("Note: Install 'keyboard' package for calibration hotkeys")

        def _adjust_scale(self, factor: float):
            self.config.scale_mul *= factor
            print(f"Scale: {self.config.scale_mul:.2f}")

        def _adjust_offset(self, dx: float, dy: float):
            self.config.offset_x += dx
            self.config.offset_y += dy
            print(f"Offset: ({self.config.offset_x:.0f}, {self.config.offset_y:.0f})")

        def _reset_calibration(self):
            self.config.scale_mul = 1.0
            self.config.offset_x = 0.0
            self.config.offset_y = 0.0
            print("Reset to defaults")

        def _render_entities(self, painter: 'QPainter', center_x: float, center_y: float, scale: float):
            """Render entity dots on the map."""
            # Use smoothed player position for stable entity rendering
            if not self._smooth_player_pos:
                return

            player_gx, player_gy = self._smooth_player_pos

            for entity in self._entities:
                # Skip based on category filters
                if entity.category == EntityCategory.MONSTER:
                    if not self.config.show_monsters:
                        continue
                    # Skip friendly monsters unless enabled
                    if entity.is_friendly and not self.config.show_friendly:
                        continue
                    # Skip dead monsters
                    if not entity.is_alive:
                        continue
                    # Filter by monster rarity
                    if entity.rarity == Rarity.NORMAL and not self.config.show_normal_monsters:
                        continue
                    if entity.rarity == Rarity.MAGIC and not self.config.show_magic_monsters:
                        continue
                    if entity.rarity == Rarity.RARE and not self.config.show_rare_monsters:
                        continue
                    if entity.rarity == Rarity.UNIQUE and not self.config.show_unique_monsters:
                        continue
                elif entity.category == EntityCategory.NPC:
                    if not self.config.show_npcs:
                        continue
                elif entity.category == EntityCategory.CHEST:
                    if not self.config.show_chests:
                        continue
                    # Skip opened chests
                    if entity.is_opened:
                        continue
                    # Only show rare/unique chests (strongboxes)
                    # Normal and magic chests are usually not worth showing
                    if entity.rarity in (Rarity.NORMAL, Rarity.MAGIC, Rarity.NON_MONSTER):
                        # Check metadata for strongbox (always show these regardless of rarity)
                        if "Strongbox" not in entity.metadata:
                            continue
                elif entity.category == EntityCategory.TRANSITION:
                    if not self.config.show_transitions:
                        continue
                elif entity.category == EntityCategory.PLAYER:
                    # Don't render self (local player)
                    continue
                else:
                    # Skip OTHER and OBJECT categories
                    continue

                # Calculate screen position relative to player
                # Use same isometric formula as terrain rendering
                dx = entity.grid_x - player_gx
                dy = entity.grid_y - player_gy

                # POE2's isometric projection (same constants as terrain):
                # screen_x = scale * (dx - dy) * cos(38.7°)  [CAMERA_COS = 0.7804]
                # screen_y = scale * (-(dx + dy)) * sin(38.7°)  [CAMERA_SIN = 0.6252]
                CAMERA_COS = 0.7804
                CAMERA_SIN = 0.6252

                sx = center_x + scale * (dx - dy) * CAMERA_COS
                sy = center_y + scale * (-(dx + dy)) * CAMERA_SIN

                # Get color and size based on category and rarity
                color, size = self._get_entity_style(entity)

                # Draw entity shape based on rarity
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(Qt.black, 1))

                if entity.category == EntityCategory.MONSTER:
                    if entity.rarity == Rarity.UNIQUE:
                        # Draw filled star for unique/boss
                        self._draw_filled_star(painter, sx, sy, size + 3, color)
                    elif entity.rarity == Rarity.RARE:
                        # Draw filled diamond for rare
                        self._draw_filled_diamond(painter, sx, sy, size + 2, color)
                    else:
                        # Normal and Magic use circles
                        painter.drawEllipse(int(sx) - size, int(sy) - size, size * 2, size * 2)
                else:
                    # Non-monsters use circles
                    painter.drawEllipse(int(sx) - size, int(sy) - size, size * 2, size * 2)

        def _get_entity_style(self, entity: EntityDot) -> Tuple['QColor', int]:
            """Get color and size for an entity based on its category and rarity."""
            if entity.category == EntityCategory.MONSTER:
                size = self.config.monster_size
                if entity.rarity == Rarity.UNIQUE:
                    color = QColor(*self.config.monster_unique_color)
                elif entity.rarity == Rarity.RARE:
                    color = QColor(*self.config.monster_rare_color)
                elif entity.rarity == Rarity.MAGIC:
                    color = QColor(*self.config.monster_magic_color)
                else:
                    color = QColor(*self.config.monster_normal_color)
            elif entity.category == EntityCategory.NPC:
                color = QColor(*self.config.npc_color)
                size = self.config.npc_size
            elif entity.category == EntityCategory.CHEST:
                color = QColor(*self.config.chest_color)
                size = self.config.chest_size
            elif entity.category == EntityCategory.TRANSITION:
                color = QColor(*self.config.transition_color)
                size = self.config.transition_size
            else:
                color = QColor(128, 128, 128, 150)  # Gray for other
                size = 3

            return color, size

        def _draw_star(self, painter: 'QPainter', cx: float, cy: float, size: float):
            """Draw a simple 4-point star marker (outline only)."""
            # Vertical line
            painter.drawLine(int(cx), int(cy - size), int(cx), int(cy + size))
            # Horizontal line
            painter.drawLine(int(cx - size), int(cy), int(cx + size), int(cy))
            # Diagonal lines
            d = size * 0.7
            painter.drawLine(int(cx - d), int(cy - d), int(cx + d), int(cy + d))
            painter.drawLine(int(cx + d), int(cy - d), int(cx - d), int(cy + d))

        def _draw_diamond(self, painter: 'QPainter', cx: float, cy: float, size: float):
            """Draw a diamond shape marker (outline only)."""
            from PyQt5.QtGui import QPolygon
            from PyQt5.QtCore import QPoint
            points = QPolygon([
                QPoint(int(cx), int(cy - size)),
                QPoint(int(cx + size), int(cy)),
                QPoint(int(cx), int(cy + size)),
                QPoint(int(cx - size), int(cy))
            ])
            painter.drawPolygon(points)

        def _draw_filled_diamond(self, painter: 'QPainter', cx: float, cy: float, size: float, color: 'QColor'):
            """Draw a filled diamond shape for Rare monsters."""
            from PyQt5.QtGui import QPolygon, QPen, QBrush
            from PyQt5.QtCore import QPoint
            points = QPolygon([
                QPoint(int(cx), int(cy - size)),      # Top
                QPoint(int(cx + size), int(cy)),      # Right
                QPoint(int(cx), int(cy + size)),      # Bottom
                QPoint(int(cx - size), int(cy))       # Left
            ])
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.black, 1))
            painter.drawPolygon(points)

        def _draw_filled_star(self, painter: 'QPainter', cx: float, cy: float, size: float, color: 'QColor'):
            """Draw a filled 5-point star for Unique/Boss monsters."""
            import math
            from PyQt5.QtGui import QPolygon, QPen, QBrush
            from PyQt5.QtCore import QPoint

            # Create 5-pointed star
            points = []
            outer_radius = size
            inner_radius = size * 0.4

            for i in range(10):
                angle = math.pi / 2 + i * math.pi / 5  # Start from top
                radius = outer_radius if i % 2 == 0 else inner_radius
                x = cx + radius * math.cos(angle)
                y = cy - radius * math.sin(angle)  # Negative because Y grows down
                points.append(QPoint(int(x), int(y)))

            polygon = QPolygon(points)
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.black, 1))
            painter.drawPolygon(polygon)

        def start(self):
            """Show the overlay."""
            self.show()
            logger.info("Overlay started")

        def stop(self):
            """Hide the overlay."""
            self.hide()
            self.update_timer.stop()
            logger.info("Overlay stopped")
else:
    # Dummy class when PyQt5 not available
    class OverlayWindow:
        def __init__(self, *args, **kwargs):
            raise ImportError("PyQt5 is required for overlay. Run: pip install PyQt5")


class MapOverlayManager:
    """Manages the overlay lifecycle using a persistent background process.

    The overlay process stays running and is shown/hidden via IPC commands.
    This eliminates the startup delay from spawning a new process.
    """

    def __init__(self, terrain_reader: TerrainReader, config: Optional[OverlayConfig] = None):
        self.reader = terrain_reader
        self.config = config or OverlayConfig()
        self._process: Optional[any] = None
        self._command_queue: Optional[any] = None  # multiprocessing.Queue
        self._visible = False
        self._process_started = False

    def update_config(self, config: OverlayConfig):
        """Update the overlay configuration."""
        self.config = config
        # Send config update to the running process
        if self._command_queue and self._process_started:
            try:
                self._command_queue.put(('config', config.to_dict()))
            except Exception:
                pass

    def _ensure_process_running(self) -> bool:
        """Ensure the overlay process is running (starts if needed)."""
        if not PYQT5_AVAILABLE:
            logger.error("PyQt5 not available")
            return False

        # Check if process died
        if self._process and not self._process.is_alive():
            self._process = None
            self._process_started = False
            self._visible = False

        if self._process_started:
            return True

        try:
            import multiprocessing

            # Create command queue for IPC
            self._command_queue = multiprocessing.Queue()

            # Start overlay in separate process (stays running)
            self._process = multiprocessing.Process(
                target=_run_persistent_overlay,
                args=(self.reader.game_version, self.config.to_dict(), self._command_queue),
                daemon=True
            )
            self._process.start()

            self._process_started = True
            logger.info("Overlay process started (persistent)")
            return True

        except Exception as e:
            logger.error(f"Failed to start overlay process: {e}")
            return False

    def start(self) -> bool:
        """Show the overlay (starts process if needed)."""
        import time
        t0 = time.time()

        if not self._ensure_process_running():
            return False

        t1 = time.time()
        logger.info(f"Process ensure took {(t1-t0)*1000:.0f}ms")

        if self._visible:
            return True

        # Send show command
        try:
            self._command_queue.put(('show', None))
            self._visible = True
            t2 = time.time()
            logger.info(f"Show command sent in {(t2-t1)*1000:.0f}ms, total {(t2-t0)*1000:.0f}ms")
            return True
        except Exception as e:
            logger.error(f"Failed to show overlay: {e}")
            return False

    def stop(self):
        """Hide the overlay (process keeps running)."""
        if self._command_queue and self._visible:
            try:
                self._command_queue.put(('hide', None))
            except Exception:
                pass
        self._visible = False
        logger.info("Overlay hidden")

    def shutdown(self):
        """Fully terminate the overlay process."""
        if self._command_queue:
            try:
                self._command_queue.put(('quit', None))
            except Exception:
                pass
        if self._process and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2)
        self._process = None
        self._command_queue = None
        self._process_started = False
        self._visible = False
        logger.info("Overlay process terminated")

    def is_running(self) -> bool:
        """Check if overlay is visible."""
        # Check if process died
        if self._process and not self._process.is_alive():
            self._process_started = False
            self._visible = False
        return self._visible

    def toggle(self) -> bool:
        """Toggle overlay visibility. Returns new state."""
        if self._visible:
            self.stop()
        else:
            self.start()
        return self._visible


def _run_persistent_overlay(game_version: str, config_dict: dict, command_queue):
    """Run the overlay in a persistent process with IPC command handling.

    The overlay stays running and responds to show/hide/config commands via queue.
    This eliminates the startup delay from spawning a new process each toggle.
    """
    import sys
    from PyQt5.QtCore import QTimer

    # Create fresh instances for this process
    app = QApplication(sys.argv)

    reader = TerrainReader(game_version)
    if not reader.connect():
        print("ERROR: Could not connect to game process")
        return

    # Build config from dict (includes all entity visibility settings)
    config = OverlayConfig.from_dict(config_dict)

    overlay = OverlayWindow(reader, config)

    # Start HIDDEN but with update timer running (so it stays connected)
    # This allows pre-spawning: process starts, connects to game, and waits
    # When user toggles ON, we just call show() - instant!
    overlay.hide()
    overlay.setVisible(False)  # Explicitly ensure hidden
    # Keep update timer running at reduced rate while hidden (just to stay connected)
    overlay.update_timer.start(100)  # 10 Hz while hidden
    print("[OVERLAY PROCESS] Started hidden, waiting for show command...")

    def check_commands():
        """Poll command queue for show/hide/config/quit commands."""
        try:
            while not command_queue.empty():
                cmd, data = command_queue.get_nowait()

                if cmd == 'show':
                    print(f"[OVERLAY] Show command received. Terrain={overlay._terrain is not None}, Player={overlay._player_grid_pos}")
                    overlay.show()
                    # Switch to full speed when visible
                    overlay.update_timer.start(overlay.config.update_interval)
                elif cmd == 'hide':
                    overlay.hide()
                    # Reduce to lower rate when hidden
                    overlay.update_timer.start(100)
                elif cmd == 'config':
                    # Update config and apply
                    new_config = OverlayConfig.from_dict(data)
                    overlay.config = new_config
                elif cmd == 'quit':
                    app.quit()
                    return
        except Exception:
            pass

    # Check for commands every 50ms
    cmd_timer = QTimer()
    cmd_timer.timeout.connect(check_commands)
    cmd_timer.start(50)

    sys.exit(app.exec_())


# ============================================================================
# Test / Demo
# ============================================================================
def test_overlay():
    """Test the overlay with game connection."""
    if not PYQT5_AVAILABLE:
        print("PyQt5 not installed. Run: pip install PyQt5")
        return

    print("=" * 60)
    print("POE2 Terrain Overlay")
    print("=" * 60)
    print("\nConnecting to POE2...")

    app = QApplication(sys.argv)

    # Create terrain reader and connect to game
    reader = TerrainReader("steam")
    if not reader.connect():
        print("ERROR: Could not connect to PathOfExileSteam.exe")
        print("Make sure the game is running.")
        return

    print(f"Connected! Base: 0x{reader.base_address:X}")

    # Create overlay with default config
    config = OverlayConfig()

    overlay = OverlayWindow(reader, config)
    overlay.show()

    print("Overlay started. Close the window or press Ctrl+C to exit.")

    sys.exit(app.exec_())


if __name__ == "__main__":
    # Required for multiprocessing on Windows
    import multiprocessing
    multiprocessing.freeze_support()

    test_overlay()
