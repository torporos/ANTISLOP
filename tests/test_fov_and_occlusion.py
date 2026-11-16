"""Unit and integration tests for VisibilitySystem, tcod FOV, and Interior Occlusion."""

import unittest
from bearlibterminal import terminal
import esper

from components import Position, StructureFootprint, Viewshed
from game_map import GameMap, Tile
from systems import InputSystem, MovementSystem, RenderSystem, VisibilitySystem
import main


class TestFOVAndInteriorOcclusion(unittest.TestCase):
    """Test suite for FOV calculations and interior occlusion mechanics."""

    def setUp(self) -> None:
        """Initialize ECS world and map before each test."""
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        # Execute one frame to compute initial FOV
        esper.process()

    def test_create_structure_geometry(self) -> None:
        """Verify rectangular structure dimensions, walls ('#'), interior, and door ('+')."""
        self.game_map.create_structure(
            x=50,
            y=50,
            width=5,
            height=5,
            z=0,
            door_x=52,
            door_y=54,
            name="Test Structure",
            room_id=10,
        )
        # Check boundary walls '#'
        for x in range(50, 55):
            self.assertEqual(self.game_map.get_tile(x, 50, 0).char, "#")
            self.assertFalse(self.game_map.is_walkable(x, 50, 0))

        # Check left and right walls
        for y in range(51, 54):
            self.assertEqual(self.game_map.get_tile(50, y, 0).char, "#")
            self.assertFalse(self.game_map.is_walkable(50, y, 0))
            self.assertEqual(self.game_map.get_tile(54, y, 0).char, "#")
            self.assertFalse(self.game_map.is_walkable(54, y, 0))

        # Check south wall with closed door at (52, 54)
        self.assertEqual(self.game_map.get_tile(50, 54, 0).char, "#")
        self.assertEqual(self.game_map.get_tile(51, 54, 0).char, "#")
        self.assertEqual(self.game_map.get_tile(52, 54, 0).char, "+")
        self.assertFalse(self.game_map.is_walkable(52, 54, 0))
        self.assertFalse(self.game_map.is_transparent(52, 54, 0))
        self.assertEqual(self.game_map.get_tile(53, 54, 0).char, "#")
        self.assertEqual(self.game_map.get_tile(54, 54, 0).char, "#")

        # Check interior floor tiles
        for ix in (51, 52, 53):
            for iy in (51, 52, 53):
                self.assertEqual(self.game_map.get_tile(ix, iy, 0).char, ".")
                self.assertTrue(self.game_map.is_walkable(ix, iy, 0))

    def test_exterior_fov_calculation(self) -> None:
        """Verify tcod calculates FOV from player position and walls block line of sight."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Move player just outside south wall of the Tavern: (101, 104)
        pos.x = 101
        pos.y = 104
        esper.process()

        # Player location and doorway should be in FOV
        self.assertTrue(viewshed.is_visible(101, 104))
        self.assertTrue(viewshed.is_visible(101, 103))  # Doorway

        # South wall tiles adjacent to door should be in FOV (illuminated)
        self.assertTrue(viewshed.is_visible(100, 103))
        self.assertTrue(viewshed.is_visible(102, 103))

        # Tiles behind solid walls (e.g. behind 100, 103) should be blocked by wall
        self.assertFalse(viewshed.is_visible(100, 102))

        # Player is outside the structure
        self.assertFalse(viewshed.inside_structure)
        self.assertIsNone(viewshed.active_structure)

    def test_interior_occlusion_transition(self) -> None:
        """Verify interior occlusion activates upon entering and deactivates upon exiting."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # 1. Player is outside at (101, 105)
        pos.x = 101
        pos.y = 105
        esper.process()
        self.assertFalse(viewshed.inside_structure)
        self.assertIsNone(viewshed.active_structure)

        # 2. Open door and step onto doorway (101, 103) - inside Tavern footprint
        door_ent = main.current_door_system.get_door_at(101, 103, 0)
        self.assertIsNotNone(door_ent)
        main.current_door_system.open_door(door_ent)

        pos.x = 101
        pos.y = 103
        esper.process()
        self.assertTrue(viewshed.inside_structure)
        self.assertIsNotNone(viewshed.active_structure)
        self.assertEqual(viewshed.active_structure.building_id, "Tavern")

        # 3. Player steps into interior room at (100, 100)
        pos.x = 100
        pos.y = 100
        esper.process()
        self.assertTrue(viewshed.inside_structure)
        self.assertIsNotNone(viewshed.active_structure)

        # Structure interior tiles are inside footprint
        self.assertTrue(viewshed.active_structure.contains(100, 100, 0))
        self.assertTrue(viewshed.active_structure.contains(99, 100, 0))
        # Outside tiles are outside footprint
        self.assertFalse(viewshed.active_structure.contains(101, 105, 0))

        # 4. Player steps back outside to (101, 104)
        pos.x = 101
        pos.y = 104
        esper.process()
        self.assertFalse(viewshed.inside_structure)
        self.assertIsNone(viewshed.active_structure)

    def test_render_system_interior_occlusion_modes(self) -> None:
        """Verify RenderSystem renders cleanly in both exterior and occluded interior states."""
        terminal.open()
        try:
            terminal.set(f"window: size={main.SCREEN_WIDTH}x{main.SCREEN_HEIGHT}")
            pos = esper.component_for_entity(self.player, Position)

            # 1. Render outside
            pos.x = 101
            pos.y = 105
            esper.process()

            # 2. Open door and render inside Tavern (Interior Occlusion active)
            door_ent = main.current_door_system.get_door_at(101, 103, 0)
            self.assertIsNotNone(door_ent)
            main.current_door_system.open_door(door_ent)
            pos.x = 100
            pos.y = 100
            esper.process()

            viewshed = esper.component_for_entity(self.player, Viewshed)
            self.assertTrue(viewshed.inside_structure)

            # 3. Render after stepping back outside
            pos.x = 101
            pos.y = 105
            esper.process()
            self.assertFalse(viewshed.inside_structure)
        finally:
            terminal.close()


if __name__ == "__main__":
    unittest.main()
