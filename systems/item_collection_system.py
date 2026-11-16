"""Item Collection System for picking up items from the ground into entity inventories.

Processes item pickup actions ('G' key) for actors standing on ground items,
removing their spatial presence from the map and placing them into inventory containers.
"""

import esper

from components import Inventory, Item, Name, Position
from message_log import MessageLog


class ItemCollectionSystem(esper.Processor):
    """Handles item pickup actions from map tiles into entity inventories."""

    def __init__(self, message_log: MessageLog | None = None) -> None:
        super().__init__()
        self.message_log = message_log

    def get_items_at(self, x: int, y: int, z: int) -> list[int]:
        """Return list of item entities located at specific (x, y, z) coordinates."""
        items: list[int] = []
        for ent, (pos, _item) in esper.get_components(Position, Item):
            if pos.x == x and pos.y == y and pos.z == z:
                items.append(ent)
        return items

    def collect_item(self, collector_ent: int) -> bool:
        """Attempt to collect a ground item at collector_ent's position into collector's inventory.

        Returns True if an item was successfully picked up, False otherwise.
        """
        if not esper.has_component(collector_ent, Position):
            return False
        if not esper.has_component(collector_ent, Inventory):
            return False

        pos = esper.component_for_entity(collector_ent, Position)
        inv = esper.component_for_entity(collector_ent, Inventory)

        # Locate items sharing this exact tile
        ground_items = self.get_items_at(pos.x, pos.y, pos.z)
        if not ground_items:
            self._log("There is nothing here to pick up.")
            return False

        # Pick up the top item on this tile
        item_ent = ground_items[0]
        item_comp = esper.component_for_entity(item_ent, Item)
        item_name = item_comp.name

        # Check inventory capacity
        if inv.is_full():
            self._log(f"Inventory is full! Cannot pick up {item_name}.")
            return False

        # Remove item's Position component to remove it from the map viewport
        esper.remove_component(item_ent, Position)

        # Add item entity to collector's inventory
        inv.add_item(item_ent)

        self._log(f"Picked up {item_name}.")
        return True

    def _log(self, text: str) -> None:
        """Log a message to the active message/combat log."""
        if self.message_log is not None:
            self.message_log.add(text)

    def process(self, *args, **kwargs) -> None:
        """Processor execution hook."""
        pass
