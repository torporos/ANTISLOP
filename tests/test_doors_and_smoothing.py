"""Unit and integration tests for Room ID tagging, Doors, and Lloyd's Relaxation."""

import unittest
from bearlibterminal import terminal
import esper
import numpy as np

from components import Door, Position, Renderable, Viewshed
from game_map import GameMap, Tile
from regional_map_generator import BiomeType, RegionalMapGenerator
import main


class TestRoomIDAndDoors(unittest.TestCase):
    """Test suite for Room ID tagging and Door interaction/FOV mechanics."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        esper.process()

    def test_room_id_tagging(self) -> None:
        """Verify interior tiles and walls have room_id=1, exterior tiles have None."""
        # Tavern Main Room bounds: x: 98..104, y: 97..103
        for x in range(98, 105):
            for y in range(97, 104):
                tile = self.game_map.get_tile(x, y, 0)
                self.assertIsNotNone(tile)
                self.assertEqual(tile.room_id, 1, f"Tile at ({x}, {y}) should have room_id=1")

        # Exterior tiles
        for coords in [(97, 90), (103, 90), (100, 89), (101, 105), (90, 80), (0, 0)]:
            x, y = coords
            tile = self.game_map.get_tile(x, y, 0)
            self.assertIsNotNone(tile)
            self.assertIsNone(tile.room_id, f"Tile at ({x}, {y}) should have room_id=None")

    def test_closed_door_blocks_fov(self) -> None:
        """Verify closed door (+) blocks FOV from entering the building."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Position player outside Tavern doorway: (101, 104)
        pos.x = 101
        pos.y = 104
        esper.process()

        # Closed door at (101, 103) is visible
        self.assertTrue(viewshed.is_visible(101, 103))

        # Interior tiles behind the closed door are BLOCKED
        self.assertFalse(viewshed.is_visible(101, 102))
        self.assertFalse(viewshed.is_visible(101, 101))
        self.assertFalse(viewshed.is_visible(100, 101))

    def test_open_door_allows_fov(self) -> None:
        """Verify opening the door allows FOV to pass through into the building."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        pos.x = 101
        pos.y = 104
        esper.process()

        # Press 'E' (terminal.TK_E) to open adjacent door
        esper.process(key=terminal.TK_E)

        # Verify door entity state
        door_ent = main.current_door_system.get_door_at(101, 103, 0)
        self.assertIsNotNone(door_ent)
        door = esper.component_for_entity(door_ent, Door)
        door_rend = esper.component_for_entity(door_ent, Renderable)
        self.assertTrue(door.is_open)
        self.assertEqual(door_rend.char, "/")

        # Verify map tile state
        door_tile = self.game_map.get_tile(101, 103, 0)
        self.assertTrue(door_tile.transparent)
        self.assertTrue(door_tile.walkable)
        self.assertEqual(door_tile.char, "/")

        # FOV now penetrates into the interior!
        self.assertTrue(viewshed.is_visible(101, 102))
        self.assertTrue(viewshed.is_visible(101, 101))

    def test_bump_to_open_door(self) -> None:
        """Verify player bumping into a closed door opens it."""
        pos = esper.component_for_entity(self.player, Position)

        # Stand right in front of the door at (101, 104)
        pos.x = 101
        pos.y = 104
        esper.process()

        # Move Up into closed door at (101, 103)
        esper.process(key=terminal.TK_UP)

        door_ent = main.current_door_system.get_door_at(101, 103, 0)
        door = esper.component_for_entity(door_ent, Door)
        self.assertTrue(door.is_open)

        # Next move steps through the open doorway
        esper.process(key=terminal.TK_UP)
        self.assertEqual((pos.x, pos.y), (101, 103))

    def test_room_id_interior_occlusion_activation(self) -> None:
        """Verify room_id correctly drives interior occlusion when entering/exiting."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # 1. Outside at (101, 105)
        pos.x = 101
        pos.y = 105
        esper.process()
        self.assertIsNone(viewshed.current_room_id)
        self.assertFalse(viewshed.inside_structure)

        # 2. Open door and enter room at (101, 102)
        main.current_door_system.open_door(main.current_door_system.get_door_at(101, 103, 0))
        pos.x = 101
        pos.y = 102
        esper.process()

        self.assertEqual(viewshed.current_room_id, 1)
        self.assertTrue(viewshed.inside_structure)

        # 3. Exit back outside to (101, 104)
        pos.x = 101
        pos.y = 104
        esper.process()

        self.assertIsNone(viewshed.current_room_id)
        self.assertFalse(viewshed.inside_structure)


class TestLloydRelaxation(unittest.TestCase):
    """Test suite for Voronoi smoothing via Lloyd's Relaxation."""

    def test_lloyd_relaxation_reduces_variance(self) -> None:
        """Verify Lloyd's Relaxation smooths cell distribution and lowers size variance."""
        width, height, num_cells = 80, 50, 30
        seed = 42

        # 1. Unrelaxed (0 steps)
        gen_raw = RegionalMapGenerator(width=width, height=height, num_cells=num_cells, relaxation_steps=0, seed=seed)
        map_raw = gen_raw.generate()
        sizes_raw = [np.sum(map_raw.grid == cid) for cid in range(num_cells)]
        std_raw = float(np.std(sizes_raw))

        # 2. Relaxed (3 steps)
        gen_relaxed = RegionalMapGenerator(width=width, height=height, num_cells=num_cells, relaxation_steps=3, seed=seed)
        map_relaxed = gen_relaxed.generate()
        sizes_relaxed = [np.sum(map_relaxed.grid == cid) for cid in range(num_cells)]
        std_relaxed = float(np.std(sizes_relaxed))

        # Standard deviation of cell areas should decrease significantly (smoothing effect)
        self.assertLess(std_relaxed, std_raw)

    def test_regional_map_with_lloyd_relaxation_has_all_biomes(self) -> None:
        """Verify smoothed regional map contains all 3 biomes."""
        gen = RegionalMapGenerator(width=80, height=50, num_cells=35, relaxation_steps=2, seed=99)
        reg_map = gen.generate()

        biomes = set(reg_map.cell_biomes.values())
        self.assertIn(BiomeType.PLAINS, biomes)
        self.assertIn(BiomeType.FOREST, biomes)
        self.assertIn(BiomeType.MOUNTAINS, biomes)


if __name__ == "__main__":
    unittest.main()
