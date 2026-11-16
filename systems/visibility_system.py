"""Visibility System for computing Field of View (FOV) and handling interior occlusion.

Uses python-tcod purely for fast C-optimized FOV math algorithms while maintaining
full decoupling from rendering.
"""

import esper
import numpy as np
import tcod

from components import Player, Position, StructureFootprint, Viewshed
from game_map import GameMap
from game_state import GameState, GameStateManager


class VisibilitySystem(esper.Processor):
    """Calculates FOV and LOS using tcod. Handles room ID tagging and interior occlusion."""

    def __init__(
        self,
        game_map: GameMap,
        state_manager: GameStateManager | None = None,
    ) -> None:
        super().__init__()
        self.game_map = game_map
        self.state_manager = state_manager

    def process(self, *args, **kwargs) -> None:
        """Compute FOV for all entities with Position and Viewshed components."""
        # Only compute local FOV when active in LOCAL_MAP state
        if self.state_manager is not None and self.state_manager.state != GameState.LOCAL_MAP:
            return

        for ent, (pos, viewshed) in esper.get_components(Position, Viewshed):
            # 1. Compute FOV map using tcod's restrictive algorithm
            # Closed doors have transparent=False (blocking FOV), open doors have transparent=True
            transparency = self.game_map.get_transparency_array(pos.z)
            fov_map = tcod.map.compute_fov(
                transparency,
                (pos.x, pos.y),
                radius=viewshed.radius,
                light_walls=True,
                algorithm=tcod.constants.FOV_RESTRICTIVE,
            )

            # Extract visible tile coordinates into a set
            xs, ys = np.where(fov_map)
            raw_visible = set(zip(xs, ys))
            visible_tiles = set(raw_visible)

            # Room reveal mechanic: "If you can see into a room, you see the entire room."
            # A room is seen into if the player is inside it or can see a transparent tile inside it.
            footprint_room_ids: set[int] = set()
            for footprint in self.game_map.structures:
                if footprint.z != pos.z:
                    continue
                if footprint.room_id is not None:
                    footprint_room_ids.add(footprint.room_id)

                # Check if entity is inside footprint or sees into footprint
                is_seen_into = footprint.contains(pos.x, pos.y, pos.z)
                if not is_seen_into:
                    for vx, vy in raw_visible:
                        if footprint.contains(vx, vy, pos.z) and self.game_map.is_transparent(vx, vy, pos.z):
                            is_seen_into = True
                            break

                if is_seen_into:
                    for rx in range(footprint.x, footprint.x + footprint.width):
                        for ry in range(footprint.y, footprint.y + footprint.height):
                            if self.game_map.in_bounds(rx, ry):
                                visible_tiles.add((rx, ry))

            # Handle ad-hoc rooms tagged with room_id not defined by a StructureFootprint
            seen_adhoc_room_ids: set[int] = set()
            curr_tile = self.game_map.get_tile(pos.x, pos.y, pos.z)
            if curr_tile and curr_tile.room_id is not None and curr_tile.room_id not in footprint_room_ids:
                seen_adhoc_room_ids.add(curr_tile.room_id)

            for vx, vy in raw_visible:
                vtile = self.game_map.get_tile(vx, vy, pos.z)
                if (
                    vtile
                    and vtile.room_id is not None
                    and vtile.room_id not in footprint_room_ids
                    and (vtile.transparent or (vx, vy) == (pos.x, pos.y))
                ):
                    seen_adhoc_room_ids.add(vtile.room_id)

            if seen_adhoc_room_ids and pos.z in self.game_map.tiles:
                level = self.game_map.tiles[pos.z]
                for rx in range(self.game_map.width):
                    for ry in range(self.game_map.height):
                        if level[rx][ry].room_id in seen_adhoc_room_ids:
                            visible_tiles.add((rx, ry))

            viewshed.visible_tiles = visible_tiles

            # Mark all tiles in FOV (including fully revealed rooms) as explored and discover buildings
            if esper.has_component(ent, Player) or not any(esper.get_component(Player)):
                self.game_map.mark_explored_batch(pos.z, fov_map)
                for vx, vy in visible_tiles:
                    self.game_map.set_explored(vx, vy, pos.z, True)
                for vx, vy in raw_visible:
                    bldg_id = self.game_map.get_building_id_at(vx, vy, pos.z)
                    if bldg_id:
                        self.game_map.discover_building(bldg_id)

            # 2. Check room ID at entity's current tile
            curr_tile = self.game_map.get_tile(pos.x, pos.y, pos.z)
            viewshed.current_room_id = curr_tile.room_id if curr_tile else None

            # 3. Check if entity's position is inside any structure footprint
            matching_structure = None
            for _s_ent, footprint in esper.get_component(StructureFootprint):
                if footprint.contains(pos.x, pos.y, pos.z):
                    matching_structure = footprint
                    break

            if matching_structure is None and self.game_map:
                matching_structure = self.game_map.get_structure_at(pos.x, pos.y, pos.z)

            viewshed.inside_structure = (
                viewshed.current_room_id is not None or matching_structure is not None
            )
            viewshed.active_structure = matching_structure
            viewshed.active_building_id = (
                matching_structure.building_id
                if matching_structure and matching_structure.building_id
                else self.game_map.get_building_id_at(pos.x, pos.y, pos.z)
            )
