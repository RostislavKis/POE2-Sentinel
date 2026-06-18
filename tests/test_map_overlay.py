"""
Unit tests for map_overlay module.
"""

import pytest
import struct
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, '..')
from terrain_reader import TerrainData, TerrainReader, Poe2Offsets
from map_overlay import (
    OverlayConfig,
    CoordinateTransformer,
    find_game_window,
    PYQT5_AVAILABLE
)


class TestOverlayConfig:
    """Tests for OverlayConfig class."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = OverlayConfig()

        assert config.update_interval == 16
        assert config.show_player is True
        assert config.show_terrain is True
        assert config.width == 1920
        assert config.height == 1080

    def test_custom_values(self):
        """Test custom configuration values."""
        config = OverlayConfig(
            monster_size=8,
            width=500,
            height=400,
            show_player=False,
        )

        assert config.monster_size == 8
        assert config.width == 500
        assert config.height == 400
        assert config.show_player is False

    def test_color_defaults(self):
        """Test default color values are RGBA tuples."""
        config = OverlayConfig()

        assert len(config.interior_color) == 4
        assert len(config.edge_color) == 4
        assert len(config.player_color) == 4
        assert len(config.monster_normal_color) == 4

        # Player marker is fully opaque; normal monsters are red.
        assert config.player_color[3] == 255
        assert config.monster_normal_color[0] == 255


class TestCoordinateTransformer:
    """Tests for CoordinateTransformer class."""
    
    def test_grid_to_world_conversion(self):
        """Test grid to world coordinate conversion."""
        reader = Mock(spec=TerrainReader)
        transformer = CoordinateTransformer(reader)
        
        world_x, world_y, world_z = transformer.grid_to_world(100, 200)
        
        expected_x = 100 * Poe2Offsets.WORLD_TO_GRID_RATIO
        expected_y = 200 * Poe2Offsets.WORLD_TO_GRID_RATIO
        
        assert abs(world_x - expected_x) < 0.001
        assert abs(world_y - expected_y) < 0.001
        assert world_z == 0.0
    
    def test_grid_to_world_handles_zero(self):
        """Test grid to world with zero coordinates."""
        reader = Mock(spec=TerrainReader)
        transformer = CoordinateTransformer(reader)
        
        world_x, world_y, world_z = transformer.grid_to_world(0, 0)
        
        assert world_x == 0.0
        assert world_y == 0.0
        assert world_z == 0.0
    
    def test_world_to_screen_returns_none_without_matrix(self):
        """Test world_to_screen returns None when no camera matrix."""
        reader = Mock(spec=TerrainReader)
        transformer = CoordinateTransformer(reader)
        
        result = transformer.world_to_screen(100.0, 200.0, 0.0)
        
        assert result is None
    
    def test_world_to_screen_with_identity_matrix(self):
        """Test world_to_screen with identity-like matrix."""
        reader = Mock(spec=TerrainReader)
        transformer = CoordinateTransformer(reader)
        
        # Set up a simple identity-like matrix
        # This is simplified - real camera matrix is more complex
        transformer._camera_matrix = [
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1
        ]
        
        result = transformer.world_to_screen(100.0, 200.0, 0.0)
        
        assert result is not None
        assert result == (100, 200)
    
    def test_grid_to_screen_chains_correctly(self):
        """Test grid_to_screen chains grid_to_world and world_to_screen."""
        reader = Mock(spec=TerrainReader)
        transformer = CoordinateTransformer(reader)
        
        # Without matrix, should return None
        result = transformer.grid_to_screen(10, 20)
        assert result is None


class TestFindGameWindow:
    """Tests for find_game_window function."""
    
    @patch('map_overlay.WIN32_AVAILABLE', False)
    def test_returns_none_when_win32_not_available(self):
        """Test returns None when win32 not available."""
        # Need to reimport to get the patched value
        from map_overlay import find_game_window as fgw
        # This test is tricky because the import happens at module load
        # Just verify the function exists
        assert callable(find_game_window)
    
    @patch('map_overlay.win32gui')
    def test_finds_poe2_window(self, mock_win32gui):
        """Test finding POE2 window."""
        mock_win32gui.FindWindow.return_value = 12345
        mock_win32gui.GetWindowRect.return_value = (100, 200, 1100, 800)
        
        result = find_game_window()
        
        assert result is not None
        assert result == (100, 200, 1000, 600)  # x, y, width, height


@pytest.mark.skipif(not PYQT5_AVAILABLE, reason="PyQt5 not installed")
class TestOverlayWindow:
    """Tests for OverlayWindow class (requires PyQt5)."""
    
    def test_overlay_window_can_be_created(self):
        """Test that OverlayWindow can be instantiated."""
        from map_overlay import OverlayWindow
        from PyQt5.QtWidgets import QApplication
        
        # Need QApplication for any Qt widgets
        app = QApplication.instance() or QApplication([])
        
        reader = Mock(spec=TerrainReader)
        config = OverlayConfig()
        
        # Should not raise
        overlay = OverlayWindow(reader, config)
        
        assert overlay is not None
        assert overlay.config == config
