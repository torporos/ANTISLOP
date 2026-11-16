"""Equipment System for managing item equipping, unequipping, and 3-tier stat derivation.

Coordinates Equipment slots, Inventory contents, and recalculates Stats component
so Battle Stats update dynamically based on D&D Substats and equipment bonuses.
"""

import esper

from components import Equipment, EquipmentSlot, Equippable, Fighter, Inventory, Item, Name, Stats
from message_log import MessageLog


class EquipmentSystem(esper.Processor):
    """Manages equipping and unequipping items and synchronizing derived Stats."""

    def __init__(self, message_log: MessageLog | None = None) -> None:
        super().__init__()
        self.message_log = message_log

    def equip_item(self, entity: int, item_entity: int) -> bool:
        """Equip item_entity on entity into its designated EquipmentSlot.

        Returns True on success, False if entity or item lacks required components.
        """
        if not esper.has_component(entity, Equipment):
            return False
        if not esper.has_component(entity, Stats):
            return False

        # Determine target slot and stat bonuses
        slot: EquipmentSlot | None = None
        item_name: str = f"Item #{item_entity}"

        if esper.has_component(item_entity, Equippable):
            equippable = esper.component_for_entity(item_entity, Equippable)
            slot = equippable.slot
        elif esper.has_component(item_entity, Item):
            item_comp = esper.component_for_entity(item_entity, Item)
            slot = item_comp.slot

        if slot is None:
            self._log(f"{item_name} cannot be equipped.")
            return False

        if esper.has_component(item_entity, Item):
            item_name = esper.component_for_entity(item_entity, Item).name
        elif esper.has_component(item_entity, Name):
            item_name = esper.component_for_entity(item_entity, Name).name

        equipment = esper.component_for_entity(entity, Equipment)
        old_item = equipment.equip(slot, item_entity)

        # Update inventory if present
        if esper.has_component(entity, Inventory):
            inv = esper.component_for_entity(entity, Inventory)
            inv.remove_item(item_entity)
            if old_item is not None:
                inv.add_item(old_item)

        # Recalculate stats dynamically
        self.update_stats(entity)

        self._log(f"Equipped {item_name} to {slot.value}.")
        return True

    def unequip_item(self, entity: int, slot: EquipmentSlot) -> int | None:
        """Unequip item from designated slot on entity. Returns the unequipped item entity."""
        if not esper.has_component(entity, Equipment):
            return None

        equipment = esper.component_for_entity(entity, Equipment)
        item_entity = equipment.unequip(slot)
        if item_entity is None:
            return None

        item_name = f"Item #{item_entity}"
        if esper.has_component(item_entity, Item):
            item_name = esper.component_for_entity(item_entity, Item).name
        elif esper.has_component(item_entity, Name):
            item_name = esper.component_for_entity(item_entity, Name).name

        # Return unequipped item to inventory if present
        if esper.has_component(entity, Inventory):
            inv = esper.component_for_entity(entity, Inventory)
            inv.add_item(item_entity)

        # Recalculate stats dynamically
        self.update_stats(entity)

        self._log(f"Unequipped {item_name} from {slot.value}.")
        return item_entity

    def update_stats(self, entity: int) -> None:
        """Recalculate entity's Stats from equipment bonuses and D&D Substats."""
        if not esper.has_component(entity, Stats) or not esper.has_component(entity, Equipment):
            return

        stats = esper.component_for_entity(entity, Stats)
        equipment = esper.component_for_entity(entity, Equipment)

        # Reset bonus modifiers
        stats.bonus_strength = 0
        stats.bonus_dexterity = 0
        stats.bonus_constitution = 0
        stats.bonus_intelligence = 0
        stats.bonus_wisdom = 0
        stats.bonus_charisma = 0
        stats.bonus_max_hp = 0
        stats.bonus_speed = 0
        stats.bonus_damage = 0
        stats.bonus_defense = 0
        stats.bonus_crit_rate = 0.0
        stats.bonus_crit_damage = 0.0
        stats.bonus_evasion = 0.0

        for slot, item_ent in equipment.slots.items():
            if item_ent is None:
                continue

            # Fetch stat bonuses from Equippable or Item
            bonuses: dict[str, int | float] = {}
            if esper.has_component(item_ent, Equippable):
                bonuses = esper.component_for_entity(item_ent, Equippable).stat_bonuses
            elif esper.has_component(item_ent, Item):
                bonuses = esper.component_for_entity(item_ent, Item).stat_bonuses

            for stat_key, val in bonuses.items():
                key = str(stat_key).lower().strip()
                if key in ("str", "strength"):
                    stats.bonus_strength += int(val)
                elif key in ("dex", "dexterity"):
                    stats.bonus_dexterity += int(val)
                elif key in ("con", "constitution"):
                    stats.bonus_constitution += int(val)
                elif key in ("int", "intelligence"):
                    stats.bonus_intelligence += int(val)
                elif key in ("wis", "wisdom"):
                    stats.bonus_wisdom += int(val)
                elif key in ("cha", "charisma"):
                    stats.bonus_charisma += int(val)
                elif key in ("hp", "max_hp"):
                    stats.bonus_max_hp += int(val)
                elif key in ("speed", "spd"):
                    stats.bonus_speed += int(val)
                elif key in ("damage", "dmg"):
                    stats.bonus_damage += int(val)
                elif key in ("defense", "def"):
                    stats.bonus_defense += int(val)
                elif key in ("crit", "crit_rate"):
                    stats.bonus_crit_rate += float(val)
                elif key in ("crit_dmg", "crit_damage"):
                    stats.bonus_crit_damage += float(val)
                elif key in ("evasion", "eva"):
                    stats.bonus_evasion += float(val)

        # Strictly derive Battle Stats from total Substats
        stats.recalculate()

        # Synchronize with Fighter component if attached
        if esper.has_component(entity, Fighter):
            fighter = esper.component_for_entity(entity, Fighter)
            hp_diff = stats.max_hp - fighter.max_hp
            fighter.max_hp = stats.max_hp
            if hp_diff > 0:
                fighter.hp += hp_diff
            fighter.hp = min(fighter.hp, fighter.max_hp)

    def _log(self, text: str) -> None:
        """Helper to append message to message log."""
        if self.message_log is not None:
            self.message_log.add(text)

    def process(self, *args, **kwargs) -> None:
        """Processor hook."""
        pass
