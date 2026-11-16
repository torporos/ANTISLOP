"""Unit and integration tests for the Item and Inventory System:

1. ECS Components:
   - Item (name, weight, description)
   - Inventory (items list, max_capacity, add_item, remove_item, is_full)
   - Player entity has Inventory component

2. World Spawn:
   - Test item ('Health Potion', rendered as '!') spawned on the ground near player

3. ItemCollectionSystem:
   - Querying items at tile coordinates (get_items_at)
   - Collecting ground item removes Position component from the map and adds entity to player Inventory
   - Logging message to Message Console
   - Handling empty tile and full inventory edge cases
   - Triggering pickup via 'G' key

4. Inventory Screen State:
   - Pressing 'I' toggles GameState.INVENTORY
   - Local map updates (movement, turns) are paused while in inventory state
   - Pressing 'ESC' closes the inventory screen and restores GameState.LOCAL_MAP
   - Inventory overlay rendering via BearLibTerminal
"""

import unittest
from bearlibterminal import terminal
import esper

from components import (
    Energy,
    Fighter,
    Inventory,
    Item,
    Name,
    Player,
    Position,
    RenderOrder,
    Renderable,
    Viewshed,
)
from game_map import GameMap
from game_state import GameState, GameStateManager
from message_log import MessageLog
from systems import (
    CombatLog,
    InputSystem,
    ItemCollectionSystem,
    MovementSystem,
    RenderSystem,
    TurnManagementSystem,
)
import main


class TestItemAndInventoryComponents(unittest.TestCase):
    """Test suite for Item and Inventory data components."""

    def test_item_component_attributes(self) -> None:
        """Verify Item component holds name, weight, and description."""
        item = Item(name="Health Potion", weight=0.5, description="Restores 25 HP.")
        self.assertEqual(item.name, "Health Potion")
        self.assertEqual(item.weight, 0.5)
        self.assertEqual(item.description, "Restores 25 HP.")

    def test_inventory_capacity_and_helpers(self) -> None:
        """Verify Inventory tracking, capacity bounds, and item addition/removal."""
        inv = Inventory(max_capacity=2)
        self.assertEqual(len(inv.items), 0)
        self.assertFalse(inv.is_full())

        # Add first item entity
        self.assertTrue(inv.add_item(101))
        self.assertEqual(inv.items, [101])
        self.assertFalse(inv.is_full())

        # Add second item entity -> full
        self.assertTrue(inv.add_item(102))
        self.assertEqual(inv.items, [101, 102])
        self.assertTrue(inv.is_full())

        # Adding third item fails
        self.assertFalse(inv.add_item(103))
        self.assertEqual(len(inv.items), 2)

        # Remove item
        self.assertTrue(inv.remove_item(101))
        self.assertEqual(inv.items, [102])
        self.assertFalse(inv.is_full())

        # Remove non-existent item returns False
        self.assertFalse(inv.remove_item(999))


class TestPlayerInventoryAndWorldItemSpawn(unittest.TestCase):
    """Test suite verifying player inventory initialization and test item world spawn."""

    def setUp(self) -> None:
        esper.clear_database()
        self.player = main.init_ecs()
        esper.process()

    def test_player_has_inventory_component(self) -> None:
        """Ensure player entity is spawned with an Inventory component."""
        self.assertTrue(esper.has_component(self.player, Inventory))
        inv = esper.component_for_entity(self.player, Inventory)
        self.assertEqual(inv.max_capacity, 20)
        self.assertEqual(len(inv.items), 0)

    def test_test_item_spawned_near_player(self) -> None:
        """Verify a test item ('Health Potion', char='!') is spawned on the ground near player."""
        player_pos = esper.component_for_entity(self.player, Position)

        # Search for Item components in the world
        potion_entities = []
        for ent, (pos, item, rend) in esper.get_components(Position, Item, Renderable):
            if item.name == "Health Potion":
                potion_entities.append((ent, pos, item, rend))

        self.assertGreaterEqual(len(potion_entities), 1)
        _ent, potion_pos, potion_item, potion_rend = potion_entities[0]

        # Verify attributes
        self.assertEqual(potion_item.name, "Health Potion")
        self.assertEqual(potion_rend.char, "!")
        self.assertEqual(potion_rend.render_order, RenderOrder.ITEM)

        # Verify spawned adjacent/near the player (within 2 tiles)
        dist = abs(potion_pos.x - player_pos.x) + abs(potion_pos.y - player_pos.y)
        self.assertEqual(dist, 1)
        self.assertEqual(potion_pos.z, player_pos.z)


class TestItemCollectionSystem(unittest.TestCase):
    """Test suite for ItemCollectionSystem logic and edge cases."""

    def setUp(self) -> None:
        esper.clear_database()
        self.log = MessageLog()
        self.collection_system = ItemCollectionSystem(message_log=self.log)

        # Create player with Position and Inventory
        self.player = esper.create_entity()
        esper.add_component(self.player, Position(x=10, y=10, z=0))
        esper.add_component(self.player, Player())
        self.inv = Inventory(max_capacity=2)
        esper.add_component(self.player, self.inv)

    def test_collect_item_success(self) -> None:
        """Standing on an item removes Position from map and adds to inventory."""
        potion = esper.create_entity()
        esper.add_component(potion, Position(x=10, y=10, z=0))
        esper.add_component(potion, Item(name="Health Potion", weight=0.5))

        # Collect
        success = self.collection_system.collect_item(self.player)
        self.assertTrue(success)

        # Item Position removed
        self.assertFalse(esper.has_component(potion, Position))

        # Item entity added to player's inventory
        self.assertIn(potion, self.inv.items)
        self.assertEqual(len(self.inv.items), 1)

        # Message logged
        recent = self.log.get_recent(5)
        self.assertIn("Picked up Health Potion.", recent)

    def test_collect_item_when_nothing_on_tile(self) -> None:
        """Calling collect when no item is present logs an informative message."""
        success = self.collection_system.collect_item(self.player)
        self.assertFalse(success)
        self.assertEqual(len(self.inv.items), 0)

        recent = self.log.get_recent(5)
        self.assertIn("There is nothing here to pick up.", recent)

    def test_collect_item_when_inventory_full(self) -> None:
        """Collecting when inventory is at capacity keeps item on ground and logs warning."""
        self.inv.items = [901, 902]  # Already full at capacity 2

        potion = esper.create_entity()
        esper.add_component(potion, Position(x=10, y=10, z=0))
        esper.add_component(potion, Item(name="Health Potion", weight=0.5))

        success = self.collection_system.collect_item(self.player)
        self.assertFalse(success)

        # Item is still on the ground
        self.assertTrue(esper.has_component(potion, Position))
        self.assertNotIn(potion, self.inv.items)

        recent = self.log.get_recent(5)
        self.assertIn("Inventory is full! Cannot pick up Health Potion.", recent)


class TestKeybindGItemPickup(unittest.TestCase):
    """Integration test verifying 'G' key triggers item pickup in the ECS loop."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.state_manager = GameStateManager(initial_state=GameState.LOCAL_MAP)
        self.player = main.init_ecs(game_map=self.game_map, state_manager=self.state_manager)
        esper.process()

    def test_press_g_picks_up_item_under_player(self) -> None:
        """When player is on an item tile, pressing 'G' picks it up."""
        pos = esper.component_for_entity(self.player, Position)
        inv = esper.component_for_entity(self.player, Inventory)

        # Health potion is spawned at (player_x, player_y + 1, player_z)
        potion_x = pos.x
        potion_y = pos.y + 1
        potion_z = pos.z

        # Verify potion exists on ground at potion_y
        potion_ents = main.current_item_collection_system.get_items_at(potion_x, potion_y, potion_z)
        self.assertEqual(len(potion_ents), 1)
        potion_ent = potion_ents[0]

        # Step south onto the potion
        esper.process(key=terminal.TK_DOWN)
        self.assertEqual((pos.x, pos.y, pos.z), (potion_x, potion_y, potion_z))

        # Press 'G' to pick up
        esper.process(key=terminal.TK_G)

        # Verify item was picked up into player inventory
        self.assertIn(potion_ent, inv.items)
        self.assertFalse(esper.has_component(potion_ent, Position))

        # Verify ground tile has 0 items now
        remaining_ground = main.current_item_collection_system.get_items_at(potion_x, potion_y, potion_z)
        self.assertEqual(len(remaining_ground), 0)

        # Verify message logged to combat/message console
        recent = main.current_combat_log.get_recent(5)
        self.assertTrue(any("Picked up Health Potion." in m for m in recent))

    def test_press_g_lowercase_and_ord_char(self) -> None:
        """Pressing ord('g') or ord('G') also successfully triggers pickup."""
        pos = esper.component_for_entity(self.player, Position)
        inv = esper.component_for_entity(self.player, Inventory)

        # Spawn a second potion at player's current position
        gem = esper.create_entity()
        esper.add_component(gem, Position(x=pos.x, y=pos.y, z=pos.z))
        esper.add_component(gem, Item(name="Ruby Gem", weight=0.1))

        # Press ord('g')
        esper.process(key=ord("g"))
        self.assertIn(gem, inv.items)
        self.assertFalse(esper.has_component(gem, Position))


class TestInventoryScreenState(unittest.TestCase):
    """Test suite for GameState.INVENTORY, pausing map updates, and ESC key closure."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.state_manager = GameStateManager(initial_state=GameState.LOCAL_MAP)
        self.player = main.init_ecs(game_map=self.game_map, state_manager=self.state_manager)
        esper.process()

    def test_press_i_opens_inventory_screen(self) -> None:
        """Pressing 'I' changes GameState from LOCAL_MAP to INVENTORY."""
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

        esper.process(key=terminal.TK_I)
        self.assertEqual(self.state_manager.state, GameState.INVENTORY)

    def test_map_updates_paused_in_inventory_mode(self) -> None:
        """While in GameState.INVENTORY, player movement and turns are paused."""
        pos = esper.component_for_entity(self.player, Position)
        initial_coords = (pos.x, pos.y, pos.z)

        # Open inventory
        esper.process(key=terminal.TK_I)
        self.assertEqual(self.state_manager.state, GameState.INVENTORY)

        # Attempt to move in various directions
        esper.process(key=terminal.TK_RIGHT)
        esper.process(key=terminal.TK_DOWN)
        esper.process(key=terminal.TK_LEFT)
        esper.process(key=terminal.TK_UP)

        # Position must not have changed
        self.assertEqual((pos.x, pos.y, pos.z), initial_coords)

    def test_press_esc_closes_inventory_screen(self) -> None:
        """Pressing 'ESC' while in INVENTORY state returns to LOCAL_MAP."""
        # Open inventory
        esper.process(key=terminal.TK_I)
        self.assertEqual(self.state_manager.state, GameState.INVENTORY)

        # Press ESC
        esper.process(key=terminal.TK_ESCAPE)
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

    def test_press_i_again_closes_inventory(self) -> None:
        """Pressing 'I' again while in INVENTORY mode also closes the overlay."""
        esper.process(key=ord("i"))
        self.assertEqual(self.state_manager.state, GameState.INVENTORY)

        esper.process(key=ord("i"))
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

    def test_inventory_overlay_rendering(self) -> None:
        """Verify RenderSystem renders cleanly in INVENTORY mode with items."""
        terminal.open()
        try:
            terminal.set(f"window: size={main.SCREEN_WIDTH}x{main.SCREEN_HEIGHT}")

            # Pick up potion into player inventory
            inv = esper.component_for_entity(self.player, Inventory)
            potion_ent = esper.create_entity()
            esper.add_component(
                potion_ent,
                Item(name="Healing Elixir", weight=0.5, description="Restores 50 HP"),
            )
            inv.add_item(potion_ent)

            # Open inventory
            esper.process(key=terminal.TK_I)
            self.assertEqual(self.state_manager.state, GameState.INVENTORY)

            # Process render pass in INVENTORY state
            esper.process()

            # Close inventory
            esper.process(key=terminal.TK_ESCAPE)
            self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

            # Process render pass back in LOCAL_MAP
            esper.process()
        finally:
            terminal.close()

    def test_inventory_takes_over_map_view_instead_of_rendering_tiles(self) -> None:
        """Verify that in INVENTORY mode, the system renders the inventory panel in the 85x30 map view."""
        render_system = esper.get_processor(RenderSystem)
        self.assertIsNotNone(render_system)

        # Switch to INVENTORY state
        esper.process(key=terminal.TK_I)
        self.assertEqual(self.state_manager.state, GameState.INVENTORY)

        terminal.open()
        try:
            terminal.set(f"window: size={main.SCREEN_WIDTH}x{main.SCREEN_HEIGHT}")
            # Ensure _render_inventory_screen and _render_inventory_view execute cleanly
            render_system._render_inventory_view(self.player)
            render_system.process()
        finally:
            terminal.close()


if __name__ == "__main__":
    unittest.main()
