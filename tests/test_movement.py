"""Unit and integration tests for ECS movement and 3D Z-level tracking."""

import unittest
from bearlibterminal import terminal
import esper

from components import MovementIntent, Player, Position, Renderable
from systems import InputSystem, MovementSystem, RenderSystem
import main


class TestECSMovement(unittest.TestCase):
    """Test suite for ECS components and movement systems."""

    def setUp(self) -> None:
        """Reset ECS world and register fresh systems before each test."""
        self.player = main.init_ecs()

    def test_initial_state(self) -> None:
        """Verify initial player position and components on the 200x200 map."""
        pos = esper.component_for_entity(self.player, Position)
        rend = esper.component_for_entity(self.player, Renderable)

        # Centered on 200x200 map
        self.assertEqual(pos.x, 100)
        self.assertEqual(pos.y, 100)
        self.assertEqual(pos.z, 0)
        self.assertEqual(rend.char, "@")
        self.assertEqual(rend.color, "white")
        self.assertTrue(esper.has_component(self.player, Player))

    def test_arrow_keys_movement(self) -> None:
        """Verify 4-directional arrow key movement on unoccupied tiles."""
        pos = esper.component_for_entity(self.player, Position)
        # Position player on unoccupied floor tile at (100, 101)
        pos.x = 100
        pos.y = 101

        # Move Right
        esper.process(key=terminal.TK_RIGHT)
        self.assertEqual((pos.x, pos.y, pos.z), (101, 101, 0))

        # Move Down
        esper.process(key=terminal.TK_DOWN)
        self.assertEqual((pos.x, pos.y, pos.z), (101, 102, 0))

        # Move Left
        esper.process(key=terminal.TK_LEFT)
        self.assertEqual((pos.x, pos.y, pos.z), (100, 102, 0))

        # Move Up
        esper.process(key=terminal.TK_UP)
        self.assertEqual((pos.x, pos.y, pos.z), (100, 101, 0))

    def test_numpad_movement(self) -> None:
        """Verify 8-directional numpad movement."""
        pos = esper.component_for_entity(self.player, Position)

        # KP_7: North-West (-1, -1)
        esper.process(key=terminal.TK_KP_7)
        self.assertEqual((pos.x, pos.y, pos.z), (99, 99, 0))

        # KP_9: North-East (+1, -1)
        esper.process(key=terminal.TK_KP_9)
        self.assertEqual((pos.x, pos.y, pos.z), (100, 98, 0))

        # KP_1: South-West (-1, +1)
        esper.process(key=terminal.TK_KP_1)
        self.assertEqual((pos.x, pos.y, pos.z), (99, 99, 0))

        # KP_3: South-East (+1, +1)
        esper.process(key=terminal.TK_KP_3)
        self.assertEqual((pos.x, pos.y, pos.z), (100, 100, 0))

        # KP_5: Center / Wait (0, 0)
        esper.process(key=terminal.TK_KP_5)
        self.assertEqual((pos.x, pos.y, pos.z), (100, 100, 0))

    def test_z_level_tracking(self) -> None:
        """Verify Z-level up (<) and down (>) traversal."""
        pos = esper.component_for_entity(self.player, Position)

        # Move up 2 levels
        esper.process(key=ord("<"))
        self.assertEqual(pos.z, 1)

        esper.process(key=ord("<"))
        self.assertEqual(pos.z, 2)

        # Move down 3 levels (into basement)
        esper.process(key=ord(">"))
        self.assertEqual(pos.z, 1)

        esper.process(key=ord(">"))
        self.assertEqual(pos.z, 0)

        esper.process(key=ord(">"))
        self.assertEqual(pos.z, -1)

    def test_boundary_wall_collision(self) -> None:
        """Verify player cannot walk through '#' boundary walls."""
        pos = esper.component_for_entity(self.player, Position)

        # Position player at top-left corner adjacent to boundary walls (1, 1)
        pos.x = 1
        pos.y = 1

        # Attempt to move Left into wall '#' at x=0
        esper.process(key=terminal.TK_LEFT)
        self.assertEqual(pos.x, 1)

        # Attempt to move Up into wall '#' at y=0
        esper.process(key=terminal.TK_UP)
        self.assertEqual(pos.y, 1)

        # Position player at bottom-right corner adjacent to boundary walls (198, 198)
        pos.x = main.MAP_WIDTH - 2
        pos.y = main.MAP_HEIGHT - 2

        # Attempt to move Right into wall '#' at x=199
        esper.process(key=terminal.TK_RIGHT)
        self.assertEqual(pos.x, main.MAP_WIDTH - 2)

        # Attempt to move Down into wall '#' at y=199
        esper.process(key=terminal.TK_DOWN)
        self.assertEqual(pos.y, main.MAP_HEIGHT - 2)

    def test_movement_intent_consumption(self) -> None:
        """Ensure MovementIntent is consumed each frame and does not persist."""
        esper.process(key=terminal.TK_RIGHT)
        self.assertFalse(esper.has_component(self.player, MovementIntent))

    def test_unmapped_keys(self) -> None:
        """Ensure unmapped keys do not alter player position."""
        pos = esper.component_for_entity(self.player, Position)
        original_coords = (pos.x, pos.y, pos.z)

        # Process arbitrary unmapped key (e.g. TK_Z)
        esper.process(key=terminal.TK_Z)
        self.assertEqual((pos.x, pos.y, pos.z), original_coords)

    def test_render_system_execution(self) -> None:
        """Verify RenderSystem executes cleanly with BearLibTerminal open."""
        terminal.open()
        try:
            terminal.set(f"window: size={main.SCREEN_WIDTH}x{main.SCREEN_HEIGHT}")
            # Render at initial Z=0
            esper.process()

            # Move up to Z=1 and render
            esper.process(key=ord("<"))
            pos = esper.component_for_entity(self.player, Position)
            self.assertEqual(pos.z, 1)

            # Move down to Z=-1 and render
            esper.process(key=ord(">"))
            esper.process(key=ord(">"))
            self.assertEqual(pos.z, -1)
        finally:
            terminal.close()


if __name__ == "__main__":
    unittest.main()
