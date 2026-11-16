"""Unit and integration tests for Explored boolean grid, Fog of War, Entities hiding, and Roofs.

Validates:
1. GameMap explored boolean grid data structure and methods.
2. VisibilitySystem marking tiles in FOV as explored.
3. RenderSystem rendering in-FOV tiles bright, explored non-FOV tiles dark gray, unexplored tiles hidden.
4. RenderSystem rendering Roof tiles ('^', 'brown') for explored non-FOV tiles possessing a room_id.
5. Entities (NPCs, items) hidden in the Fog of War unless in active FOV.
"""

import unittest
from bearlibterminal import terminal
import esper
import numpy as np

from components import (
    Door,
    MovementIntent,
    Player,
    Position,
    Renderable,
    StructureFootprint,
    Viewshed,
)
from game_map import GameMap, Tile
from systems import DoorSystem, InputSystem, MovementSystem, RenderSystem, VisibilitySystem
import main


class TestExploredGridDataStructure(unittest.TestCase):
    """Test suite for the explored boolean grid in GameMap."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)

    def test_initial_explored_state(self) -> None:
        """Verify explored boolean grid exists and is initially all False."""
        self.assertIn(0, self.game_map.explored)
        self.assertIsInstance(self.game_map.explored[0], np.ndarray)
        self.assertEqual(self.game_map.explored[0].shape, (200, 200))
        self.assertEqual(self.game_map.explored[0].dtype, bool)
        self.assertFalse(np.any(self.game_map.explored[0]))

        # Checking is_explored for arbitrary coordinates
        self.assertFalse(self.game_map.is_explored(100, 100, 0))
        self.assertFalse(self.game_map.is_explored(0, 0, 0))
        self.assertFalse(self.game_map.is_explored(199, 199, 0))

    def test_set_and_query_explored(self) -> None:
        """Verify set_explored marks single tiles and synchronizes with Tile.explored."""
        self.game_map.set_explored(50, 60, 0, True)
        self.assertTrue(self.game_map.is_explored(50, 60, 0))
        self.assertTrue(self.game_map.explored[0][50, 60])
        self.assertTrue(self.game_map.explored[0][50][60])

        tile = self.game_map.get_tile(50, 60, 0)
        self.assertIsNotNone(tile)
        self.assertTrue(tile.explored)

        # Unexplored neighbor remains False
        self.assertFalse(self.game_map.is_explored(50, 61, 0))

        # Can unset explored
        self.game_map.set_explored(50, 60, 0, False)
        self.assertFalse(self.game_map.is_explored(50, 60, 0))
        self.assertFalse(tile.explored)

    def test_multi_level_explored_auto_generation(self) -> None:
        """Verify accessing Z=1 automatically generates the explored grid."""
        self.assertFalse(self.game_map.is_explored(10, 10, 1))
        self.assertIn(1, self.game_map.explored)
        self.assertEqual(self.game_map.explored[1].shape, (200, 200))

        self.game_map.set_explored(10, 10, 1, True)
        self.assertTrue(self.game_map.is_explored(10, 10, 1))
        # Level 0 remains untouched
        self.assertFalse(self.game_map.is_explored(10, 10, 0))

    def test_out_of_bounds_explored(self) -> None:
        """Verify out-of-bounds coordinates return False safely without raising exceptions."""
        self.assertFalse(self.game_map.is_explored(-1, 0, 0))
        self.assertFalse(self.game_map.is_explored(200, 100, 0))
        self.assertFalse(self.game_map.is_explored(50, -5, 0))
        self.assertFalse(self.game_map.is_explored(50, 205, 0))


class TestVisibilityMarksExplored(unittest.TestCase):
    """Test suite for VisibilitySystem marking FOV tiles as explored."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)

    def test_fov_marks_tiles_explored(self) -> None:
        """Verify initial frame FOV calculation marks visible tiles as explored."""
        esper.process()
        viewshed = esper.component_for_entity(self.player, Viewshed)
        pos = esper.component_for_entity(self.player, Position)

        self.assertGreater(len(viewshed.visible_tiles), 0)
        # Player position must be explored
        self.assertTrue(self.game_map.is_explored(pos.x, pos.y, pos.z))

        # All tiles in FOV must be explored
        for vx, vy in viewshed.visible_tiles:
            self.assertTrue(
                self.game_map.is_explored(vx, vy, pos.z),
                f"Tile at ({vx}, {vy}, {pos.z}) in FOV should be marked explored",
            )
            tile = self.game_map.get_tile(vx, vy, pos.z)
            self.assertTrue(tile.explored)

    def test_exploration_persists_when_player_moves(self) -> None:
        """Verify tiles remain explored when player moves away and they exit active FOV."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Stand at (100, 100, 0)
        pos.x = 100
        pos.y = 100
        esper.process()
        first_visible = set(viewshed.visible_tiles)

        # Move far away to (150, 150, 0)
        pos.x = 150
        pos.y = 150
        esper.process()

        # Previous position is no longer in active FOV
        self.assertFalse(viewshed.is_visible(100, 100))

        # But it MUST STILL BE EXPLORED!
        self.assertTrue(self.game_map.is_explored(100, 100, 0))
        for vx, vy in first_visible:
            self.assertTrue(self.game_map.is_explored(vx, vy, 0))


class TestRenderSystemFogOfWarAndRoofs(unittest.TestCase):
    """Test suite for Fog of War tile rendering, muted colors, and Roof generation."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.render_system = RenderSystem(game_map=self.game_map)

    def test_unexplored_tile_not_rendered(self) -> None:
        """Verify an unexplored tile outside FOV returns None (not rendered)."""
        viewshed = Viewshed(radius=10, visible_tiles=set())
        # Tile (10, 10, 0) is unexplored and not in FOV
        info = self.render_system.get_tile_render_info(10, 10, 0, active_viewshed=viewshed)
        self.assertIsNone(info, "Unexplored tile outside FOV should not be rendered")

    def test_tile_in_fov_rendered_with_bright_colors(self) -> None:
        """Verify a tile currently in FOV renders with normal bright colors."""
        viewshed = Viewshed(radius=10, visible_tiles={(50, 50)})
        self.game_map.set_explored(50, 50, 0, True)

        # Floor tile (normally char='.', color='gray')
        floor_tile = self.game_map.get_tile(50, 50, 0)
        info = self.render_system.get_tile_render_info(50, 50, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info)
        char, color = info
        self.assertEqual(char, floor_tile.char)
        self.assertEqual(color, floor_tile.color)

        # Wall tile (normally char='#', color='white')
        self.game_map.set_tile(50, 50, 0, Tile.wall(room_id=None))
        info_wall = self.render_system.get_tile_render_info(50, 50, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info_wall)
        char_w, color_w = info_wall
        self.assertEqual(char_w, "#")
        self.assertEqual(color_w, "white")

    def test_exterior_tile_explored_not_in_fov_rendered_muted(self) -> None:
        """Verify an exterior tile (room_id=None) explored but NOT in FOV renders in dark gray."""
        viewshed = Viewshed(radius=10, visible_tiles=set())  # (50, 50) is NOT in visible_tiles
        self.game_map.set_explored(50, 50, 0, True)

        info = self.render_system.get_tile_render_info(50, 50, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info)
        char, color = info
        self.assertEqual(char, ".")
        self.assertEqual(color, "dark gray")

    def test_interior_tile_explored_not_in_fov_renders_roof(self) -> None:
        """Verify an interior tile (room_id is not None) explored but NOT in FOV renders as Roof ('^', 'brown')."""
        viewshed = Viewshed(radius=10, visible_tiles=set())
        # Tag tile with room_id=1
        self.game_map.set_tile(60, 60, 0, Tile.floor(room_id=1))
        self.game_map.set_explored(60, 60, 0, True)

        info = self.render_system.get_tile_render_info(60, 60, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info)
        char, color = info
        self.assertEqual(char, "^", "Explored interior tile outside FOV should render Roof char '^'")
        self.assertEqual(color, "brown", "Explored interior tile outside FOV should render Roof color 'brown'")

        # Test outer wall with room_id renders as '#' (never as roof)
        self.game_map.set_tile(61, 60, 0, Tile.wall(room_id=1))
        self.game_map.set_explored(61, 60, 0, True)
        info_wall = self.render_system.get_tile_render_info(61, 60, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info_wall)
        char_w, color_w = info_wall
        self.assertEqual(char_w, "#", "Outer wall with room_id outside FOV should render as wall '#'")
        self.assertEqual(color_w, "dark gray")

    def test_interior_tile_in_fov_does_not_render_roof(self) -> None:
        """Verify an interior tile currently IN active FOV renders normally, NOT as roof."""
        viewshed = Viewshed(radius=10, visible_tiles={(60, 60)}, current_room_id=1)
        self.game_map.set_tile(60, 60, 0, Tile.floor(room_id=1))
        self.game_map.set_explored(60, 60, 0, True)

        info = self.render_system.get_tile_render_info(60, 60, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info)
        char, color = info
        self.assertEqual(char, ".", "Interior tile inside FOV should render normal character '.'")
        self.assertEqual(color, "gray")


class TestEntityFogOfWarHiding(unittest.TestCase):
    """Test suite ensuring entities (NPCs, items) are only rendered when in active FOV."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)

    def test_entity_hidden_when_tile_explored_but_not_in_fov(self) -> None:
        """Verify an NPC or item entity is hidden when its tile is explored but outside active FOV."""
        # Spawn an NPC goblin 'g' at (120, 120, 0)
        npc = esper.create_entity()
        esper.add_component(npc, Position(x=120, y=120, z=0))
        esper.add_component(npc, Renderable(char="g", color="green", layer=1))

        # Mark the tile (120, 120, 0) as explored
        self.game_map.set_explored(120, 120, 0, True)

        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Player is at (100, 100, 0) - distance to (120, 120) is ~28 > radius 15
        pos.x = 100
        pos.y = 100
        esper.process()

        self.assertFalse(viewshed.is_visible(120, 120))
        self.assertTrue(self.game_map.is_explored(120, 120, 0))

        # RenderSystem check: NPC must not be visible to player
        render_system = esper.get_processor(RenderSystem)
        self.assertFalse(
            render_system.is_entity_rendered(
                Position(120, 120, 0), active_viewshed=viewshed
            ),
            "NPC should be hidden in Fog of War even if tile is explored",
        )

    def test_entity_rendered_when_in_active_fov(self) -> None:
        """Verify an NPC is rendered when player moves close enough to have it in active FOV."""
        npc = esper.create_entity()
        esper.add_component(npc, Position(x=102, y=102, z=0))
        esper.add_component(npc, Renderable(char="g", color="green", layer=1))

        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Player at (101, 101, 0) - adjacent to NPC
        pos.x = 101
        pos.y = 101
        esper.process()

        self.assertTrue(viewshed.is_visible(102, 102))
        render_system = esper.get_processor(RenderSystem)
        self.assertTrue(
            render_system.is_entity_rendered(
                Position(102, 102, 0), active_viewshed=viewshed
            )
        )


class TestFullTavernFogOfWarAndRoofs(unittest.TestCase):
    """Integration test verifying full Tavern behavior: entry, exploration, exit, and roof viewing."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        esper.process()

    def test_tavern_interior_becomes_roof_after_player_leaves(self) -> None:
        """When player explores Tavern and steps outside, interior tiles must render as Roof ('^', 'brown')."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)
        render_system = esper.get_processor(RenderSystem)

        # 1. Player is inside Tavern Main Room at spawn (100, 100, 0)
        self.assertEqual(viewshed.current_room_id, 1)
        self.assertTrue(self.game_map.is_explored(100, 100, 0))

        # Main Room floor inside FOV renders normally ('.', 'gray')
        info = render_system.get_tile_render_info(100, 100, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info)
        self.assertEqual(info[0], ".")
        self.assertEqual(info[1], "gray")

        # 2. Open exterior door and step outside to (101, 105, 0)
        # Main Room exterior door is at (101, 103, 0)
        pos.x = 101
        pos.y = 115  # 12 tiles south, outside FOV of (100, 100)
        esper.process()

        self.assertIsNone(viewshed.current_room_id)
        self.assertFalse(viewshed.inside_structure)
        self.assertFalse(viewshed.is_visible(100, 100))
        self.assertTrue(self.game_map.is_explored(100, 100, 0))

        # 3. Tavern interior at (100, 100) has room_id=1, is explored, but NOT in FOV -> ROOF!
        outside_info = render_system.get_tile_render_info(100, 100, 0, active_viewshed=viewshed)
        self.assertIsNotNone(outside_info)
        self.assertEqual(
            outside_info[0],
            "^",
            "Tavern interior tile viewed from outside should render as roof '^'",
        )
        self.assertEqual(
            outside_info[1],
            "brown",
            "Tavern interior tile viewed from outside should render as roof color 'brown'",
        )


if __name__ == "__main__":
    unittest.main()
