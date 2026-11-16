"""Unit and integration tests for Mount & Blade style overworld travel and map transitions.

Tests:
1. SurvivalStats component (Food, Water, max values, consumption, starvation/dehydration).
2. WorldClock progression (advancing hours, rollover to days, formatted time).
3. Regional Movement System:
   - In GameState.REGIONAL_MAP, arrow keys move player exactly 1 regional tile.
   - Clamped within regional map boundaries.
4. Resource Drain:
   - Each step on Regional Map advances WorldClock by 4 hours.
   - Each step deducts 1 Food and 1 Water from SurvivalStats.
   - Moving on Local Map does NOT drain Food/Water at this extreme rate.
5. Descending to Local Map:
   - Pressing ENTER on Regional Map switches to GameState.LOCAL_MAP.
   - Triggers LocalMapGenerator with exact Biome, Elevation, and Moisture of the current RegionalTile.
   - Places player at center (100, 100) of the newly generated 200x200 map.
6. Ascending to Regional Map:
   - Reaching extreme edges (X=0, 199, Y=0, 199) on Local Map ascends to Regional Map.
   - Pressing SHIFT+ENTER on Local Map ascends to Regional Map.
   - All local map entities (herbs, doors, npcs, etc.) are garbage-collected.
   - Player entity and items in player inventory are preserved.
"""

import unittest
from bearlibterminal import terminal
import esper
import numpy as np

from components import (
    Energy,
    Inventory,
    Item,
    MovementIntent,
    Name,
    Player,
    Position,
    RegionalPosition,
    RenderOrder,
    Renderable,
    SurvivalStats,
    Viewshed,
)
from game_map import GameMap, Tile
from game_state import GameState, GameStateManager
from regional_map_generator import BiomeType, RegionalMap, RegionalMapGenerator, RegionalTile
from systems import (
    CombatLog,
    DoorSystem,
    InputSystem,
    MapTransitionSystem,
    MovementSystem,
    RegionalMovementSystem,
    TurnManagementSystem,
)
from world_clock import WorldClock, global_world_clock


class TestOverworldAndMapTransitions(unittest.TestCase):
    """Test suite for Mount & Blade overworld mechanics, time, survival, and map transitions."""

    def setUp(self) -> None:
        """Reset ECS database and processors before each test."""
        esper.clear_database()
        for p in list(esper._processors):
            esper.remove_processor(type(p))
        global_world_clock.reset(year=1, day=1, hour=8, minute=0)

    def test_survival_stats_component(self) -> None:
        """Verify SurvivalStats tracks Food (max 100) and Water (max 100) with proper clamping."""
        surv = SurvivalStats(food=100, max_food=100, water=100, max_water=100)
        self.assertEqual(surv.food, 100)
        self.assertEqual(surv.water, 100)
        self.assertFalse(surv.is_starving)
        self.assertFalse(surv.is_dehydrated)

        # Consume resources
        f_lost, w_lost = surv.consume(food_amount=10, water_amount=15)
        self.assertEqual(f_lost, 10)
        self.assertEqual(w_lost, 15)
        self.assertEqual(surv.food, 90)
        self.assertEqual(surv.water, 85)

        # Clamp at zero
        surv.consume(food_amount=200, water_amount=200)
        self.assertEqual(surv.food, 0)
        self.assertEqual(surv.water, 0)
        self.assertTrue(surv.is_starving)
        self.assertTrue(surv.is_dehydrated)

        # Restore
        surv.restore(food_amount=50, water_amount=60)
        self.assertEqual(surv.food, 50)
        self.assertEqual(surv.water, 60)

        # Clamp at max
        surv.restore(food_amount=100, water_amount=100)
        self.assertEqual(surv.food, 100)
        self.assertEqual(surv.water, 100)

    def test_world_clock_progression(self) -> None:
        """Verify WorldClock advances hours, rolls over days, and formats time string."""
        clock = WorldClock(year=1, day=1, hour=8, minute=0)
        self.assertEqual(clock.time_str, "Day 1, 08:00")

        # Advance 4 hours
        clock.advance_hours(4)
        self.assertEqual(clock.hour, 12)
        self.assertEqual(clock.day, 1)
        self.assertEqual(clock.time_str, "Day 1, 12:00")

        # Advance 14 hours (hour 26 -> next day, hour 2)
        clock.advance_hours(14)
        self.assertEqual(clock.day, 2)
        self.assertEqual(clock.hour, 2)
        self.assertEqual(clock.time_str, "Day 2, 02:00")

    def test_regional_movement_and_resource_drain(self) -> None:
        """Verify pressing arrow keys moves player 1 regional tile, advances 4h, and drains 1 food/water."""
        reg_map = RegionalMapGenerator(width=80, height=50, num_cells=15, seed=42).generate()
        clock = WorldClock(year=1, day=1, hour=8, minute=0)
        combat_log = CombatLog()
        state_mgr = GameStateManager(initial_state=GameState.REGIONAL_MAP)

        reg_movement_sys = RegionalMovementSystem(
            regional_map=reg_map,
            state_manager=state_mgr,
            world_clock=clock,
            combat_log=combat_log,
        )

        player = esper.create_entity(
            Player(),
            RegionalPosition(x=20, y=20),
            SurvivalStats(food=100, max_food=100, water=100, max_water=100),
        )

        # 1. Step East (+1, 0)
        moved = reg_movement_sys.move_player(player, dx=1, dy=0)
        self.assertTrue(moved)
        reg_pos = esper.component_for_entity(player, RegionalPosition)
        surv = esper.component_for_entity(player, SurvivalStats)

        self.assertEqual((reg_pos.x, reg_pos.y), (21, 20), "Must move exactly ONE regional tile")
        self.assertEqual(clock.hour, 12, "Must advance WorldClock by 4 hours per step")
        self.assertEqual(surv.food, 99, "Must deduct 1 Food per regional step")
        self.assertEqual(surv.water, 99, "Must deduct 1 Water per regional step")

        # 2. Step South (0, +1)
        reg_movement_sys.move_player(player, dx=0, dy=1)
        self.assertEqual((reg_pos.x, reg_pos.y), (21, 21))
        self.assertEqual(clock.hour, 16)
        self.assertEqual(surv.food, 98)
        self.assertEqual(surv.water, 98)

    def test_local_map_movement_does_not_drain_survival_stats(self) -> None:
        """Verify moving on the Local Map does NOT drain Food/Water at the regional 4-hour rate."""
        game_map = GameMap(width=200, height=200)
        clock = WorldClock(year=1, day=1, hour=8, minute=0)
        combat_log = CombatLog()
        turn_sys = TurnManagementSystem(combat_log=combat_log)
        state_mgr = GameStateManager(initial_state=GameState.LOCAL_MAP)

        movement_sys = MovementSystem(
            game_map=game_map,
            state_manager=state_mgr,
            turn_system=turn_sys,
        )

        player = esper.create_entity(
            Player(),
            Position(x=50, y=50, z=0),
            Energy(current=100, max_energy=100),
            SurvivalStats(food=100, max_food=100, water=100, max_water=100),
        )

        # Move on local map
        esper.add_component(player, MovementIntent(dx=1, dy=0, dz=0))
        movement_sys.process()

        surv = esper.component_for_entity(player, SurvivalStats)
        self.assertEqual(surv.food, 100, "Local movement must NOT drain food")
        self.assertEqual(surv.water, 100, "Local movement must NOT drain water")
        self.assertEqual(clock.hour, 8, "Local movement must NOT advance WorldClock by 4 hours")

    def test_descend_to_local_map_inherits_regional_data_and_centers_player(self) -> None:
        """Verify pressing ENTER on Regional Map descends to Local Map, inheriting regional data, centered @."""
        reg_map = RegionalMapGenerator(width=80, height=50, num_cells=15, seed=77).generate()
        state_mgr = GameStateManager(initial_state=GameState.REGIONAL_MAP)
        combat_log = CombatLog()

        # Place player on a known regional tile (e.g. at 25, 25)
        regional_tile = reg_map.get_regional_tile(25, 25)
        player = esper.create_entity(
            Player(),
            RegionalPosition(x=25, y=25),
            Position(x=0, y=0, z=0),
            SurvivalStats(food=100, water=100),
            Viewshed(radius=15),
        )

        transition_sys = MapTransitionSystem(
            state_manager=state_mgr,
            regional_map=reg_map,
            combat_log=combat_log,
        )

        # Descend to local map
        new_map = transition_sys.descend_to_local_map(player)
        self.assertIsNotNone(new_map)
        self.assertEqual(new_map.width, 200)
        self.assertEqual(new_map.height, 200)

        # 1. State must switch to LOCAL_MAP
        self.assertEqual(state_mgr.state, GameState.LOCAL_MAP)

        # 2. Player must be placed at the center (100, 100) or adjacent walkable
        player_pos = esper.component_for_entity(player, Position)
        self.assertAlmostEqual(player_pos.x, 100, delta=5, msg="Player must spawn at center of 200x200 map")
        self.assertAlmostEqual(player_pos.y, 100, delta=5, msg="Player must spawn at center of 200x200 map")
        self.assertEqual(player_pos.z, int(regional_tile.base_elevation))

        # 3. Ground tiles should match the regional tile biome
        dominant_biome = regional_tile.dominant_biome
        b_val = dominant_biome.value if hasattr(dominant_biome, "value") else str(dominant_biome)
        if "desert" in b_val.lower():
            # In desert, ground is yellow
            tile = new_map.get_tile(player_pos.x, player_pos.y, player_pos.z)
            self.assertEqual(tile.color, "yellow")

    def test_ascend_to_regional_map_on_shift_enter_and_cleanup(self) -> None:
        """Verify pressing SHIFT+ENTER ascends to Regional Map and garbage-collects wilderness entities."""
        reg_map = RegionalMapGenerator(width=80, height=50, num_cells=15, seed=12).generate()
        state_mgr = GameStateManager(initial_state=GameState.LOCAL_MAP)
        combat_log = CombatLog()

        player = esper.create_entity(
            Player(),
            Position(x=50, y=50, z=0),
            RegionalPosition(x=10, y=10),
            Inventory(max_capacity=20),
        )

        # Add an item to player inventory (MUST NOT be deleted)
        inv_item = esper.create_entity(
            Item(name="Healing Salve", weight=0.5),
            Name("Healing Salve"),
        )
        inv = esper.component_for_entity(player, Inventory)
        inv.add_item(inv_item)

        # Spawn temporary local map entities (MUST BE DELETED)
        ground_herb = esper.create_entity(
            Position(x=55, y=55, z=0),
            Renderable(char="*", color="bright green", layer=1, render_order=RenderOrder.ITEM),
            Item(name="Kingsfoil", weight=0.1),
        )
        dummy_npc = esper.create_entity(
            Position(x=52, y=50, z=0),
            Name("Training Dummy"),
        )

        transition_sys = MapTransitionSystem(
            state_manager=state_mgr,
            regional_map=reg_map,
            combat_log=combat_log,
        )

        # Trigger ascend via SHIFT+ENTER
        deleted_count = transition_sys.ascend_to_regional_map(player)

        # 1. State must switch to REGIONAL_MAP
        self.assertEqual(state_mgr.state, GameState.REGIONAL_MAP)

        # 2. Local entities deleted
        self.assertFalse(esper.entity_exists(ground_herb), "Ground herb must be garbage collected")
        self.assertFalse(esper.entity_exists(dummy_npc), "Local NPC must be garbage collected")

        # 3. Player and inventory item preserved
        self.assertTrue(esper.entity_exists(player), "Player entity must be preserved")
        self.assertTrue(esper.entity_exists(inv_item), "Player inventory items must be preserved")
        self.assertIn(inv_item, inv.items)

    def test_ascend_to_regional_map_when_reaching_extreme_edge(self) -> None:
        """Verify reaching extreme edges (X=0, X=199, Y=0, or Y=199) ascends to Regional Map."""
        game_map = GameMap(width=200, height=200)
        game_map.set_tile(0, 50, 0, Tile.floor())
        reg_map = RegionalMapGenerator(width=80, height=50, num_cells=15, seed=33).generate()
        state_mgr = GameStateManager(initial_state=GameState.LOCAL_MAP)
        combat_log = CombatLog()

        player = esper.create_entity(
            Player(),
            Position(x=1, y=50, z=0),
            RegionalPosition(x=15, y=15),
            Inventory(max_capacity=20),
            Energy(current=100, max_energy=100),
        )

        # Local ground herb that should be cleaned up on edge transition
        ground_herb = esper.create_entity(
            Position(x=5, y=50, z=0),
            Item(name="Bloodweed"),
        )

        transition_sys = MapTransitionSystem(
            state_manager=state_mgr,
            regional_map=reg_map,
            game_map=game_map,
            combat_log=combat_log,
        )

        movement_sys = MovementSystem(
            game_map=game_map,
            state_manager=state_mgr,
            transition_system=transition_sys,
        )

        # Move left towards edge (target_x = 0)
        esper.add_component(player, MovementIntent(dx=-1, dy=0, dz=0))
        movement_sys.process()

        # Player must have reached X=0 and ascended to REGIONAL_MAP
        player_pos = esper.component_for_entity(player, Position)
        self.assertEqual(player_pos.x, 0, "Player must reach extreme edge X=0")
        self.assertEqual(state_mgr.state, GameState.REGIONAL_MAP, "State must switch to REGIONAL_MAP")
        self.assertFalse(esper.entity_exists(ground_herb), "Local map entities must be cleaned up")
        self.assertTrue(esper.entity_exists(player), "Player entity must be preserved")

    def test_input_system_regional_navigation_and_enter_descend(self) -> None:
        """Verify InputSystem handles arrow keys in REGIONAL_MAP and ENTER descending."""
        reg_map = RegionalMapGenerator(width=80, height=50, num_cells=15, seed=90).generate()
        state_mgr = GameStateManager(initial_state=GameState.REGIONAL_MAP)
        clock = WorldClock(year=1, day=1, hour=8, minute=0)
        combat_log = CombatLog()

        player = esper.create_entity(
            Player(),
            RegionalPosition(x=30, y=30),
            Position(x=0, y=0, z=0),
            SurvivalStats(food=100, max_food=100, water=100, max_water=100),
            Viewshed(radius=15),
        )

        reg_movement_sys = RegionalMovementSystem(
            regional_map=reg_map,
            state_manager=state_mgr,
            world_clock=clock,
            combat_log=combat_log,
        )

        transition_sys = MapTransitionSystem(
            state_manager=state_mgr,
            regional_map=reg_map,
            combat_log=combat_log,
        )

        input_sys = InputSystem(
            state_manager=state_mgr,
            regional_movement_system=reg_movement_sys,
            transition_system=transition_sys,
        )

        # Press RIGHT arrow key
        input_sys.process(key=terminal.TK_RIGHT)

        reg_pos = esper.component_for_entity(player, RegionalPosition)
        surv = esper.component_for_entity(player, SurvivalStats)
        self.assertEqual((reg_pos.x, reg_pos.y), (31, 30))
        self.assertEqual(clock.hour, 12)
        self.assertEqual(surv.food, 99)
        self.assertEqual(surv.water, 99)

        # Press ENTER key to descend
        input_sys.process(key=terminal.TK_ENTER)
        self.assertEqual(state_mgr.state, GameState.LOCAL_MAP)
        player_pos = esper.component_for_entity(player, Position)
        self.assertAlmostEqual(player_pos.x, 100, delta=5)
        self.assertAlmostEqual(player_pos.y, 100, delta=5)

    def test_cannot_move_on_regional_map_without_ascending(self) -> None:
        """Verify you cannot move on the regional map without ascending from the tile you are in."""
        reg_map = RegionalMapGenerator(width=80, height=50, num_cells=15, seed=55).generate()
        state_mgr = GameStateManager(initial_state=GameState.REGIONAL_MAP)
        clock = WorldClock(year=1, day=1, hour=8, minute=0)
        combat_log = CombatLog()

        # Player is currently descended into a local tile (is_descended=True)
        player = esper.create_entity(
            Player(),
            RegionalPosition(x=20, y=20, is_descended=True),
            SurvivalStats(food=100, max_food=100, water=100, max_water=100),
        )

        reg_movement_sys = RegionalMovementSystem(
            regional_map=reg_map,
            state_manager=state_mgr,
            world_clock=clock,
            combat_log=combat_log,
        )

        transition_sys = MapTransitionSystem(
            state_manager=state_mgr,
            regional_map=reg_map,
            combat_log=combat_log,
        )

        # 1. Attempt to move on regional map while still descended
        moved = reg_movement_sys.move_player(player, dx=1, dy=0)
        self.assertFalse(moved, "Must not be able to move on regional map without ascending")
        reg_pos = esper.component_for_entity(player, RegionalPosition)
        surv = esper.component_for_entity(player, SurvivalStats)
        self.assertEqual((reg_pos.x, reg_pos.y), (20, 20), "Coordinates must not change")
        self.assertEqual(clock.hour, 8, "Clock must not advance when movement is blocked")
        self.assertEqual(surv.food, 100, "Food must not drain when movement is blocked")

        # 2. Now ascend from the local tile
        transition_sys.ascend_to_regional_map(player)
        self.assertFalse(reg_pos.is_descended, "is_descended must be False after ascending")

        # 3. Now movement on the regional map must succeed
        moved_after_ascend = reg_movement_sys.move_player(player, dx=1, dy=0)
        self.assertTrue(moved_after_ascend, "Movement must succeed after ascending")
        self.assertEqual((reg_pos.x, reg_pos.y), (21, 20))
        self.assertEqual(clock.hour, 12)
        self.assertEqual(surv.food, 99)

    def test_persistent_seed_per_regional_tile(self) -> None:
        """Verify each regional tile has a persistent deterministic seed."""
        reg_map = RegionalMapGenerator(width=80, height=50, num_cells=15, seed=42).generate()

        tile_a1 = reg_map.get_regional_tile(10, 15)
        tile_a2 = reg_map.get_regional_tile(10, 15)
        tile_b = reg_map.get_regional_tile(10, 16)

        self.assertIsNotNone(tile_a1.seed)
        self.assertEqual(tile_a1.seed, tile_a2.seed, "Same tile must always return the exact same seed")
        self.assertNotEqual(tile_a1.seed, tile_b.seed, "Different tiles must receive different seeds")

    def test_different_brooks_on_different_tiles_and_identical_on_same_tile(self) -> None:
        """Verify brook paths vary across regional tiles and are persistent on returning to the same tile."""
        reg_map = RegionalMapGenerator(width=80, height=50, num_cells=15, seed=123).generate()
        state_mgr = GameStateManager(initial_state=GameState.REGIONAL_MAP)
        combat_log = CombatLog()

        player = esper.create_entity(
            Player(),
            RegionalPosition(x=10, y=15, is_descended=False),
            Position(x=0, y=0, z=0),
            SurvivalStats(food=100, water=100),
            Viewshed(radius=15),
        )

        transition_sys = MapTransitionSystem(
            state_manager=state_mgr,
            regional_map=reg_map,
            combat_log=combat_log,
        )

        # 1. Descend into tile (10, 15)
        map_tile_a1 = transition_sys.descend_to_local_map(player)
        self.assertIsNotNone(map_tile_a1)
        z = int(reg_map.get_regional_tile(10, 15).base_elevation)
        water_a1 = {
            (x, y) for x in range(map_tile_a1.width) for y in range(map_tile_a1.height)
            if map_tile_a1.get_tile(x, y, z) and map_tile_a1.get_tile(x, y, z).char == "~"
        }
        self.assertGreater(len(water_a1), 0, "Brook must have carved water tiles")

        # 2. Ascend, travel to a different tile (25, 25), descend
        transition_sys.ascend_to_regional_map(player)
        reg_pos = esper.component_for_entity(player, RegionalPosition)
        reg_pos.x = 25
        reg_pos.y = 25
        map_tile_b = transition_sys.descend_to_local_map(player)
        self.assertIsNotNone(map_tile_b)
        z_b = int(reg_map.get_regional_tile(25, 25).base_elevation)
        water_b = {
            (x, y) for x in range(map_tile_b.width) for y in range(map_tile_b.height)
            if map_tile_b.get_tile(x, y, z_b) and map_tile_b.get_tile(x, y, z_b).char == "~"
        }

        # Water tiles should NOT be identical on different tiles
        self.assertNotEqual(water_a1, water_b, "Brook created on different tiles must NOT be identical")

        # 3. Ascend, travel back to (10, 15), descend again
        transition_sys.ascend_to_regional_map(player)
        reg_pos.x = 10
        reg_pos.y = 15
        map_tile_a2 = transition_sys.descend_to_local_map(player)
        self.assertIsNotNone(map_tile_a2)
        water_a2 = {
            (x, y) for x in range(map_tile_a2.width) for y in range(map_tile_a2.height)
            if map_tile_a2.get_tile(x, y, z) and map_tile_a2.get_tile(x, y, z).char == "~"
        }

        # Water tiles on the same tile must be completely identical and persistent
        self.assertEqual(water_a1, water_a2, "Local map and brook must be persistent on returning to the same tile")


if __name__ == "__main__":
    unittest.main()
