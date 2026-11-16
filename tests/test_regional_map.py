"""Unit and integration tests for RegionalMapGenerator, Voronoi cells, and Regional Map mode."""

import unittest
from bearlibterminal import terminal
import esper
import numpy as np

from game_state import GameState, GameStateManager
from regional_map_generator import (
    BIOME_REGISTRY,
    BiomeData,
    BiomeType,
    RegionalMap,
    RegionalMapGenerator,
)
import main


class TestRegionalMapGenerator(unittest.TestCase):
    """Test suite for Voronoi generation and biome distribution."""

    def test_voronoi_grid_generation(self) -> None:
        """Verify Voronoi diagram generation and 2D grid shape."""
        gen = RegionalMapGenerator(width=80, height=50, num_cells=30, seed=123)
        reg_map = gen.generate()

        self.assertEqual(reg_map.width, 80)
        self.assertEqual(reg_map.height, 50)
        self.assertEqual(reg_map.grid.shape, (80, 50))
        self.assertIsNotNone(reg_map.voronoi)
        self.assertEqual(len(reg_map.seed_points), 30)

        # All cells on the grid must have valid cell IDs in [0, 29]
        unique_cells = np.unique(reg_map.grid)
        self.assertTrue(all(0 <= cid < 30 for cid in unique_cells))

    def test_three_basic_biomes_assigned(self) -> None:
        """Verify Plains, Forest, and Mountains are all assigned and represented."""
        gen = RegionalMapGenerator(width=80, height=50, num_cells=30, seed=456)
        reg_map = gen.generate()

        assigned_biomes = set(reg_map.cell_biomes.values())
        self.assertIn(BiomeType.PLAINS, assigned_biomes)
        self.assertIn(BiomeType.FOREST, assigned_biomes)
        self.assertIn(BiomeType.MOUNTAINS, assigned_biomes)

        # Verify biome data registry has valid chars and colors
        plains_data = BIOME_REGISTRY[BiomeType.PLAINS]
        self.assertEqual(plains_data.char, ".")
        self.assertEqual(plains_data.color, "green")

        forest_data = BIOME_REGISTRY[BiomeType.FOREST]
        self.assertEqual(forest_data.char, "T")
        self.assertEqual(forest_data.color, "dark green")

        mountains_data = BIOME_REGISTRY[BiomeType.MOUNTAINS]
        self.assertEqual(mountains_data.char, "^")
        self.assertEqual(mountains_data.color, "gray")

    def test_grid_biome_queries(self) -> None:
        """Verify get_biome and get_biome_data methods across the 2D grid."""
        gen = RegionalMapGenerator(width=80, height=50, num_cells=25, seed=789)
        reg_map = gen.generate()

        for coords in [(0, 0), (40, 25), (79, 49), (10, 30)]:
            x, y = coords
            biome = reg_map.get_biome(x, y)
            self.assertIsInstance(biome, BiomeType)

            biome_data = reg_map.get_biome_data(x, y)
            self.assertIsInstance(biome_data, BiomeData)
            self.assertEqual(biome_data.name, biome.value)
            self.assertIn(biome_data.char, (".", "T", "^"))


class TestGameStateAndToggle(unittest.TestCase):
    """Test suite for GameState transitions and 'M' keybind toggle."""

    def setUp(self) -> None:
        self.state_manager = GameStateManager(initial_state=GameState.LOCAL_MAP)
        self.player = main.init_ecs(state_manager=self.state_manager)

    def test_initial_state_is_local_map(self) -> None:
        """Verify initial state starts in LOCAL_MAP mode."""
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

    def test_toggle_keybind_m(self) -> None:
        """Verify pressing 'M' toggles between LOCAL_MAP and REGIONAL_MAP."""
        # 1. Press 'M' -> switches to REGIONAL_MAP
        esper.process(key=terminal.TK_M)
        self.assertEqual(self.state_manager.state, GameState.REGIONAL_MAP)

        # 2. Press 'M' again -> switches back to LOCAL_MAP
        esper.process(key=terminal.TK_M)
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

        # 3. Press ord('m') -> switches to REGIONAL_MAP
        esper.process(key=ord("m"))
        self.assertEqual(self.state_manager.state, GameState.REGIONAL_MAP)

        # 4. Press ord('M') -> switches back to LOCAL_MAP
        esper.process(key=ord("M"))
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

    def test_local_movement_paused_in_regional_map(self) -> None:
        """Ensure player position does not change when walking while in REGIONAL_MAP mode."""
        from components import Position

        pos = esper.component_for_entity(self.player, Position)
        original_coords = (pos.x, pos.y, pos.z)

        # Switch to REGIONAL_MAP
        esper.process(key=terminal.TK_M)
        self.assertEqual(self.state_manager.state, GameState.REGIONAL_MAP)

        # Attempt to walk in all directions
        esper.process(key=terminal.TK_RIGHT)
        esper.process(key=terminal.TK_DOWN)
        esper.process(key=terminal.TK_LEFT)
        esper.process(key=terminal.TK_UP)

        # Coordinates should remain unchanged
        self.assertEqual((pos.x, pos.y, pos.z), original_coords)

    def test_render_system_in_regional_map_mode(self) -> None:
        """Verify BearLibTerminal renders cleanly in REGIONAL_MAP state."""
        terminal.open()
        try:
            terminal.set(f"window: size={main.SCREEN_WIDTH}x{main.SCREEN_HEIGHT}")

            # Render local map
            esper.process()

            # Switch to regional map and render
            esper.process(key=terminal.TK_M)
            self.assertEqual(self.state_manager.state, GameState.REGIONAL_MAP)

            # Switch back to local map and render
            esper.process(key=terminal.TK_M)
            self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)
        finally:
            terminal.close()


if __name__ == "__main__":
    unittest.main()
