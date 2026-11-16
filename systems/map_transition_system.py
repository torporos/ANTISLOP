"""Map Transition System for descending to and ascending from local wilderness maps.

Implements Mount & Blade style overworld transitions:
- Descending to Local Map: On ENTER in REGIONAL_MAP, generates a 200x200 tactical map
  inheriting the exact Biome, Elevation, and Moisture of the regional tile currently occupied,
  and places the player at the center (100, 100).
- Ascending to Regional Map: On extreme edge reached (X=0, 199, Y=0, 199) or SHIFT+ENTER,
  garbage collects all local map entities (preserving the player and inventory/equipment)
  and returns to REGIONAL_MAP mode.
"""

import esper

from components import Equipment, Inventory, Player, Position, RegionalPosition, Viewshed
from game_map import GameMap
from game_state import GameState, GameStateManager
from local_map_generator import LocalMapGenerator
from regional_map_generator import RegionalMap, RegionalTile


class MapTransitionSystem:
    """Orchestrates seamless transitions between Regional Map and Local Wilderness Maps."""

    def __init__(
        self,
        state_manager: GameStateManager | None = None,
        regional_map: RegionalMap | None = None,
        game_map: GameMap | None = None,
        combat_log=None,
        door_system=None,
        input_system=None,
        movement_system=None,
        visibility_system=None,
        render_system=None,
    ) -> None:
        self.state_manager = state_manager
        self.regional_map = regional_map
        self.game_map = game_map
        self.combat_log = combat_log
        self.door_system = door_system
        self.input_system = input_system
        self.movement_system = movement_system
        self.visibility_system = visibility_system
        self.render_system = render_system

    def _get_player_ent(self) -> int | None:
        """Locate the active player entity in the ECS database."""
        for ent, _player in esper.get_components(Player):
            return ent
        return None

    def cleanup_local_map_entities(self, player_ent: int | None = None) -> int:
        """Garbage-collect all temporary local map entities, preserving the player and inventory items."""
        if player_ent is None:
            player_ent = self._get_player_ent()

        preserved_entities: set[int] = set()
        if player_ent is not None:
            preserved_entities.add(player_ent)
            if esper.has_component(player_ent, Inventory):
                inv = esper.component_for_entity(player_ent, Inventory)
                preserved_entities.update(inv.items)
            if esper.has_component(player_ent, Equipment):
                eq = esper.component_for_entity(player_ent, Equipment)
                if hasattr(eq, "slots"):
                    for item_ent in eq.slots.values():
                        if item_ent is not None:
                            preserved_entities.add(item_ent)
                elif hasattr(eq, "equipped"):
                    for item_ent in eq.equipped.values():
                        if item_ent is not None:
                            preserved_entities.add(item_ent)

        all_ents = list(esper._entities.keys())
        deleted_count = 0
        for ent in all_ents:
            if ent not in preserved_entities:
                esper.delete_entity(ent)
                deleted_count += 1

        return deleted_count

    def descend_to_local_map(self, player_ent: int | None = None) -> GameMap | None:
        """Descend from Regional Map into a newly generated 200x200 Local Map.

        Inherits Biome, Base Elevation, and Base Moisture from the RegionalTile
        the player is currently standing on.
        """
        if player_ent is None:
            player_ent = self._get_player_ent()
        if player_ent is None:
            return None

        # 1. Retrieve player's regional coordinates
        if not esper.has_component(player_ent, RegionalPosition):
            rx = self.regional_map.width // 2 if self.regional_map else 0
            ry = self.regional_map.height // 2 if self.regional_map else 0
            esper.add_component(player_ent, RegionalPosition(x=rx, y=ry))

        reg_pos = esper.component_for_entity(player_ent, RegionalPosition)
        reg_pos.is_descended = True

        # 2. Extract RegionalTile data
        if self.regional_map is not None:
            regional_tile = self.regional_map.get_regional_tile(reg_pos.x, reg_pos.y)
        else:
            regional_tile = RegionalTile()

        local_seed = regional_tile.seed
        if local_seed is None:
            if self.regional_map is not None:
                local_seed = self.regional_map.get_local_seed(reg_pos.x, reg_pos.y)
            else:
                local_seed = (int(reg_pos.x) * 19349663 ^ int(reg_pos.y) * 83492791) & 0x7FFFFFFF
            regional_tile.seed = local_seed

        # 3. Trigger LocalMapGenerator for this regional tile with persistent seed
        generator = LocalMapGenerator(
            width=200,
            height=200,
            regional_tile=regional_tile,
            seed=local_seed,
        )
        new_map = generator.generate(seed=local_seed, clear_starting_area=False, spawn_herbs_in_ecs=True)
        self.game_map = new_map

        # 4. Find center walkable tile for player spawn
        center_x = 100
        center_y = 100
        center_z = generator.base_z

        if not new_map.is_walkable(center_x, center_y, center_z):
            found = False
            for r in range(1, 15):
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        nx, ny = center_x + dx, center_y + dy
                        if new_map.in_bounds(nx, ny) and new_map.is_walkable(nx, ny, center_z):
                            center_x, center_y = nx, ny
                            found = True
                            break
                    if found:
                        break

        # 5. Position player at map center
        if esper.has_component(player_ent, Position):
            pos = esper.component_for_entity(player_ent, Position)
            pos.x = center_x
            pos.y = center_y
            pos.z = center_z
        else:
            esper.add_component(player_ent, Position(x=center_x, y=center_y, z=center_z))

        # Reset Viewshed for fresh FOV
        if esper.has_component(player_ent, Viewshed):
            vs = esper.component_for_entity(player_ent, Viewshed)
            vs.visible_tiles.clear()
            vs.inside_structure = False
            vs.active_building_id = None
            vs.current_room_id = None

        # 6. Update system references to newly active game map
        if self.door_system is not None:
            self.door_system.game_map = new_map
        if self.input_system is not None:
            self.input_system.game_map = new_map
        if self.movement_system is not None:
            self.movement_system.game_map = new_map
        if self.visibility_system is not None:
            self.visibility_system.game_map = new_map
        if self.render_system is not None:
            self.render_system.game_map = new_map

        # Update global reference in main module if loaded
        try:
            import main
            main.current_game_map = new_map
        except Exception:
            pass

        # 7. Switch state to LOCAL_MAP
        if self.state_manager is not None:
            self.state_manager.set_state(GameState.LOCAL_MAP)

        biome_name = regional_tile.dominant_biome
        if hasattr(biome_name, "value"):
            biome_name = biome_name.value

        if self.combat_log is not None:
            self.combat_log.add(
                f"[World] Descended into {biome_name} wilderness at ({reg_pos.x}, {reg_pos.y})."
            )

        return new_map

    def ascend_to_regional_map(self, player_ent: int | None = None) -> int:
        """Ascend from Local Map to Regional Map.

        Deletes all local map entities (garbage collection), preserving the player
        and inventory/equipment, and switches state to REGIONAL_MAP.
        """
        if player_ent is None:
            player_ent = self._get_player_ent()

        # 1. Garbage collect local map entities
        deleted_count = self.cleanup_local_map_entities(player_ent)

        # 2. Mark player as ascended (no longer descended in a local tile)
        if player_ent is not None and esper.has_component(player_ent, RegionalPosition):
            reg_pos = esper.component_for_entity(player_ent, RegionalPosition)
            reg_pos.is_descended = False

        # 3. Switch state to REGIONAL_MAP
        if self.state_manager is not None:
            self.state_manager.set_state(GameState.REGIONAL_MAP)

        if self.combat_log is not None:
            self.combat_log.add(
                f"[World] Ascended to Regional Map. ({deleted_count} wilderness entities cleared)"
            )

        return deleted_count
