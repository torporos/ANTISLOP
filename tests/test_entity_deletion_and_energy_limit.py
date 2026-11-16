"""Unit and integration tests for:
1. Entity deletion upon defeat (defeated enemies are removed from ECS and no longer rendered).
2. Limiting energy regeneration only to when energy is NOT consumed.
"""

import unittest
from bearlibterminal import terminal
import esper

from components import Energy, Fighter, Name, Player, Position, Renderable, Skill, SkillBar, Viewshed
from game_map import GameMap, Tile
from systems import CombatLog, DoorSystem, InputSystem, MovementSystem, RenderSystem, TurnManagementSystem, VisibilitySystem
import main


class TestEntityDeletionAndEnergyLimit(unittest.TestCase):
    """Test suite for entity deletion and conditional energy regeneration."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        self.turn_system = main.current_turn_system
        self.combat_log = main.current_combat_log
        self.render_system = esper.get_processor(RenderSystem)
        esper.process()

    def test_single_enemy_deleted_when_defeated(self) -> None:
        """When an enemy takes lethal damage, it is deleted from the ECS database."""
        # Find the initial training dummy
        dummy_ent = None
        for ent, (d_pos, d_fighter) in esper.get_components(Position, Fighter):
            if ent != self.player:
                dummy_ent = ent
                break
        self.assertIsNotNone(dummy_ent)
        self.assertTrue(esper.entity_exists(dummy_ent))

        # Set dummy HP low so 1 Cleave defeats it
        dummy_fighter = esper.component_for_entity(dummy_ent, Fighter)
        dummy_fighter.hp = 10

        self.combat_log.clear()
        self.turn_system.execute_cleave(self.player)

        # Confirm dummy is completely deleted
        self.assertFalse(esper.entity_exists(dummy_ent), "Dummy should be deleted from ECS upon defeat")
        self.assertEqual(len(list(esper.get_components(Position, Fighter))), 1, "Only player should remain")

        # Verify combat log has Defeated status
        messages = self.combat_log.get_latest(1)
        self.assertIn("(Defeated!)", messages[0])

    def test_multiple_enemies_deleted_in_single_cleave(self) -> None:
        """Cleave striking multiple low-HP enemies deletes all defeated entities."""
        pos = esper.component_for_entity(self.player, Position)

        # Spawn two extra enemies adjacent to player
        e1 = esper.create_entity()
        esper.add_component(e1, Position(x=pos.x - 1, y=pos.y, z=pos.z))
        esper.add_component(e1, Fighter(hp=5, max_hp=30))
        esper.add_component(e1, Name("Goblin 1"))

        e2 = esper.create_entity()
        esper.add_component(e2, Position(x=pos.x, y=pos.y - 1, z=pos.z))
        esper.add_component(e2, Fighter(hp=10, max_hp=30))
        esper.add_component(e2, Name("Goblin 2"))

        # Also give initial dummy 5 HP
        for ent, (_d_pos, d_fighter) in esper.get_components(Position, Fighter):
            if ent != self.player:
                d_fighter.hp = 5

        # Execute Cleave
        self.turn_system.execute_cleave(self.player)

        # All 3 adjacent enemies should be deleted!
        self.assertFalse(esper.entity_exists(e1))
        self.assertFalse(esper.entity_exists(e2))
        for ent, _f in esper.get_component(Fighter):
            self.assertEqual(ent, self.player, "Only player should remain in Fighter components")

    def test_player_never_deleted_by_defeat_cleanup(self) -> None:
        """Player entity is never deleted by delete_defeated_entity even if hp <= 0."""
        p_fighter = esper.component_for_entity(self.player, Fighter)
        p_fighter.hp = 0

        deleted = self.turn_system.delete_defeated_entity(self.player)
        self.assertFalse(deleted)
        self.assertTrue(esper.entity_exists(self.player))

        # Sweep cleanup also preserves player
        self.turn_system.cleanup_defeated_entities()
        self.assertTrue(esper.entity_exists(self.player))

    def test_deleted_enemy_not_rendered(self) -> None:
        """Deleted enemy has its Renderable removed so it cannot be rendered."""
        dummy_ent = None
        for ent, (d_pos, _d_fighter) in esper.get_components(Position, Fighter):
            if ent != self.player:
                dummy_ent = ent
                break

        # Set dummy HP to 5 and cleave
        esper.component_for_entity(dummy_ent, Fighter).hp = 5
        self.turn_system.execute_cleave(self.player)

        # Entity should not exist in Renderable components
        renderables = dict(esper.get_components(Position, Renderable))
        self.assertNotIn(dummy_ent, renderables)

    def test_energy_regen_inhibited_on_cleave_consumption(self) -> None:
        """Using Cleave consumes 20 energy and prevents regeneration on that turn."""
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 100

        self.turn_system.execute_cleave(self.player)
        # 100 - 20 = 80; no regen on this tick
        self.assertEqual(energy.current, 80)

        # Using Cleave again consumes 20 energy again
        self.turn_system.execute_cleave(self.player)
        # 80 - 20 = 60; no regen on this tick
        self.assertEqual(energy.current, 60)

    def test_energy_regen_occurs_when_no_energy_consumed(self) -> None:
        """Waiting / passing turn does not consume energy and triggers regeneration."""
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 60

        # Pass turn with '.'
        self.turn_system.pass_turn(self.player)
        self.assertEqual(energy.current, 70)

        # Move on normal floor (costs 0 energy) at (100, 101) -> (101, 101)
        pos = esper.component_for_entity(self.player, Position)
        pos.x = 100
        pos.y = 101
        # Normal floor to the right
        self.game_map.set_tile(101, 101, 0, Tile.floor())
        esper.process(key=terminal.TK_RIGHT)
        self.assertEqual(energy.current, 80)

    def test_energy_regen_inhibited_on_hard_terrain_consumption(self) -> None:
        """Moving onto hard terrain consumes energy and prevents regeneration on that turn."""
        energy = esper.component_for_entity(self.player, Energy)
        pos = esper.component_for_entity(self.player, Position)

        pos.x = 100
        pos.y = 101
        energy.current = 80

        # Place hard terrain at (101, 101, 0) costing 20
        self.game_map.set_tile(101, 101, 0, Tile.hard_floor(movement_cost=20))

        # Move right onto hard terrain
        esper.process(key=terminal.TK_RIGHT)

        # Moved successfully
        self.assertEqual((pos.x, pos.y, pos.z), (101, 101, 0))
        # 80 - 20 = 60. NO regeneration occurred because energy was consumed!
        self.assertEqual(energy.current, 60)

        # Next turn, pass turn: energy regenerates +10 -> 70
        esper.process(key=ord("."))
        self.assertEqual(energy.current, 70)

    def test_other_entities_regenerate_when_they_did_not_consume_energy(self) -> None:
        """An entity that did not consume energy still regenerates even if player consumed energy."""
        dummy_ent = None
        for ent, (d_pos, _d_fighter) in esper.get_components(Position, Fighter):
            if ent != self.player:
                dummy_ent = ent
                break
        self.assertIsNotNone(dummy_ent)

        dummy_energy = esper.component_for_entity(dummy_ent, Energy)
        dummy_energy.current = 0

        player_energy = esper.component_for_entity(self.player, Energy)
        player_energy.current = 100

        # Player uses Cleave (consumes 20 energy)
        self.turn_system.execute_cleave(self.player)

        # Player consumed energy -> did NOT regenerate (100 - 20 = 80)
        self.assertEqual(player_energy.current, 80)

        # Dummy did NOT consume energy -> DID regenerate (0 + 10 = 10)
        self.assertEqual(dummy_energy.current, 10)


if __name__ == "__main__":
    unittest.main()
