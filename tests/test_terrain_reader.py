"""
Unit tests for terrain_reader module.
"""

import pytest
import struct
from unittest.mock import Mock, patch, MagicMock

# Import the module under test
import sys
sys.path.insert(0, '..')
from terrain_reader import (
    TerrainData, 
    Poe2Offsets, 
    AobScanner, 
    TerrainReader
)


class TestTerrainData:
    """Tests for TerrainData class."""
    
    def test_is_walkable_returns_true_for_walkable_cell(self):
        """Test that is_walkable returns True for walkable cells."""
        # Create grid with walkable cells (nibble value > 0)
        # Each byte = 2 cells, low nibble first
        # 0x12 = low nibble 2 (walkable), high nibble 1 (walkable)
        grid = bytes([0x12, 0x34, 0x56, 0x78])
        
        terrain = TerrainData(
            width=8,
            height=1,
            walkable_grid=grid,
            tiles_x=1,
            tiles_y=1,
            bytes_per_row=4
        )
        
        # Cell 0 (low nibble of byte 0) = 2 -> walkable
        assert terrain.is_walkable(0, 0) == True
        # Cell 1 (high nibble of byte 0) = 1 -> walkable
        assert terrain.is_walkable(1, 0) == True
    
    def test_is_walkable_returns_false_for_blocked_cell(self):
        """Test that is_walkable returns False for blocked cells."""
        # 0x10 = low nibble 0 (blocked), high nibble 1 (walkable)
        grid = bytes([0x10, 0x01])
        
        terrain = TerrainData(
            width=4,
            height=1,
            walkable_grid=grid,
            tiles_x=1,
            tiles_y=1,
            bytes_per_row=2
        )
        
        # Cell 0 (low nibble) = 0 -> blocked
        assert terrain.is_walkable(0, 0) == False
        # Cell 1 (high nibble) = 1 -> walkable
        assert terrain.is_walkable(1, 0) == True
    
    def test_is_walkable_returns_false_for_out_of_bounds(self):
        """Test that is_walkable returns False for out-of-bounds coordinates."""
        grid = bytes([0xFF])
        
        terrain = TerrainData(
            width=2,
            height=1,
            walkable_grid=grid,
            tiles_x=1,
            tiles_y=1,
            bytes_per_row=1
        )
        
        assert terrain.is_walkable(-1, 0) == False
        assert terrain.is_walkable(0, -1) == False
        assert terrain.is_walkable(2, 0) == False
        assert terrain.is_walkable(0, 1) == False
    
    def test_is_walkable_handles_multi_row_grid(self):
        """Test walkability check on multi-row grid."""
        # 2 rows, 4 cells each, 2 bytes per row
        grid = bytes([
            0x12, 0x34,  # Row 0
            0x00, 0xFF   # Row 1
        ])
        
        terrain = TerrainData(
            width=4,
            height=2,
            walkable_grid=grid,
            tiles_x=1,
            tiles_y=1,
            bytes_per_row=2
        )
        
        # Row 0
        assert terrain.is_walkable(0, 0) == True   # 0x12 low = 2
        assert terrain.is_walkable(1, 0) == True   # 0x12 high = 1
        
        # Row 1
        assert terrain.is_walkable(0, 1) == False  # 0x00 low = 0
        assert terrain.is_walkable(3, 1) == True   # 0xFF high = F


class TestAobScanner:
    """Tests for AobScanner class."""
    
    def test_find_pattern_finds_exact_match(self):
        """Test pattern finding with exact bytes."""
        data = bytes([0x00, 0x48, 0x8B, 0x05, 0x00, 0x00])
        pattern = [0x48, 0x8B, 0x05]
        
        results = AobScanner.find_pattern(data, pattern)
        
        assert len(results) == 1
        assert results[0] == 1
    
    def test_find_pattern_finds_multiple_matches(self):
        """Test pattern finding with multiple occurrences."""
        data = bytes([0xAA, 0xBB, 0xAA, 0xBB, 0xAA, 0xBB])
        pattern = [0xAA, 0xBB]
        
        results = AobScanner.find_pattern(data, pattern)
        
        assert len(results) == 3
        assert results == [0, 2, 4]
    
    def test_find_pattern_with_wildcards(self):
        """Test pattern finding with None wildcards."""
        data = bytes([0x48, 0x8B, 0x05, 0x12, 0x34, 0x56, 0x78])
        pattern = [0x48, 0x8B, 0x05, None, None, None, None]
        
        results = AobScanner.find_pattern(data, pattern)
        
        assert len(results) == 1
        assert results[0] == 0
    
    def test_find_pattern_returns_empty_for_no_match(self):
        """Test pattern finding returns empty list when no match."""
        data = bytes([0x00, 0x00, 0x00, 0x00])
        pattern = [0xFF, 0xFF]
        
        results = AobScanner.find_pattern(data, pattern)
        
        assert len(results) == 0
    
    def test_resolve_rip_relative_calculates_correctly(self):
        """Test RIP-relative address resolution."""
        # Pattern: 48 8B 05 [disp32] at base 0x1000
        # Instruction length: 7 bytes
        # Displacement at offset 3
        
        base_addr = 0x1000
        match_offset = 0
        disp_offset = 3
        instr_len = 7
        
        # Displacement = 0x100 (256)
        data = bytes([0x48, 0x8B, 0x05, 0x00, 0x01, 0x00, 0x00])
        
        result = AobScanner.resolve_rip_relative(
            base_addr, match_offset, disp_offset, instr_len, data
        )
        
        # Expected: base + match_offset + instr_len + displacement
        # = 0x1000 + 0 + 7 + 0x100 = 0x1107
        assert result == 0x1107

    def test_resolve_rip_relative_handles_negative_displacement(self):
        """Test RIP-relative with negative displacement."""
        base_addr = 0x2000
        match_offset = 0
        disp_offset = 3
        instr_len = 7

        # Displacement = -256 (0xFFFFFF00 as signed int32)
        data = bytes([0x48, 0x8B, 0x05, 0x00, 0xFF, 0xFF, 0xFF])

        result = AobScanner.resolve_rip_relative(
            base_addr, match_offset, disp_offset, instr_len, data
        )

        # Expected: 0x2000 + 7 + (-256) = 0x1F07
        assert result == 0x1F07


class TestPoe2Offsets:
    """Tests for Poe2Offsets constants."""

    def test_world_to_grid_ratio(self):
        """Test world to grid ratio constant."""
        assert abs(Poe2Offsets.WORLD_TO_GRID_RATIO - 10.8695652) < 0.001

    def test_tile_grid_cells(self):
        """Test tile grid cells constant."""
        assert Poe2Offsets.TILE_GRID_CELLS == 23

    def test_terrain_offsets_exist(self):
        """Test that terrain offsets are defined."""
        assert Poe2Offsets.Terrain.GRID_WALKABLE_DATA == 0xD0
        assert Poe2Offsets.Terrain.BYTES_PER_ROW == 0x130
        assert Poe2Offsets.Terrain.TOTAL_TILES == 0x18

    def test_ingamestate_offsets_exist(self):
        """Test that InGameState offsets are defined."""
        assert Poe2Offsets.InGameState.AREA_INSTANCE_DATA == 0x290
        assert Poe2Offsets.InGameState.CAMERA == 0x368


class TestTerrainReaderConnection:
    """Tests for TerrainReader connection handling."""

    @patch('terrain_reader.pymem.Pymem')
    def test_connect_success(self, mock_pymem):
        """Test successful connection to game."""
        mock_pm = MagicMock()
        mock_pm.base_address = 0x140000000
        mock_pm.list_modules.return_value = [
            MagicMock(name='PathOfExileSteam.exe', SizeOfImage=0x10000000)
        ]
        mock_pymem.return_value = mock_pm

        reader = TerrainReader("steam")
        result = reader.connect()

        assert result == True
        assert reader.connected == True
        assert reader.base_address == 0x140000000

    @patch('terrain_reader.pymem.Pymem')
    def test_connect_failure(self, mock_pymem):
        """Test failed connection to game."""
        mock_pymem.side_effect = Exception("Process not found")

        reader = TerrainReader("steam")
        result = reader.connect()

        assert result == False
        assert reader.connected == False

    def test_disconnect_clears_state(self):
        """Test that disconnect clears cached state."""
        reader = TerrainReader("steam")
        reader._in_game_state_addr = 0x12345678
        reader._area_instance_addr = 0x87654321
        reader.connected = True

        reader.disconnect()

        assert reader.connected == False
        assert reader._in_game_state_addr is None
        assert reader._area_instance_addr is None


class TestTerrainReaderMemoryOps:
    """Tests for TerrainReader memory operations."""

    def test_read_ptr_returns_none_when_not_connected(self):
        """Test _read_ptr returns None when not connected."""
        reader = TerrainReader("steam")
        result = reader._read_ptr(0x12345678)
        assert result is None

    def test_read_std_vector_validates_size(self):
        """Test _read_std_vector validates size bounds."""
        reader = TerrainReader("steam")
        reader.pm = MagicMock()

        # Return begin and end that would give negative size
        reader.pm.read_longlong.side_effect = [0x2000, 0x1000]  # end < begin

        result = reader._read_std_vector(0x1000)
        assert result is None

    def test_read_std_vector_rejects_huge_size(self):
        """Test _read_std_vector rejects sizes > 100MB."""
        reader = TerrainReader("steam")
        reader.pm = MagicMock()

        # Return begin and end that would give > 100MB
        reader.pm.read_longlong.side_effect = [0x1000, 0x1000 + 200_000_000]

        result = reader._read_std_vector(0x1000)
        assert result is None


# ============================================================================
# Integration test (requires game running - skip by default)
# ============================================================================
@pytest.mark.skip(reason="Requires POE2 running")
class TestTerrainReaderIntegration:
    """Integration tests that require POE2 to be running."""

    def test_read_terrain_from_game(self):
        """Test reading actual terrain from running game."""
        reader = TerrainReader("steam")

        if not reader.connect():
            pytest.skip("Game not running")

        terrain = reader.read_terrain()

        assert terrain is not None
        assert terrain.width > 0
        assert terrain.height > 0
        assert len(terrain.walkable_grid) > 0

        reader.disconnect()
