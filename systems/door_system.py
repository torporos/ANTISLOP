"""Door System for managing interactable doors and synchronizing with the GameMap."""

import esper

from components import Door, Position, Renderable
from game_map import GameMap


class DoorSystem(esper.Processor):
    """Handles door interactions (open/close) and synchronizes door state with the map."""

    def __init__(self, game_map: GameMap) -> None:
        super().__init__()
        self.game_map = game_map

    def process(self, *args, **kwargs) -> None:
        """Process door updates or synchronize doors with map if needed."""
        pass

    def get_door_at(self, x: int, y: int, z: int) -> int | None:
        """Find the entity ID of a door at (x, y, z), if any."""
        for ent, (pos, _door) in esper.get_components(Position, Door):
            if (pos.x, pos.y, pos.z) == (x, y, z):
                return ent
        return None

    def toggle_door(self, door_ent: int) -> bool:
        """Toggle a door entity between open and closed, updating map transparency and walkability."""
        door = esper.component_for_entity(door_ent, Door)
        pos = esper.component_for_entity(door_ent, Position)
        rend = esper.component_for_entity(door_ent, Renderable)

        door.is_open = not door.is_open

        if door.is_open:
            rend.char = door.open_char
            rend.color = door.open_color
            tile = self.game_map.get_tile(pos.x, pos.y, pos.z)
            if tile is not None:
                tile.transparent = True
                tile.walkable = True
                tile.char = door.open_char
                tile.color = door.open_color
        else:
            rend.char = door.closed_char
            rend.color = door.closed_color
            tile = self.game_map.get_tile(pos.x, pos.y, pos.z)
            if tile is not None:
                tile.transparent = False
                tile.walkable = False
                tile.char = door.closed_char
                tile.color = door.closed_color

        self.game_map.invalidate_transparency_cache(pos.z)
        return door.is_open

    def open_door(self, door_ent: int) -> None:
        """Open a door entity if currently closed."""
        door = esper.component_for_entity(door_ent, Door)
        if not door.is_open:
            self.toggle_door(door_ent)

    def close_door(self, door_ent: int) -> None:
        """Close a door entity if currently open."""
        door = esper.component_for_entity(door_ent, Door)
        if door.is_open:
            self.toggle_door(door_ent)

    def interact_adjacent(self, player_x: int, player_y: int, player_z: int) -> bool:
        """Find an adjacent door and toggle its open/closed state.

        Prevents closing a door while the player is standing directly inside the doorway.
        Returns True if a door was toggled.
        """
        for door_ent, (d_pos, door) in esper.get_components(Position, Door):
            if d_pos.z == player_z:
                dx = abs(d_pos.x - player_x)
                dy = abs(d_pos.y - player_y)
                if dx <= 1 and dy <= 1:
                    # Prevent closing a door if the player is standing on the door tile
                    if dx == 0 and dy == 0 and door.is_open:
                        continue
                    self.toggle_door(door_ent)
                    return True
        return False
