"""Regional Movement System for Mount & Blade style overworld exploration.

Handles 1-tile discrete movement on the Regional Map grid, advancing the WorldClock
by 4 hours per step and deducting 1 Food and 1 Water from the player's SurvivalStats.
"""

import esper

from components import Player, RegionalPosition, SurvivalStats
from game_state import GameState, GameStateManager
from regional_map_generator import RegionalMap
from world_clock import WorldClock, global_world_clock


class RegionalMovementSystem(esper.Processor):
    """Processes discrete movement and survival resource drain on the Regional Map."""

    def __init__(
        self,
        regional_map: RegionalMap | None = None,
        state_manager: GameStateManager | None = None,
        world_clock: WorldClock | None = None,
        combat_log=None,
    ) -> None:
        super().__init__()
        self.regional_map = regional_map
        self.state_manager = state_manager
        self.world_clock = world_clock if world_clock is not None else global_world_clock
        self.combat_log = combat_log

    def move_player(self, player_ent: int, dx: int, dy: int) -> bool:
        """Move the player exactly one regional tile, advance clock by 4h, and drain resources.

        Returns True if moved successfully, False if blocked by map boundary.
        """
        if self.regional_map is None:
            return False

        if not esper.has_component(player_ent, RegionalPosition):
            esper.add_component(
                player_ent,
                RegionalPosition(x=self.regional_map.width // 2, y=self.regional_map.height // 2),
            )

        reg_pos = esper.component_for_entity(player_ent, RegionalPosition)

        # Player cannot move on the regional map without ascending from the local tile
        if reg_pos.is_descended:
            if self.combat_log is not None:
                self.combat_log.add(
                    "[Overworld] You cannot travel on the regional map without ascending from the tile you are in! (Shift+Enter or walk to map edge)"
                )
            return False

        if self.state_manager is not None and self.state_manager.state != GameState.REGIONAL_MAP:
            return False

        new_x = reg_pos.x + dx
        new_y = reg_pos.y + dy

        # Clamp strictly within regional map bounds
        if not (0 <= new_x < self.regional_map.width and 0 <= new_y < self.regional_map.height):
            if self.combat_log is not None:
                self.combat_log.add("[Overworld] You have reached the edge of the known realm.")
            return False

        # Apply regional movement
        reg_pos.x = new_x
        reg_pos.y = new_y

        # Resource Drain: 4 hours of travel, 1 Food, 1 Water
        self.world_clock.advance_hours(4)

        survival: SurvivalStats | None = None
        if esper.has_component(player_ent, SurvivalStats):
            survival = esper.component_for_entity(player_ent, SurvivalStats)
            survival.consume(food_amount=1, water_amount=1)

        # Logging
        biome = self.regional_map.get_biome(new_x, new_y)
        biome_name = biome.value if hasattr(biome, "value") else str(biome)

        if self.combat_log is not None:
            time_str = self.world_clock.time_str
            food_info = f"{survival.food}/{survival.max_food}" if survival else "N/A"
            water_info = f"{survival.water}/{survival.max_water}" if survival else "N/A"
            self.combat_log.add(
                f"[Overworld] Step into {biome_name} ({new_x}, {new_y}). {time_str} | Food: {food_info}, Water: {water_info}"
            )
            if survival is not None:
                if survival.is_starving:
                    self.combat_log.add("[Warning] You are starving! Find sustenance soon.")
                if survival.is_dehydrated:
                    self.combat_log.add("[Warning] You are dehydrated! Find water soon.")

        return True

    def process(self, *args, **kwargs) -> None:
        """Standard esper process hook (optional intent processing)."""
        pass
