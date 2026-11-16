"""Unit and integration tests for Phase 12: Advanced Equipment UI & 3-Tier Stat System.

Tests:
1. Stats Component & Strict Derivation Logic:
   - Base Stats (Level, XP, Max XP)
   - D&D Substats (STR, DEX, CON, INT, WIS, CHA)
   - Battle Stats strict derivations:
     * 1 CON = +5 Max HP
     * 1 STR = +1 Damage
     * 1 DEX = +1 Speed and +0.5% Evasion
     * 1 INT = +0.5% Crit Rate
     * 1 WIS = +1 Defense

2. Equipment Component (11 Slots):
   - 6 Armor Slots: Head, Cape, Torso, Gloves, Legs, Boots
   - 5 Trinket Slots: Hair Ornament, Necklace, Belt, Wristband, Ring

3. EquipmentSystem:
   - Equipping and unequipping items into correct slots
   - Dynamic recalculation of Substats and Battle Stats
   - Synchronization with Fighter component max_hp

4. Ground Items Spawning:
   - 'Bronze Ring' (Trinket, +2 STR)
   - 'Leather Tunic' (Torso, +2 CON)
   - Player pickup, inventory integration, and equip updates

5. Character Screen (Key 'C'):
   - GameState.CHARACTER toggle and pausing local map
   - ESC and 'C' closure
   - Rendering of 16x16 ASCII portrait, paper doll slots, and 3-tier stats grid
"""

import unittest
from bearlibterminal import terminal
import esper

from components import (
    Equipment,
    EquipmentSlot,
    Equippable,
    Fighter,
    Inventory,
    Item,
    Player,
    Position,
    RenderOrder,
    Renderable,
    Stats,
)
from game_map import GameMap
from game_state import GameState, GameStateManager
from message_log import MessageLog
from systems import (
    EquipmentSystem,
    InputSystem,
    ItemCollectionSystem,
    RenderSystem,
)
import main


class TestThreeTierStatsDerivation(unittest.TestCase):
    """Test suite for Stats component and strict derivation logic."""

    def test_default_base_and_substats(self) -> None:
        """Verify default starting stats: Level 1, 0/100 XP, all substats 10."""
        stats = Stats()
        self.assertEqual(stats.level, 1)
        self.assertEqual(stats.xp, 0)
        self.assertEqual(stats.max_xp, 100)

        self.assertEqual(stats.strength, 10)
        self.assertEqual(stats.dexterity, 10)
        self.assertEqual(stats.constitution, 10)
        self.assertEqual(stats.intelligence, 10)
        self.assertEqual(stats.wisdom, 10)
        self.assertEqual(stats.charisma, 10)

    def test_strict_battle_stat_derivations(self) -> None:
        """Verify strict derivation rules on baseline substats of 10:
        1 CON = +5 Max HP (50)
        1 STR = +1 Damage (10)
        1 DEX = +1 Speed (10) and +0.5% Evasion (5.0%)
        1 INT = +0.5% Crit Rate (5.0%)
        1 WIS = +1 Defense (10)
        """
        stats = Stats()
        self.assertEqual(stats.max_hp, 50)
        self.assertEqual(stats.damage, 10)
        self.assertEqual(stats.speed, 10)
        self.assertEqual(stats.evasion, 5.0)
        self.assertEqual(stats.crit_rate, 5.0)
        self.assertEqual(stats.defense, 10)

    def test_substat_bonuses_dynamically_update_battle_stats(self) -> None:
        """Verify adding bonuses dynamically recalculates battle stats according to rules."""
        stats = Stats()

        # Add +2 STR (Damage should increase from 10 to 12)
        stats.bonus_strength = 2
        stats.recalculate()
        self.assertEqual(stats.total_strength(), 12)
        self.assertEqual(stats.damage, 12)

        # Add +2 CON (Max HP should increase from 50 to 60)
        stats.bonus_constitution = 2
        stats.recalculate()
        self.assertEqual(stats.total_constitution(), 12)
        self.assertEqual(stats.max_hp, 60)

        # Add +4 DEX (Speed should increase by 4, Evasion by 2.0%)
        stats.bonus_dexterity = 4
        stats.recalculate()
        self.assertEqual(stats.total_dexterity(), 14)
        self.assertEqual(stats.speed, 14)
        self.assertEqual(stats.evasion, 7.0)

        # Add +6 INT (Crit Rate should increase by 3.0%)
        stats.bonus_intelligence = 6
        stats.recalculate()
        self.assertEqual(stats.total_intelligence(), 16)
        self.assertEqual(stats.crit_rate, 8.0)

        # Add +5 WIS (Defense should increase by 5)
        stats.bonus_wisdom = 5
        stats.recalculate()
        self.assertEqual(stats.total_wisdom(), 15)
        self.assertEqual(stats.defense, 15)


class TestElevenSlotEquipmentComponent(unittest.TestCase):
    """Test suite for Equipment component and 11 distinct slots."""

    def test_equipment_slot_enum_has_exactly_eleven_slots(self) -> None:
        """Verify EquipmentSlot enum has exactly 6 armor slots and 5 trinket slots."""
        armor_slots = [
            EquipmentSlot.HEAD,
            EquipmentSlot.CAPE,
            EquipmentSlot.TORSO,
            EquipmentSlot.GLOVES,
            EquipmentSlot.LEGS,
            EquipmentSlot.BOOTS,
        ]
        trinket_slots = [
            EquipmentSlot.HAIR_ORNAMENT,
            EquipmentSlot.NECKLACE,
            EquipmentSlot.BELT,
            EquipmentSlot.WRISTBAND,
            EquipmentSlot.RING,
        ]
        self.assertEqual(len(armor_slots), 6)
        self.assertEqual(len(trinket_slots), 5)
        self.assertEqual(len(EquipmentSlot), 11)

    def test_equipment_component_initial_slots_empty(self) -> None:
        """Verify Equipment component initializes with all 11 slots set to None."""
        eq = Equipment()
        self.assertEqual(len(eq.slots), 11)
        for slot in EquipmentSlot:
            self.assertIsNone(eq.get_equipped(slot))

    def test_equipment_equip_and_unequip(self) -> None:
        """Verify equipping and unequipping item entities directly in Equipment."""
        eq = Equipment()
        item_id = 42

        # Equip
        old = eq.equip(EquipmentSlot.RING, item_id)
        self.assertIsNone(old)
        self.assertEqual(eq.get_equipped(EquipmentSlot.RING), item_id)
        self.assertTrue(eq.is_equipped(item_id))
        self.assertEqual(eq.get_slot_of(item_id), EquipmentSlot.RING)

        # Unequip
        unequipped = eq.unequip(EquipmentSlot.RING)
        self.assertEqual(unequipped, item_id)
        self.assertIsNone(eq.get_equipped(EquipmentSlot.RING))
        self.assertFalse(eq.is_equipped(item_id))


class TestEquipmentSystem(unittest.TestCase):
    """Test suite for EquipmentSystem equipping and stat updates."""

    def setUp(self) -> None:
        esper.clear_database()
        self.log = MessageLog()
        self.eq_system = EquipmentSystem(message_log=self.log)

        # Create actor with Equipment, Stats, Inventory, Fighter
        self.actor = esper.create_entity()
        esper.add_component(self.actor, Equipment())
        self.stats = Stats()
        esper.add_component(self.actor, self.stats)
        self.inv = Inventory(max_capacity=10)
        esper.add_component(self.actor, self.inv)
        self.fighter = Fighter(hp=50, max_hp=50)
        esper.add_component(self.actor, self.fighter)

    def test_equip_bronze_ring_increases_str_and_damage(self) -> None:
        """Equipping Bronze Ring (+2 STR) updates Damage from 10 to 12."""
        ring = esper.create_entity()
        esper.add_component(
            ring,
            Item(name="Bronze Ring", slot=EquipmentSlot.RING, stat_bonuses={"strength": 2}),
        )
        esper.add_component(
            ring,
            Equippable(slot=EquipmentSlot.RING, stat_bonuses={"strength": 2}),
        )
        self.inv.add_item(ring)

        # Equip
        success = self.eq_system.equip_item(self.actor, ring)
        self.assertTrue(success)

        # Ring removed from inventory and equipped in slot
        self.assertNotIn(ring, self.inv.items)
        eq = esper.component_for_entity(self.actor, Equipment)
        self.assertEqual(eq.get_equipped(EquipmentSlot.RING), ring)

        # Verify STR and Damage updated
        self.assertEqual(self.stats.bonus_strength, 2)
        self.assertEqual(self.stats.total_strength(), 12)
        self.assertEqual(self.stats.damage, 12)

    def test_equip_leather_tunic_increases_con_and_max_hp(self) -> None:
        """Equipping Leather Tunic (+2 CON) updates Max HP from 50 to 60."""
        tunic = esper.create_entity()
        esper.add_component(
            tunic,
            Item(name="Leather Tunic", slot=EquipmentSlot.TORSO, stat_bonuses={"constitution": 2}),
        )
        esper.add_component(
            tunic,
            Equippable(slot=EquipmentSlot.TORSO, stat_bonuses={"constitution": 2}),
        )
        self.inv.add_item(tunic)

        # Equip
        success = self.eq_system.equip_item(self.actor, tunic)
        self.assertTrue(success)

        # Verify CON, Stats Max HP, and Fighter Max HP updated
        self.assertEqual(self.stats.bonus_constitution, 2)
        self.assertEqual(self.stats.total_constitution(), 12)
        self.assertEqual(self.stats.max_hp, 60)
        self.assertEqual(self.fighter.max_hp, 60)

    def test_unequip_item_restores_baseline_stats(self) -> None:
        """Unequipping an item returns it to inventory and recalculates baseline stats."""
        ring = esper.create_entity()
        esper.add_component(
            ring,
            Item(name="Bronze Ring", slot=EquipmentSlot.RING, stat_bonuses={"strength": 2}),
        )
        esper.add_component(ring, Equippable(slot=EquipmentSlot.RING, stat_bonuses={"strength": 2}))
        self.inv.add_item(ring)

        self.eq_system.equip_item(self.actor, ring)
        self.assertEqual(self.stats.damage, 12)

        # Unequip
        unequipped = self.eq_system.unequip_item(self.actor, EquipmentSlot.RING)
        self.assertEqual(unequipped, ring)
        self.assertIn(ring, self.inv.items)

        # Stats restored to baseline
        self.assertEqual(self.stats.total_strength(), 10)
        self.assertEqual(self.stats.damage, 10)


class TestMainInitAndGroundItems(unittest.TestCase):
    """Test suite verifying world setup with Bronze Ring and Leather Tunic ground spawns."""

    def setUp(self) -> None:
        esper.clear_database()
        self.player = main.init_ecs()
        esper.process()

    def test_player_spawned_with_stats_and_equipment(self) -> None:
        """Verify player has Stats and Equipment components initialized."""
        self.assertTrue(esper.has_component(self.player, Stats))
        self.assertTrue(esper.has_component(self.player, Equipment))

        stats = esper.component_for_entity(self.player, Stats)
        self.assertEqual(stats.level, 1)
        self.assertEqual(stats.strength, 10)
        self.assertEqual(stats.damage, 10)
        self.assertEqual(stats.max_hp, 50)

    def test_bronze_ring_and_leather_tunic_spawned_on_ground(self) -> None:
        """Verify 'Bronze Ring' (+2 STR) and 'Leather Tunic' (+2 CON) are spawned on the ground."""
        found_ring = False
        found_tunic = False

        for _ent, (pos, item, eq) in esper.get_components(Position, Item, Equippable):
            if item.name == "Bronze Ring":
                self.assertEqual(eq.slot, EquipmentSlot.RING)
                self.assertEqual(eq.stat_bonuses.get("strength"), 2)
                found_ring = True
            elif item.name == "Leather Tunic":
                self.assertEqual(eq.slot, EquipmentSlot.TORSO)
                self.assertEqual(eq.stat_bonuses.get("constitution"), 2)
                found_tunic = True

        self.assertTrue(found_ring, "Bronze Ring should be spawned on ground")
        self.assertTrue(found_tunic, "Leather Tunic should be spawned on ground")


class TestCharacterScreenStateAndInteraction(unittest.TestCase):
    """Test suite for Character Screen (Key 'C') state and equip interaction."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.state_manager = GameStateManager(initial_state=GameState.LOCAL_MAP)
        self.player = main.init_ecs(game_map=self.game_map, state_manager=self.state_manager)
        esper.process()

    def test_press_c_opens_and_closes_character_screen(self) -> None:
        """Pressing 'C' enters GameState.CHARACTER and pressing ESC returns to LOCAL_MAP."""
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

        # Press 'C'
        esper.process(key=terminal.TK_C)
        self.assertEqual(self.state_manager.state, GameState.CHARACTER)

        # Press ESC to close
        esper.process(key=terminal.TK_ESCAPE)
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

        # Press ord('c') to open
        esper.process(key=ord("c"))
        self.assertEqual(self.state_manager.state, GameState.CHARACTER)

        # Press ord('c') to close
        esper.process(key=ord("c"))
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

    def test_local_map_paused_in_character_screen(self) -> None:
        """Movement and turn actions are paused while Character Screen is open."""
        pos = esper.component_for_entity(self.player, Position)
        initial_coords = (pos.x, pos.y, pos.z)

        # Open Character Screen
        esper.process(key=terminal.TK_C)
        self.assertEqual(self.state_manager.state, GameState.CHARACTER)

        # Attempt to walk
        esper.process(key=terminal.TK_RIGHT)
        esper.process(key=terminal.TK_DOWN)
        self.assertEqual((pos.x, pos.y, pos.z), initial_coords)

    def test_pick_up_and_equip_updates_battle_stats(self) -> None:
        """Pick up Bronze Ring and Leather Tunic, equip them from inventory, and verify Battle Stats update."""
        inv = esper.component_for_entity(self.player, Inventory)
        stats = esper.component_for_entity(self.player, Stats)

        # Directly add Bronze Ring and Leather Tunic to player inventory
        ring = esper.create_entity()
        esper.add_component(ring, Item(name="Bronze Ring", slot=EquipmentSlot.RING, stat_bonuses={"strength": 2}))
        esper.add_component(ring, Equippable(slot=EquipmentSlot.RING, stat_bonuses={"strength": 2}))
        inv.add_item(ring)

        tunic = esper.create_entity()
        esper.add_component(tunic, Item(name="Leather Tunic", slot=EquipmentSlot.TORSO, stat_bonuses={"constitution": 2}))
        esper.add_component(tunic, Equippable(slot=EquipmentSlot.TORSO, stat_bonuses={"constitution": 2}))
        inv.add_item(tunic)

        # 1. Open Character Screen: verifying keybind conflict is resolved
        esper.process(key=terminal.TK_C)
        self.assertEqual(self.state_manager.state, GameState.CHARACTER)

        # In Character Screen, pressing item hotkeys like 'a' does NOT equip anything
        esper.process(key=ord("a"))
        self.assertEqual(stats.total_strength(), 10, "Equipping from Character Screen must be disabled")
        self.assertEqual(stats.damage, 10)

        # Pressing 'c' in Character Screen closes it without equipping item 'c'
        esper.process(key=ord("c"))
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

        # 2. Open Inventory Screen ('I') where gear is equipped
        esper.process(key=terminal.TK_I)
        self.assertEqual(self.state_manager.state, GameState.INVENTORY)

        # Equipping Bronze Ring from Inventory (item slot 0 -> key 'a')
        esper.process(key=ord("a"))
        self.assertEqual(stats.total_strength(), 12)
        self.assertEqual(stats.damage, 12)

        # Equipping Leather Tunic from Inventory (item slot 0 -> key 'a' now that ring was removed from inv)
        esper.process(key=ord("a"))
        self.assertEqual(stats.total_constitution(), 12)
        self.assertEqual(stats.max_hp, 60)

        # Close Inventory Screen
        esper.process(key=terminal.TK_I)
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

        # Open Character Screen ('C') to verify updated Battle Stats
        esper.process(key=terminal.TK_C)
        self.assertEqual(self.state_manager.state, GameState.CHARACTER)
        self.assertEqual(stats.damage, 12)
        self.assertEqual(stats.max_hp, 60)

        # Close with ESC
        esper.process(key=terminal.TK_ESCAPE)
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

    def test_equip_item_c_from_inventory(self) -> None:
        """Verify pressing 'c' in Inventory equips the 3rd item (index 2) without conflict."""
        inv = esper.component_for_entity(self.player, Inventory)
        stats = esper.component_for_entity(self.player, Stats)

        # Add 3 items to inventory: item 0 ('a'), item 1 ('b'), item 2 ('c')
        item_a = esper.create_entity()
        esper.add_component(item_a, Item(name="Dummy Item A"))
        inv.add_item(item_a)

        item_b = esper.create_entity()
        esper.add_component(item_b, Item(name="Dummy Item B"))
        inv.add_item(item_b)

        ring = esper.create_entity()
        esper.add_component(ring, Item(name="Bronze Ring", slot=EquipmentSlot.RING, stat_bonuses={"strength": 2}))
        esper.add_component(ring, Equippable(slot=EquipmentSlot.RING, stat_bonuses={"strength": 2}))
        inv.add_item(ring)  # index 2 -> letter 'c'

        # Open Inventory Screen
        esper.process(key=terminal.TK_I)
        self.assertEqual(self.state_manager.state, GameState.INVENTORY)

        # Press 'c' to equip item 'c' (the Bronze Ring)
        esper.process(key=ord("c"))
        self.assertEqual(stats.total_strength(), 12)
        self.assertEqual(stats.damage, 12)
        self.assertNotIn(ring, inv.items)

        # Close Inventory Screen
        esper.process(key=terminal.TK_ESCAPE)
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

    def test_slot_art_presets_and_empty_slots(self) -> None:
        """Verify slot art presets exist for all 11 slots and have exact 5x5 dimensions."""
        from systems.render_system import (
            EMPTY_SLOT_ART,
            SLOT_ART_PRESETS,
            RING_ART,
            TORSO_ART,
        )

        self.assertEqual(len(EMPTY_SLOT_ART), 5)
        for line in EMPTY_SLOT_ART:
            self.assertEqual(len(line), 5)
        self.assertEqual(EMPTY_SLOT_ART[0], "_____")
        self.assertEqual(EMPTY_SLOT_ART[1], "|   |")
        self.assertEqual(EMPTY_SLOT_ART[2], "|   |")
        self.assertEqual(EMPTY_SLOT_ART[3], "|   |")
        self.assertEqual(EMPTY_SLOT_ART[4], "¯¯¯¯¯")

        # Ring format
        self.assertEqual(len(RING_ART), 5)
        for line in RING_ART:
            self.assertEqual(len(line), 5)
        self.assertEqual(RING_ART[0], "_____")
        self.assertEqual(RING_ART[1], "| _ |")
        self.assertEqual(RING_ART[2], "|< >|")
        self.assertEqual(RING_ART[3], "| ¯ |")
        self.assertEqual(RING_ART[4], "¯¯¯¯¯")

        # Torso format
        self.assertEqual(len(TORSO_ART), 5)
        for line in TORSO_ART:
            self.assertEqual(len(line), 5)
        self.assertEqual(TORSO_ART[0], "_____")
        self.assertEqual(TORSO_ART[1], "| _ |")
        self.assertEqual(TORSO_ART[2], "|{ }|")
        self.assertEqual(TORSO_ART[3], "|[-]|")
        self.assertEqual(TORSO_ART[4], "¯¯¯¯¯")

        # All 11 slots in SLOT_ART_PRESETS
        self.assertEqual(len(SLOT_ART_PRESETS), 11)
        for slot in EquipmentSlot:
            self.assertIn(slot, SLOT_ART_PRESETS)
            art = SLOT_ART_PRESETS[slot]
            self.assertEqual(len(art), 5)
            for line in art:
                self.assertEqual(len(line), 5)

    def test_character_screen_rendering(self) -> None:
        """Verify RenderSystem renders Character Screen cleanly in BearLibTerminal."""
        terminal.open()
        try:
            terminal.set(f"window: size={main.SCREEN_WIDTH}x{main.SCREEN_HEIGHT}")

            # Open Character Screen
            esper.process(key=terminal.TK_C)
            self.assertEqual(self.state_manager.state, GameState.CHARACTER)

            # Process render pass
            esper.process()

            # Close Character Screen
            esper.process(key=terminal.TK_ESCAPE)
            self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)
            esper.process()
        finally:
            terminal.close()


if __name__ == "__main__":
    unittest.main()
