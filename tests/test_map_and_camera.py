"""Unit and integration tests for GameMap, Tile, Camera, and boundary collision."""

import unittest
from bearlibterminal import terminal
import esper

from camera import Camera
from components import MovementIntent, Player, Position, Renderable
from game_map import GameMap, Tile
from systems import InputSystem, MovementSystem, RenderSystem
import main


class TestGameMapAndTile(unittest.TestCase):
    """Test suite for Tile and GameMap data structures."""

    def test_tile_properties(self) -> None:
        """Verify Tile attributes and factory methods."""
        floor = Tile.floor()
        self.assertTrue(floor.walkable)
        self.assertTrue(floor.transparent)
        self.assertEqual(floor.char, ".")
        self.assertEqual(floor.color, "gray")

        wall = Tile.wall()
        self.assertFalse(wall.walkable)
        self.assertFalse(wall.transparent)
        self.assertEqual(wall.char, "#")
        self.assertEqual(wall.color, "white")

    def test_map_dimensions_and_z_levels(self) -> None:
        """Verify 200x200 grid across multi-level storage."""
        game_map = GameMap(width=200, height=200)
        self.assertEqual(game_map.width, 200)
        self.assertEqual(game_map.height, 200)
        self.assertIn(0, game_map.tiles)
        self.assertEqual(len(game_map.tiles[0]), 200)
        self.assertEqual(len(game_map.tiles[0][0]), 200)

    def test_z_level_0_floor_and_boundary_walls(self) -> None:
        """Verify Z-level 0 has generic floor tiles ('.') and '#' boundary walls."""
        game_map = GameMap(width=200, height=200)

        # Boundary walls on all 4 borders
        for x in range(200):
            # Top boundary (y=0)
            self.assertEqual(game_map.get_tile(x, 0, 0).char, "#")
            self.assertFalse(game_map.is_walkable(x, 0, 0))
            # Bottom boundary (y=199)
            self.assertEqual(game_map.get_tile(x, 199, 0).char, "#")
            self.assertFalse(game_map.is_walkable(x, 199, 0))

        for y in range(200):
            # Left boundary (x=0)
            self.assertEqual(game_map.get_tile(0, y, 0).char, "#")
            self.assertFalse(game_map.is_walkable(0, y, 0))
            # Right boundary (x=199)
            self.assertEqual(game_map.get_tile(199, y, 0).char, "#")
            self.assertFalse(game_map.is_walkable(199, y, 0))

        # Interior tiles should all be walkable '.'
        self.assertEqual(game_map.get_tile(1, 1, 0).char, ".")
        self.assertTrue(game_map.is_walkable(1, 1, 0))
        self.assertEqual(game_map.get_tile(100, 100, 0).char, ".")
        self.assertTrue(game_map.is_walkable(100, 100, 0))
        self.assertEqual(game_map.get_tile(198, 198, 0).char, ".")
        self.assertTrue(game_map.is_walkable(198, 198, 0))

    def test_multi_level_access_and_indexing(self) -> None:
        """Verify on-demand Z-level generation and bracket indexing."""
        game_map = GameMap(width=200, height=200)

        # Z=1 should be generated on demand with walls and floor
        tile_z1 = game_map[100, 100, 1]
        self.assertIsNotNone(tile_z1)
        self.assertEqual(tile_z1.char, ".")
        self.assertTrue(game_map.is_walkable(100, 100, 1))

        # Check boundary wall on Z=1
        wall_z1 = game_map[0, 50, 1]
        self.assertEqual(wall_z1.char, "#")
        self.assertFalse(game_map.is_walkable(0, 50, 1))

        # Out of bounds check
        self.assertIsNone(game_map.get_tile(-1, 50, 0))
        self.assertIsNone(game_map.get_tile(200, 50, 0))
        self.assertFalse(game_map.is_walkable(-1, 50, 0))


class TestCameraSystem(unittest.TestCase):
    """Test suite for Camera viewport centering and clamping."""

    def test_camera_center_on_player(self) -> None:
        """Verify camera centers on player at (100, 100)."""
        camera = Camera(viewport_width=80, viewport_height=50)
        camera.update(target_x=100, target_y=100, map_width=200, map_height=200)

        # Top-left of camera should be (100 - 40, 100 - 25) = (60, 75)
        self.assertEqual(camera.x, 60)
        self.assertEqual(camera.y, 75)

        # Player at map (100, 100) translates to screen (40, 25)
        screen_pos = camera.to_screen(100, 100)
        self.assertEqual(screen_pos, (40, 25))

    def test_camera_top_left_clamping(self) -> None:
        """Verify camera clamps to (0, 0) when player is near top-left edge."""
        camera = Camera(viewport_width=80, viewport_height=50)
        camera.update(target_x=5, target_y=5, map_width=200, map_height=200)

        self.assertEqual(camera.x, 0)
        self.assertEqual(camera.y, 0)

        # Player at (5, 5) renders at screen (5, 5)
        self.assertEqual(camera.to_screen(5, 5), (5, 5))
        self.assertTrue(camera.in_view(5, 5))

    def test_camera_bottom_right_clamping(self) -> None:
        """Verify camera clamps to (120, 150) when player is near bottom-right edge."""
        camera = Camera(viewport_width=80, viewport_height=50)
        camera.update(target_x=195, target_y=195, map_width=200, map_height=200)

        # Max camera x = 200 - 80 = 120, max camera y = 200 - 50 = 150
        self.assertEqual(camera.x, 120)
        self.assertEqual(camera.y, 150)

        # Player at (195, 195) renders at (195 - 120, 195 - 150) = (75, 45)
        self.assertEqual(camera.to_screen(195, 195), (75, 45))
        self.assertTrue(camera.in_view(195, 195))

    def test_camera_in_view(self) -> None:
        """Verify in_view correctly checks visibility."""
        camera = Camera(viewport_width=80, viewport_height=50)
        camera.update(target_x=100, target_y=100, map_width=200, map_height=200)
        # Camera is at (60, 75), covers map_x in [60, 139], map_y in [75, 124]

        self.assertTrue(camera.in_view(60, 75))
        self.assertTrue(camera.in_view(139, 124))
        self.assertFalse(camera.in_view(59, 75))
        self.assertFalse(camera.in_view(140, 100))
        self.assertFalse(camera.in_view(100, 74))
        self.assertFalse(camera.in_view(100, 125))


class TestMovementCollisionWithMap(unittest.TestCase):
    """Test suite for MovementSystem collision checking against boundary walls."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)

    def test_cannot_walk_through_boundary_walls(self) -> None:
        """Ensure MovementSystem prevents stepping into '#' boundary walls."""
        pos = esper.component_for_entity(self.player, Position)

        # Move player next to left boundary wall: (1, 50)
        pos.x = 1
        pos.y = 50

        # Try walking West into wall '#' at (0, 50)
        esper.process(key=terminal.TK_LEFT)
        self.assertEqual((pos.x, pos.y), (1, 50))

        # Move player next to top boundary wall: (50, 1)
        pos.x = 50
        pos.y = 1

        # Try walking North into wall '#' at (50, 0)
        esper.process(key=terminal.TK_UP)
        self.assertEqual((pos.x, pos.y), (50, 1))

        # Move player next to right boundary wall: (198, 50)
        pos.x = 198
        pos.y = 50

        # Try walking East into wall '#' at (199, 50)
        esper.process(key=terminal.TK_RIGHT)
        self.assertEqual((pos.x, pos.y), (198, 50))

        # Move player next to bottom boundary wall: (50, 198)
        pos.x = 50
        pos.y = 198

        # Try walking South into wall '#' at (50, 199)
        esper.process(key=terminal.TK_DOWN)
        self.assertEqual((pos.x, pos.y), (50, 198))


if __name__ == "__main__":
    unittest.main()
