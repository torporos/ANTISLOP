"""Unit and integration tests for:
1. Terrain movement cost (floor=1, hard terrain > 1).
2. Ditching movement energy cost for normal (non-hard) terrain.
3. Hard terrain movement energy cost and blocking when energy is insufficient.
4. Energy regeneration per tick / turn.
5. Passing a turn by pressing the period '.' button.
"""

import unittest
from bearlibterminal import terminal
import esper

from components import Energy, Fighter, MovementIntent, Name, Player, Position, Renderable
from game_map import GameMap, Tile
from systems import CombatLog, DoorSystem, InputSystem, MovementSystem, RenderSystem, TurnManagementSystem
import main


class TestTerrainMovementCostAndRegen(unittest.TestCase):
    """Test suite for terrain movement cost, zero-cost normal movement, and energy regen."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        self.turn_system = main.current_turn_system
        self.combat_log = main.current_combat_log
        esper.process()

    def test_floor_has_movement_cost_one(self) -> None:
        """Verify normal floor has movement_cost=1 and is_hard=False."""
        floor_tile = self.game_map.get_tile(100, 100, 0)
        self.assertIsNotNone(floor_tile)
        self.assertEqual(floor_tile.movement_cost, 1)
        self.assertFalse(floor_tile.is_hard)
        self.assertEqual(self.game_map.get_movement_cost(100, 100, 0), 1)
        self.assertFalse(self.game_map.is_hard_terrain(100, 100, 0))

    def test_normal_movement_costs_zero_energy(self) -> None:
        """Moving on normal floor (movement_cost=1) costs 0 energy and regenerates energy."""
        pos = esper.component_for_entity(self.player, Position)
        energy = esper.component_for_entity(self.player, Energy)

        # Set player energy to 0 on unoccupied tile (100, 101)
        energy.current = 0
        pos.x = 100
        pos.y = 101

        # Move right onto normal floor (101, 101)
        # Even with 0 energy, movement succeeds because normal terrain has 0 energy cost!
        esper.process(key=terminal.TK_RIGHT)

        self.assertEqual((pos.x, pos.y, pos.z), (101, 101, 0))
        # Energy regenerated via turn tick (0 + 10 = 10)
        self.assertEqual(energy.current, 10)

    def test_hard_terrain_requires_and_consumes_energy(self) -> None:
        """Hard terrain (movement_cost > 1 or is_hard=True) costs energy and blocks if insufficient."""
        pos = esper.component_for_entity(self.player, Position)
        energy = esper.component_for_entity(self.player, Energy)

        # Place hard terrain (rubble/mud) at (101, 101, 0) with cost 25
        self.game_map.set_tile(101, 101, 0, Tile.hard_floor(movement_cost=25))
        self.assertTrue(self.game_map.is_hard_terrain(101, 101, 0))
        self.assertEqual(self.game_map.get_movement_cost(101, 101, 0), 25)

        # 1. Player has only 10 energy (< 25)
        pos.x = 100
        pos.y = 101
        energy.current = 10
        self.combat_log.clear()

        # Try to move into hard terrain
        esper.process(key=terminal.TK_RIGHT)

        # Movement blocked!
        self.assertEqual((pos.x, pos.y, pos.z), (100, 101, 0))
        self.assertEqual(energy.current, 10)
        latest = self.combat_log.get_latest(1)
        self.assertIn("Terrain is too hard to cross", latest[0])

        # 2. Player has 50 energy (>= 25)
        energy.current = 50
        self.combat_log.clear()

        esper.process(key=terminal.TK_RIGHT)

        # Successfully moved into hard terrain!
        self.assertEqual((pos.x, pos.y, pos.z), (101, 101, 0))
        # Energy consumed 25. Regeneration is limited only to when energy IS NOT consumed, so net 50 - 25 = 25
        self.assertEqual(energy.current, 25)

        # On the next turn, pass turn (no energy consumed): energy regenerates +10 -> 35
        esper.process(key=ord("."))
        self.assertEqual(energy.current, 35)

    def test_energy_regeneration_on_turn_tick(self) -> None:
        """Energy regenerates each tick up to max_energy."""
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 20

        self.turn_system.tick()
        self.assertEqual(energy.current, 30)

        self.turn_system.tick()
        self.assertEqual(energy.current, 40)

        energy.current = 98
        self.turn_system.tick()
        self.assertEqual(energy.current, 100)


class TestPassTurnPeriodButton(unittest.TestCase):
    """Test suite for passing a turn using the period '.' button."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        self.turn_system = main.current_turn_system
        self.combat_log = main.current_combat_log
        esper.process()

    def test_pressing_period_passes_turn_and_regenerates_energy(self) -> None:
        """Pressing '.' button advances the turn, regenerates energy, and logs wait message."""
        pos = esper.component_for_entity(self.player, Position)
        energy = esper.component_for_entity(self.player, Energy)

        initial_x, initial_y, initial_z = pos.x, pos.y, pos.z
        energy.current = 40
        self.combat_log.clear()

        # Press '.' (ord('.'))
        esper.process(key=ord("."))

        # Position unchanged
        self.assertEqual((pos.x, pos.y, pos.z), (initial_x, initial_y, initial_z))

        # Energy regenerated by 10 (40 -> 50)
        self.assertEqual(energy.current, 50)

        # Combat log records wait message
        latest = self.combat_log.get_latest(1)
        self.assertGreater(len(latest), 0)
        self.assertIn("Player waits a turn.", latest[0])

    def test_pressing_tk_period_constant_passes_turn(self) -> None:
        """Pressing terminal.TK_PERIOD constant also passes turn."""
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 60
        self.combat_log.clear()

        esper.process(key=terminal.TK_PERIOD)

        self.assertEqual(energy.current, 70)
        latest = self.combat_log.get_latest(1)
        self.assertIn("Player waits a turn.", latest[0])


if __name__ == "__main__":
    unittest.main()
