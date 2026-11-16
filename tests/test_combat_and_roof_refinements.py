"""Unit and integration tests for:
1. Whole roof of a building renders as soon as any part of that building is seen.
2. Roof does not render over the outer walls of the building.
3. Combat ECS Components: Fighter, Energy, SkillBar, Skill.
4. TurnManagementSystem energy replenishment each tick.
5. Cleave skill execution targeting all adjacent tiles, checking energy, dealing damage to dummy, and logging combat messages.
6. Movement and skill action energy consumption.
"""

import unittest
from bearlibterminal import terminal
import esper

from components import (
    Door,
    Energy,
    Fighter,
    MovementIntent,
    Name,
    Player,
    Position,
    Renderable,
    Skill,
    SkillBar,
    Viewshed,
)
from game_map import GameMap, Tile
from systems import (
    CombatLog,
    DoorSystem,
    InputSystem,
    MovementSystem,
    RenderSystem,
    TurnManagementSystem,
    VisibilitySystem,
)
import main


class TestRoofRefinements(unittest.TestCase):
    """Test suite for roof refinements: outer walls preservation and instant full roof display."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        self.render_system = esper.get_processor(RenderSystem)
        esper.process()

    def test_outer_walls_never_render_as_roof(self) -> None:
        """Outer walls of a building must render as '#' and never as roof '^'."""
        viewshed = esper.component_for_entity(self.player, Viewshed)
        # Discover the Tavern building
        self.game_map.discover_building("Tavern")

        # Tavern outer perimeter walls at North (y=97) and South (y=103)
        for bx in range(98, 105):
            # North wall at y=97
            self.assertTrue(self.game_map.is_outer_wall(bx, 97, 0))
            info = self.render_system.get_tile_render_info(bx, 97, 0, active_viewshed=viewshed)
            self.assertIsNotNone(info)
            self.assertEqual(info[0], "#", f"Outer wall at ({bx}, 97) must render as '#' not roof")

            # South wall at y=103 (except doorway at 101)
            if bx != 101:
                self.assertTrue(self.game_map.is_outer_wall(bx, 103, 0))
                info_s = self.render_system.get_tile_render_info(bx, 103, 0, active_viewshed=viewshed)
                self.assertIsNotNone(info_s)
                self.assertEqual(info_s[0], "#", f"Outer wall at ({bx}, 103) must render as '#' not roof")

    def test_whole_roof_renders_when_any_part_of_building_is_seen(self) -> None:
        """As soon as the player sees a wall of the Tavern, its entire roof renders."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Move player outside to (101, 105), south of Tavern exterior door at (101, 103)
        pos.x = 101
        pos.y = 105
        esper.process()

        # Player sees the south wall/door of Tavern at (101, 103)
        self.assertTrue(viewshed.is_visible(101, 103))
        self.assertTrue(self.game_map.is_building_discovered("Tavern"))

        # The interior floor of Kitchen at (108, 99) is NOT in FOV and was never explored
        self.assertFalse(viewshed.is_visible(108, 99))

        # BUT because the building was seen, the interior renders as ROOF ('^', 'brown')!
        info = self.render_system.get_tile_render_info(108, 99, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info, "Interior tile of discovered building should render roof")
        self.assertEqual(info[0], "^", "Whole roof renders as soon as a part of building is seen")
        self.assertEqual(info[1], "brown")

        # Outer wall at (98, 99) renders as '#' not roof
        wall_info = self.render_system.get_tile_render_info(98, 99, 0, active_viewshed=viewshed)
        self.assertIsNotNone(wall_info)
        self.assertEqual(wall_info[0], "#")
        self.assertEqual(wall_info[1], "dark gray")


class TestCombatAndTurnManagement(unittest.TestCase):
    """Test suite for Fighter, Energy, TurnManagementSystem, and Cleave skill."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        self.turn_system = main.current_turn_system
        self.combat_log = main.current_combat_log
        esper.process()

    def test_player_and_dummy_initial_components(self) -> None:
        """Verify Fighter, Energy, and SkillBar are present on player, and dummy exists adjacent."""
        pos = esper.component_for_entity(self.player, Position)
        fighter = esper.component_for_entity(self.player, Fighter)
        energy = esper.component_for_entity(self.player, Energy)
        sbar = esper.component_for_entity(self.player, SkillBar)

        # Player baseline HP derived from CON: 10 CON * 5 = 50 Max HP
        self.assertIn(fighter.hp, (50, 100))
        self.assertIn(fighter.max_hp, (50, 100))
        self.assertEqual(energy.current, 100)
        self.assertGreaterEqual(len(sbar.skills), 1)
        self.assertEqual(sbar.skills[0].name, "Cleave")

        # Find dummy NPC at adjacent position (player.x + 1, player.y, player.z)
        dummy_found = False
        for ent, (d_pos, d_fighter) in esper.get_components(Position, Fighter):
            if ent != self.player and (d_pos.x, d_pos.y, d_pos.z) == (pos.x + 1, pos.y, pos.z):
                dummy_found = True
                self.assertEqual(d_fighter.hp, 50)
                self.assertEqual(d_fighter.max_hp, 50)
                d_name = esper.component_for_entity(ent, Name).name
                self.assertEqual(d_name, "Training Dummy")
                break
        self.assertTrue(dummy_found, "Training Dummy must spawn adjacent to the player")

    def test_turn_system_energy_ticks(self) -> None:
        """Verify tick() replenishes energy for entities with Energy component."""
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 50

        self.turn_system.tick()
        # gain_per_tick is 10
        self.assertEqual(energy.current, 60)

        # Clamps to max_energy
        energy.current = 95
        self.turn_system.tick()
        self.assertEqual(energy.current, 100)

    def test_cleave_skill_execution_and_damage(self) -> None:
        """Pressing '1' executes Cleave, consumes energy, damages adjacent dummy, and logs message."""
        pos = esper.component_for_entity(self.player, Position)
        energy = esper.component_for_entity(self.player, Energy)

        # Find dummy entity
        dummy_ent = None
        for ent, (d_pos, _d_fighter) in esper.get_components(Position, Fighter):
            if ent != self.player:
                dummy_ent = ent
                break
        self.assertIsNotNone(dummy_ent)
        dummy_fighter = esper.component_for_entity(dummy_ent, Fighter)

        self.assertEqual(energy.current, 100)
        self.assertEqual(dummy_fighter.hp, 50)

        # Trigger Cleave by simulating key '1'
        self.combat_log.clear()
        esper.process(key=terminal.TK_1)

        # Cleave damage is 15: Dummy HP drops from 50 to 35
        self.assertEqual(dummy_fighter.hp, 35)

        # Energy consumed: cost 20. Regeneration is limited only to when energy IS NOT consumed, so net 100 - 20 = 80
        self.assertEqual(energy.current, 80)

        # Combat log message was recorded
        messages = self.combat_log.get_latest(1)
        self.assertGreater(len(messages), 0)
        self.assertIn("Player used Cleave! Hit Training Dummy for 15 damage! (35/50 HP)", messages[0])

    def test_cleave_fails_when_energy_insufficient(self) -> None:
        """Cleave cannot be used if player lacks required Energy."""
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 10  # Cleave costs 20

        # Find dummy entity
        dummy_ent = None
        for ent, (d_pos, _d_fighter) in esper.get_components(Position, Fighter):
            if ent != self.player:
                dummy_ent = ent
                break
        dummy_fighter = esper.component_for_entity(dummy_ent, Fighter)
        initial_hp = dummy_fighter.hp

        self.combat_log.clear()
        # Try to use Cleave with insufficient energy
        esper.process(key=terminal.TK_1)

        # No damage dealt
        self.assertEqual(dummy_fighter.hp, initial_hp)
        # Energy unchanged
        self.assertEqual(energy.current, 10)

        # Combat log warns about insufficient energy
        messages = self.combat_log.get_latest(1)
        self.assertGreater(len(messages), 0)
        self.assertIn("Not enough Energy to use Cleave", messages[0])

    def test_cleave_hits_multiple_adjacent_targets(self) -> None:
        """Cleave damages all enemies in the 8 adjacent tiles."""
        pos = esper.component_for_entity(self.player, Position)

        # Spawn a second dummy at (player.x, player.y + 1)
        dummy2 = esper.create_entity()
        esper.add_component(dummy2, Position(x=pos.x, y=pos.y + 1, z=pos.z))
        esper.add_component(dummy2, Name("Goblin Sentry"))
        esper.add_component(dummy2, Fighter(hp=30, max_hp=30))

        # Player has 100 energy
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 100

        self.combat_log.clear()
        self.turn_system.execute_cleave(self.player)

        # Check second dummy took damage
        f2 = esper.component_for_entity(dummy2, Fighter)
        self.assertEqual(f2.hp, 15)

    def test_cleave_hits_nothing_when_no_adjacent_targets(self) -> None:
        """Cleave logs appropriate message when no enemies are adjacent."""
        pos = esper.component_for_entity(self.player, Position)

        # Move player far from dummy to (100, 150, 0)
        pos.x = 100
        pos.y = 150
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 100

        self.combat_log.clear()
        self.turn_system.execute_cleave(self.player)

        messages = self.combat_log.get_latest(1)
        self.assertIn("hit nothing", messages[0])

    def test_defeated_enemy_is_deleted_from_world(self) -> None:
        """When an enemy's HP reaches 0, it is deleted from the ECS database."""
        # Find dummy entity
        dummy_ent = None
        for ent, (d_pos, _d_fighter) in esper.get_components(Position, Fighter):
            if ent != self.player:
                dummy_ent = ent
                break
        self.assertIsNotNone(dummy_ent)
        self.assertTrue(esper.entity_exists(dummy_ent))

        energy = esper.component_for_entity(self.player, Energy)

        # Give player enough energy for 4 Cleaves (4 * 20 = 80)
        energy.current = 100

        # Hit 1: 50 -> 35
        self.turn_system.execute_cleave(self.player)
        self.assertTrue(esper.entity_exists(dummy_ent))

        # Hit 2: 35 -> 20
        self.turn_system.execute_cleave(self.player)
        self.assertTrue(esper.entity_exists(dummy_ent))

        # Hit 3: 20 -> 5
        self.turn_system.execute_cleave(self.player)
        self.assertTrue(esper.entity_exists(dummy_ent))

        # Hit 4: 5 -> 0 (Defeated!)
        self.combat_log.clear()
        self.turn_system.execute_cleave(self.player)

        # Dummy is deleted from the ECS world!
        self.assertFalse(esper.entity_exists(dummy_ent), "Defeated dummy should be deleted from ECS")

        # Verify combat log recorded defeat
        messages = self.combat_log.get_latest(1)
        self.assertIn("(Defeated!)", messages[0])

        # Fifth Cleave hits nothing because dummy was deleted
        self.combat_log.clear()
        energy.current = 100
        self.turn_system.execute_cleave(self.player)
        latest = self.combat_log.get_latest(1)
        self.assertIn("hit nothing", latest[0])

    def test_energy_regen_limited_only_to_when_energy_is_not_consumed(self) -> None:
        """Energy regenerates ONLY on ticks where energy was NOT consumed."""
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 100

        # 1. Action that consumes energy: Cleave costs 20
        self.turn_system.execute_cleave(self.player)
        # 100 - 20 = 80 (NO regeneration on this tick)
        self.assertEqual(energy.current, 80)

        # 2. Action that DOES NOT consume energy: Pass turn ('.')
        self.turn_system.pass_turn(self.player)
        # 80 + 10 = 90 (Regeneration occurred!)
        self.assertEqual(energy.current, 90)

        # 3. Direct tick without consumption
        self.turn_system.tick()
        # 90 + 10 = 100 (Regeneration occurred!)
        self.assertEqual(energy.current, 100)


if __name__ == "__main__":
    unittest.main()
