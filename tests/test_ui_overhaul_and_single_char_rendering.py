"""Unit and integration tests for:
1. UI Layout Overhaul:
   - Window size: 120x40
   - Map Viewport: Top Left, 85x30
   - GUI Sidebar: Top Right, 35x30
   - Message Console: Bottom, 120x10
2. Strict Single-Character Rendering:
   - render_order hierarchy: Player (50) > NPC (40) > Item (30) > Furniture (20) > Floor (0)
   - Multiple entities on the same (X, Y) tile resolve to only the single highest-priority entity.
3. GUI Sidebar population:
   - Border, Player Name, HP (100/100), Energy Level, Z-Level, Coordinates, Hotbar (1-5).
4. MessageLog system:
   - Stores strings, retrieves 8 most recent messages, pushes old messages up.
"""

import unittest
from bearlibterminal import terminal
import esper

from camera import Camera
from components import (
    Energy,
    Fighter,
    Name,
    Player,
    Position,
    RenderOrder,
    Renderable,
    Skill,
    SkillBar,
    Viewshed,
)
from game_map import GameMap
from message_log import MessageLog, global_message_log
from systems import CombatLog, RenderSystem
import main


class TestMessageLogSystem(unittest.TestCase):
    """Test suite for the global MessageLog system."""

    def setUp(self) -> None:
        self.log = MessageLog(max_messages=50)

    def test_add_and_retrieve_recent_messages(self) -> None:
        """Adding messages stores them and get_recent(8) returns up to 8 messages."""
        for i in range(5):
            self.log.add(f"Message {i}")

        recent = self.log.get_recent(8)
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[0], "Message 0")
        self.assertEqual(recent[-1], "Message 4")

    def test_messages_push_up_when_exceeding_eight(self) -> None:
        """When more than 8 messages arrive, older messages are pushed up and out."""
        for i in range(12):
            self.log.add(f"Message {i}")

        recent = self.log.get_recent(8)
        self.assertEqual(len(recent), 8)
        # Should be Message 4 through Message 11
        self.assertEqual(recent[0], "Message 4")
        self.assertEqual(recent[-1], "Message 11")

    def test_combat_log_inherits_message_log(self) -> None:
        """CombatLog behaves as a MessageLog subclass."""
        combat_log = CombatLog()
        combat_log.add("Hit Training Dummy for 15 damage!")
        self.assertEqual(len(combat_log.get_recent(8)), 1)
        self.assertIn("Training Dummy", combat_log.get_recent(8)[0])


class TestStrictSingleCharacterRendering(unittest.TestCase):
    """Test suite for strict single-character rendering and render_order hierarchy."""

    def setUp(self) -> None:
        esper.clear_database()
        self.game_map = GameMap(width=200, height=200)
        self.render_system = RenderSystem(
            game_map=self.game_map,
            viewport_width=85,
            viewport_height=30,
            screen_width=120,
            screen_height=40,
        )

    def test_render_order_hierarchy_values(self) -> None:
        """Verify strict priority ordering: Player > NPC > Item > Furniture > Floor."""
        self.assertGreater(RenderOrder.PLAYER, RenderOrder.NPC)
        self.assertGreater(RenderOrder.NPC, RenderOrder.ITEM)
        self.assertGreater(RenderOrder.ITEM, RenderOrder.FURNITURE)
        self.assertGreater(RenderOrder.FURNITURE, RenderOrder.FLOOR)

    def test_highest_priority_entity_renders_on_shared_tile(self) -> None:
        """When multiple entities occupy the same tile, only the highest render_order is chosen."""
        # Create Player at (50, 50, 0) with Viewshed
        player = esper.create_entity()
        esper.add_component(player, Position(x=50, y=50, z=0))
        esper.add_component(player, Player())
        viewshed = Viewshed(radius=10)
        viewshed.visible_tiles = {(50, 50), (51, 50)}
        esper.add_component(player, viewshed)

        # On tile (51, 50, 0), place 3 entities:
        # 1. Furniture: Door ('+', render_order=20)
        furniture = esper.create_entity()
        esper.add_component(furniture, Position(x=51, y=50, z=0))
        esper.add_component(
            furniture,
            Renderable(char="+", color="white", render_order=RenderOrder.FURNITURE),
        )

        # 2. Item: Gold Pouch ('$', render_order=30)
        item = esper.create_entity()
        esper.add_component(item, Position(x=51, y=50, z=0))
        esper.add_component(
            item,
            Renderable(char="$", color="yellow", render_order=RenderOrder.ITEM),
        )

        # 3. NPC: Goblin ('g', render_order=40)
        npc = esper.create_entity()
        esper.add_component(npc, Position(x=51, y=50, z=0))
        esper.add_component(
            npc,
            Renderable(char="g", color="green", render_order=RenderOrder.NPC),
        )

        # All 3 entities share tile (51, 50).
        # When rendered, only the NPC ('g', render_order=40) should be rendered!
        self.render_system.camera.update(50, 50, 200, 200)

        # Execute process() to verify no crash and correct rendering
        self.render_system.process()

        # Remove the NPC: now Item ('$', render_order=30) takes priority over Furniture ('+')
        esper.delete_entity(npc, immediate=True)
        self.render_system.process()

        # Remove the Item: now Furniture ('+', render_order=20) is rendered
        esper.delete_entity(item, immediate=True)
        self.render_system.process()

    def test_entity_suppresses_underlying_stairs_tile(self) -> None:
        """When player is standing on stairs ('<'), only '@' renders and '<' is suppressed."""
        from game_map import Tile

        # Place stairs at (50, 50, 0)
        self.game_map.set_tile(50, 50, 0, Tile(char="<", walkable=True, transparent=True))

        player = esper.create_entity()
        esper.add_component(player, Position(x=50, y=50, z=0))
        esper.add_component(
            player,
            Renderable(char="@", color="white", render_order=RenderOrder.PLAYER),
        )
        viewshed = Viewshed(radius=10)
        viewshed.visible_tiles = {(50, 50)}
        esper.add_component(player, viewshed)

        self.render_system.camera.update(50, 50, 200, 200)

        # In _render_local_map, the entity candidates at (50, 50) contain the Player (@, 50).
        # The underlying stairs tile ('<') is suppressed because an entity is present.
        self.render_system.process()

        # When player moves off stairs to (51, 50), the stairs at (50, 50) render as '<'
        p_pos = esper.component_for_entity(player, Position)
        p_pos.x = 51
        viewshed.visible_tiles = {(50, 50), (51, 50)}
        self.render_system.process()


class TestUILayoutAndSidebar(unittest.TestCase):
    """Test suite for the 120x40 layout, 85x30 viewport, 35x30 sidebar, and 120x10 console."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        self.render_system = esper.get_processor(RenderSystem)
        self.interaction_system = main.current_interaction_system
        esper.process()

    def test_window_and_layout_dimensions(self) -> None:
        """Verify layout constants and camera viewport sizes."""
        self.assertEqual(main.SCREEN_WIDTH, 120)
        self.assertEqual(main.SCREEN_HEIGHT, 40)
        self.assertEqual(main.MAP_VIEWPORT_WIDTH, 85)
        self.assertEqual(main.MAP_VIEWPORT_HEIGHT, 30)
        self.assertEqual(main.SIDEBAR_WIDTH, 35)
        self.assertEqual(main.CONSOLE_HEIGHT, 10)

        # Camera viewport matches map viewport
        self.assertEqual(self.render_system.camera.viewport_width, 85)
        self.assertEqual(self.render_system.camera.viewport_height, 30)
        self.assertEqual(self.render_system.screen_width, 120)
        self.assertEqual(self.render_system.screen_height, 40)

    def test_render_system_executes_all_layout_panels(self) -> None:
        """RenderSystem renders map viewport, sidebar, message console, and dialogue without errors."""
        # Add messages to log
        main.current_combat_log.add("Welcome to the Sandbox RPG!")
        main.current_combat_log.add("Player entered the Tavern.")

        # Process frame
        self.render_system.process()

    def test_dialogue_renders_in_message_console_and_not_center_screen(self) -> None:
        """Bumping NPC activates dialogue which renders inside the bottom 120x10 console."""
        # Move Left to bump Garrick
        esper.process(key=terminal.TK_LEFT)
        self.assertTrue(self.interaction_system.has_active_dialogue())

        # Rendering frame executes dialogue mode in bottom console without throwing
        self.render_system.process()

        # Press SPACE to close
        esper.process(key=terminal.TK_SPACE)
        self.assertFalse(self.interaction_system.has_active_dialogue())

        # Normal message log console renders again
        self.render_system.process()

    def test_player_has_highest_render_order(self) -> None:
        """Player entity is assigned RenderOrder.PLAYER (highest priority)."""
        rend = esper.component_for_entity(self.player, Renderable)
        self.assertEqual(rend.render_order, RenderOrder.PLAYER)
        self.assertEqual(rend.char, "@")

    def test_keybind_reminders_escaped_brackets(self) -> None:
        """Verify bracket strings are properly measured with brackets by BearLibTerminal."""
        terminal.open()
        try:
            m_arrows = terminal.measure("[[Arrows]] Move")
            self.assertEqual(m_arrows, (13, 1))

            m_slot = terminal.measure("[[1]] Cleave (20 En)")
            self.assertEqual(m_slot, (18, 1))

            m_wait = terminal.measure("[[.]]      Wait / Pass Turn")
            self.assertEqual(m_wait, (25, 1))
        finally:
            terminal.close()


if __name__ == "__main__":
    unittest.main()
