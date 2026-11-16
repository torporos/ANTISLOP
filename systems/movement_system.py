"""Movement System for updating entity positions based on movement intents and map collision."""

import esper

from components import (
    BlocksTile,
    Door,
    Energy,
    Fighter,
    Memory,
    Mindset,
    MovementIntent,
    Name,
    NPC,
    Personality,
    Player,
    Position,
)
from game_map import GameMap
from game_state import GameState, GameStateManager
from systems.door_system import DoorSystem
from systems.turn_management_system import TurnManagementSystem


class MovementSystem(esper.Processor):
    """Processes MovementIntent components and updates Position components respecting collisions."""

    def __init__(
        self,
        game_map: GameMap | None = None,
        bounds_width: int = 80,
        bounds_height: int = 50,
        state_manager: GameStateManager | None = None,
        door_system: DoorSystem | None = None,
        turn_system: TurnManagementSystem | None = None,
        interaction_system=None,
        transition_system=None,
    ) -> None:
        super().__init__()
        self.game_map = game_map
        self.bounds_width = bounds_width
        self.bounds_height = bounds_height
        self.state_manager = state_manager
        self.door_system = door_system
        self.turn_system = turn_system
        self.interaction_system = interaction_system
        self.transition_system = transition_system

    def get_blocking_entity_at(
        self, x: int, y: int, z: int, exclude_ent: int | None = None
    ) -> int | None:
        """Find an entity blocking movement at (x, y, z), excluding exclude_ent."""
        for other_ent, pos in esper.get_component(Position):
            if other_ent == exclude_ent:
                continue
            if (pos.x, pos.y, pos.z) != (x, y, z):
                continue

            # Explicit blocking component
            if esper.has_component(other_ent, BlocksTile):
                return other_ent

            # NPC entities block
            if esper.has_component(other_ent, NPC):
                return other_ent

            # Player entities block
            if esper.has_component(other_ent, Player):
                return other_ent

            # Living Fighter entities block
            if esper.has_component(other_ent, Fighter):
                fighter = esper.component_for_entity(other_ent, Fighter)
                if fighter.is_alive:
                    return other_ent

        return None

    def is_interactable_npc(self, ent: int) -> bool:
        """Check if an entity can be interacted with for dialogue."""
        return (
            esper.has_component(ent, NPC)
            or esper.has_component(ent, Memory)
            or esper.has_component(ent, Mindset)
            or esper.has_component(ent, Personality)
        )

    def process(self, *args, **kwargs) -> None:
        """Apply movement intents to entities checking walkability, doors, and boundaries."""
        # Only process local movement when active in LOCAL_MAP state
        if self.state_manager is not None and self.state_manager.state != GameState.LOCAL_MAP:
            return

        for ent, (pos, intent) in list(esper.get_components(Position, MovementIntent)):
            # Check for pass turn / wait intent (dx=0, dy=0, dz=0)
            if intent.dx == 0 and intent.dy == 0 and intent.dz == 0:
                if self.turn_system is not None:
                    self.turn_system.pass_turn(ent)
                esper.remove_component(ent, MovementIntent)
                continue

            target_x = pos.x + intent.dx
            target_y = pos.y + intent.dy
            target_z = pos.z + intent.dz

            # 0. Check extreme edge trigger for Player in LOCAL_MAP if already on extreme edge
            if esper.has_component(ent, Player) and self.state_manager is not None and self.state_manager.state == GameState.LOCAL_MAP:
                map_w = self.game_map.width if self.game_map else self.bounds_width
                map_h = self.game_map.height if self.game_map else self.bounds_height
                if pos.x <= 0 or pos.x >= map_w - 1 or pos.y <= 0 or pos.y >= map_h - 1:
                    esper.remove_component(ent, MovementIntent)
                    if self.transition_system is not None:
                        self.transition_system.ascend_to_regional_map(ent)
                    continue

            # 1. Bump-to-open door interaction
            if self.door_system is not None and (intent.dx != 0 or intent.dy != 0):
                door_ent = self.door_system.get_door_at(target_x, target_y, target_z)
                if door_ent is not None:
                    door = esper.component_for_entity(door_ent, Door)
                    if not door.is_open:
                        # Bumped into closed door: open it and consume turn
                        self.door_system.open_door(door_ent)
                        esper.remove_component(ent, MovementIntent)
                        if self.turn_system is not None:
                            self.turn_system.tick()
                        continue

            # 2. Check collision with map tiles
            target_tile = self.game_map.get_tile(target_x, target_y, target_z) if self.game_map else None
            if self.game_map is not None:
                if not self.game_map.is_walkable(target_x, target_y, target_z):
                    if esper.has_component(ent, Player) and self.turn_system is not None:
                        if target_tile is not None and target_tile.char == "T":
                            species_text = f"{target_tile.tree_species} " if getattr(target_tile, "tree_species", None) else ""
                            self.turn_system.combat_log.add(f"Movement blocked by a {species_text}tree trunk.")
                    esper.remove_component(ent, MovementIntent)
                    continue

            # 3. Check entity collision (prevent walking through entities; bump-to-talk with NPCs)
            blocking_ent = self.get_blocking_entity_at(target_x, target_y, target_z, exclude_ent=ent)
            if blocking_ent is not None:
                # If Player bumped into an interactable NPC, open dialogue window instead of attacking
                if esper.has_component(ent, Player) and self.is_interactable_npc(blocking_ent):
                    if self.interaction_system is not None:
                        self.interaction_system.interact(ent, blocking_ent)
                    esper.remove_component(ent, MovementIntent)
                    continue

                # Non-interactable entity blocks movement
                if esper.has_component(ent, Player) and self.turn_system is not None:
                    other_name = "an entity"
                    if esper.has_component(blocking_ent, Name):
                        other_name = esper.component_for_entity(blocking_ent, Name).name
                    self.turn_system.combat_log.add(f"Movement blocked by {other_name}.")

                esper.remove_component(ent, MovementIntent)
                continue

            # 4. Determine movement cost and terrain difficulty
            # "Ditch movement energy cost for terrain that is not hard. Add movement cost to terrain, with the current floor having cost one."
            is_hard = False
            move_cost = 1
            if target_tile is not None:
                move_cost = target_tile.movement_cost
                is_hard = target_tile.is_hard or (target_tile.movement_cost > 1)

            # Normal terrain (movement_cost <= 1, not hard) costs 0 energy! Only hard terrain costs energy.
            energy_cost = move_cost if is_hard else 0

            # Check Energy requirement if terrain is hard
            if self.turn_system is not None and esper.has_component(ent, Energy):
                if energy_cost > 0 and not self.turn_system.can_entity_act(ent, energy_cost):
                    if esper.has_component(ent, Player):
                        self.turn_system.combat_log.add(
                            f"Terrain is too hard to cross without Energy! (Need {energy_cost})"
                        )
                    esper.remove_component(ent, MovementIntent)
                    continue

            moved = False

            if self.game_map is not None:
                pos.x = target_x
                pos.y = target_y
                pos.z = target_z
                moved = True
            else:
                # Fallback bounds check if no game map is provided
                if 0 <= target_x < self.bounds_width:
                    pos.x = target_x
                    moved = True
                if 0 <= target_y < self.bounds_height:
                    pos.y = target_y
                    moved = True
                pos.z = target_z

            if moved and self.turn_system is not None:
                if energy_cost > 0 and esper.has_component(ent, Energy):
                    energy = esper.component_for_entity(ent, Energy)
                    energy.consume(energy_cost)
                # Advance turn and regenerate energy!
                self.turn_system.tick()

            # Check if player reached the extreme edge (X=0, 199, Y=0, 199) of the LOCAL_MAP
            if moved and esper.has_component(ent, Player) and self.state_manager is not None and self.state_manager.state == GameState.LOCAL_MAP:
                map_w = self.game_map.width if self.game_map else self.bounds_width
                map_h = self.game_map.height if self.game_map else self.bounds_height
                if pos.x <= 0 or pos.x >= map_w - 1 or pos.y <= 0 or pos.y >= map_h - 1:
                    if self.transition_system is not None:
                        self.transition_system.ascend_to_regional_map(ent)

            # Intent consumed; remove component
            esper.remove_component(ent, MovementIntent)
