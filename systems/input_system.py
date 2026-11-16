"""Input System for capturing keyboard events and translating them into ECS intents.

Handles general gameplay inputs, map movement, interactable door toggling,
and top-level game state toggling (e.g., toggling between Local Map and Regional Map via 'M').
"""

from bearlibterminal import terminal
import esper

from components import Energy, EquipmentSlot, Inventory, MovementIntent, Player, Position, RegionalPosition, Skill, SkillBar
from game_state import GameState, GameStateManager
from systems.door_system import DoorSystem
from systems.turn_management_system import TurnManagementSystem


# Key mapping for 2D cardinal and diagonal movements
DIRECTION_KEYS: dict[int, tuple[int, int]] = {
    # Arrow keys
    terminal.TK_LEFT: (-1, 0),
    terminal.TK_RIGHT: (1, 0),
    terminal.TK_UP: (0, -1),
    terminal.TK_DOWN: (0, 1),
    # Numpad keys (standard 8-direction + wait)
    terminal.TK_KP_1: (-1, 1),   # South-West
    terminal.TK_KP_2: (0, 1),    # South
    terminal.TK_KP_3: (1, 1),    # South-East
    terminal.TK_KP_4: (-1, 0),   # West
    terminal.TK_KP_5: (0, 0),    # Center / Wait
    terminal.TK_KP_6: (1, 0),    # East
    terminal.TK_KP_7: (-1, -1),  # North-West
    terminal.TK_KP_8: (0, -1),   # North
    terminal.TK_KP_9: (1, -1),   # North-East
}


class InputSystem(esper.Processor):
    """Captures player input and translates it into movement and interaction intents."""

    def __init__(
        self,
        state_manager: GameStateManager | None = None,
        door_system: DoorSystem | None = None,
        turn_system: TurnManagementSystem | None = None,
        interaction_system=None,
        item_collection_system=None,
        equipment_system=None,
        game_map=None,
        regional_movement_system=None,
        transition_system=None,
    ) -> None:
        super().__init__()
        self.state_manager = state_manager
        self.door_system = door_system
        self.turn_system = turn_system
        self.interaction_system = interaction_system
        self.item_collection_system = item_collection_system
        self.equipment_system = equipment_system
        self.game_map = game_map
        self.regional_movement_system = regional_movement_system
        self.transition_system = transition_system

    def _is_shift_pressed(self) -> bool:
        """Check if Shift key is currently held down in BearLibTerminal."""
        try:
            return terminal.check(terminal.TK_SHIFT) or terminal.state(terminal.TK_SHIFT) > 0
        except Exception:
            return False

    def process(self, key: int | None = None, *args, **kwargs) -> None:
        """Process keyboard input event: handle state toggles, door interaction, skills, or movement."""
        if key is None:
            return

        # 0. Check if currently in REGIONAL_MAP mode
        if self.state_manager is not None and self.state_manager.state == GameState.REGIONAL_MAP:
            # Check for map mode toggle ('M')
            if self._is_map_toggle_key(key):
                self.state_manager.toggle_map()
                return

            # Descending to Local Map on ENTER:
            # Trigger LocalMapGenerator for current regional tile, place player at center (100, 100).
            # If player is already descended in this tile (e.g. opened map viewer via 'M'), resume local map.
            if key in (terminal.TK_ENTER, terminal.TK_KP_ENTER, ord("\r"), ord("\n")):
                for ent, _player in esper.get_components(Player):
                    if esper.has_component(ent, RegionalPosition):
                        reg_pos = esper.component_for_entity(ent, RegionalPosition)
                        if reg_pos.is_descended:
                            self.state_manager.state = GameState.LOCAL_MAP
                            return
                    if self.transition_system is not None:
                        self.transition_system.descend_to_local_map(ent)
                        return
                return

            # Regional Movement with arrow keys: exactly 1 regional tile, advances WorldClock by 4h, drains 1 food/water
            if key in DIRECTION_KEYS and self.regional_movement_system is not None:
                dx, dy = DIRECTION_KEYS[key]
                for ent, _player in esper.get_components(Player):
                    self.regional_movement_system.move_player(ent, dx, dy)
                    return
                return

            return

        # 0. Check if currently in TARGETING mode
        if self.state_manager is not None and self.state_manager.state == GameState.TARGETING:
            # Cancel on ESC or '2'
            if key in (terminal.TK_ESCAPE, terminal.TK_2, ord("2")):
                self.state_manager.cancel_targeting()
                return

            # Execute skill on ENTER
            if key in (terminal.TK_ENTER, terminal.TK_KP_ENTER, ord("\r"), ord("\n")):
                for ent, (pos, _player) in esper.get_components(Position, Player):
                    target_x = self.state_manager.cursor_x
                    target_y = self.state_manager.cursor_y
                    target_z = self.state_manager.cursor_z
                    skill = self.state_manager.targeting_skill
                    if self.turn_system is not None:
                        self.turn_system.execute_fireball(
                            user_ent=ent,
                            target_x=target_x,
                            target_y=target_y,
                            target_z=target_z,
                            skill=skill,
                        )
                    self.state_manager.cancel_targeting()
                    return
                return

            # Move cursor with arrow / direction keys
            if key in DIRECTION_KEYS:
                dx, dy = DIRECTION_KEYS[key]
                map_w = self.game_map.width if self.game_map else (
                    self.door_system.game_map.width if self.door_system and hasattr(self.door_system, "game_map") else 99999
                )
                map_h = self.game_map.height if self.game_map else (
                    self.door_system.game_map.height if self.door_system and hasattr(self.door_system, "game_map") else 99999
                )
                self.state_manager.move_cursor(dx, dy, map_w, map_h)
                return

            # In targeting mode, character cannot move and other actions are suppressed
            return

        # 0a. Check if currently in Character Screen mode ('C')
        if self.state_manager is not None and self.state_manager.state == GameState.CHARACTER:
            # ESC or 'C' closes the Character Screen (equipping is handled exclusively via Inventory 'I')
            if key in (terminal.TK_ESCAPE, terminal.TK_C, ord("c"), ord("C")):
                self.state_manager.close_character()
                return
            try:
                if terminal.check(terminal.TK_CHAR) and chr(terminal.state(terminal.TK_CHAR)).lower() == "c":
                    self.state_manager.close_character()
                    return
            except Exception:
                pass
            return

        # 0b. Check if currently in Inventory mode ('I')
        if self.state_manager is not None and self.state_manager.state == GameState.INVENTORY:
            # ESC or 'I' closes the inventory overlay
            if key in (terminal.TK_ESCAPE, terminal.TK_I, ord("i"), ord("I")):
                self.state_manager.close_inventory()
                return
            try:
                if terminal.check(terminal.TK_CHAR) and chr(terminal.state(terminal.TK_CHAR)).lower() == "i":
                    self.state_manager.close_inventory()
                    return
            except Exception:
                pass

            # Pressing a letter key [a-z] equips an item from inventory
            item_idx = self._get_char_item_index(key)
            if item_idx is not None and self.equipment_system is not None:
                for ent, _player in esper.get_components(Player):
                    if esper.has_component(ent, Inventory):
                        inv = esper.component_for_entity(ent, Inventory)
                        if 0 <= item_idx < len(inv.items):
                            self.equipment_system.equip_item(ent, inv.items[item_idx])
                            return
            return

        # Check if an active NPC dialogue window is open
        if self.interaction_system is not None and self.interaction_system.has_active_dialogue():
            # Dismiss on SPACE, ESC, ENTER, or close and continue for other actions
            if key in (terminal.TK_SPACE, terminal.TK_ESCAPE, terminal.TK_ENTER, ord(" ")):
                self.interaction_system.close_dialogue()
                return
            else:
                self.interaction_system.close_dialogue()

        # 1. Check for map mode toggle ('M')
        if self._is_map_toggle_key(key):
            if self.state_manager is not None:
                self.state_manager.toggle_map()
            return

        # If currently in Regional Map mode, ignore local interactions and movements
        if self.state_manager is not None and self.state_manager.state != GameState.LOCAL_MAP:
            return

        # Check for SHIFT+ENTER: Ascend to Regional Map (deleting local map entities)
        is_shift = kwargs.get("is_shift", False) or self._is_shift_pressed()
        if is_shift and key in (terminal.TK_ENTER, terminal.TK_KP_ENTER, ord("\r"), ord("\n")):
            if self.transition_system is not None:
                for ent, _player in esper.get_components(Player):
                    self.transition_system.ascend_to_regional_map(ent)
                    return
            return

        # 2. Check for Character Screen toggle ('C')
        if self._is_character_key(key):
            if self.state_manager is not None:
                self.state_manager.open_character()
            return

        # 3. Check for Inventory toggle key ('I')
        if self._is_inventory_key(key):
            if self.state_manager is not None:
                self.state_manager.open_inventory()
            return

        # 4. Check for Item Pickup key ('G')
        if self._is_pickup_key(key):
            if self.item_collection_system is not None:
                for ent, _player in esper.get_components(Player):
                    self.item_collection_system.collect_item(ent)
                    return
            return

        # 5. Check for Door interaction key ('E' or 'O')
        if self._is_door_interact_key(key):
            if self.door_system is not None:
                for _ent, (pos, _player) in esper.get_components(Position, Player):
                    self.door_system.interact_adjacent(pos.x, pos.y, pos.z)
                    return

        # 6. Check for Combat Skills ('1' for Cleave, '2' for Fireball)
        if self._is_skill_key(key, 1):
            if self.turn_system is not None:
                for ent, _player in esper.get_components(Player):
                    self.turn_system.execute_cleave(ent)
                    return
            return

        if self._is_skill_key(key, 2):
            for ent, (pos, _player) in esper.get_components(Position, Player):
                # Resolve Fireball skill
                skill = None
                if esper.has_component(ent, SkillBar):
                    sbar = esper.component_for_entity(ent, SkillBar)
                    for s in sbar.skills:
                        if s.name.lower() == "fireball":
                            skill = s
                            break
                    if skill is None and len(sbar.skills) > 1:
                        skill = sbar.skills[1]

                if skill is None:
                    skill = Skill(
                        name="Fireball",
                        energy_cost=20,
                        damage=25,
                        range=5,
                        description="Ranged fire projectile (Range: 5)",
                    )

                # Check if player has enough Energy
                if esper.has_component(ent, Energy):
                    energy = esper.component_for_entity(ent, Energy)
                    if not energy.can_act(skill.energy_cost):
                        msg = f"Not enough Energy to use {skill.name}! (Need {skill.energy_cost}, have {energy.current})"
                        if self.turn_system is not None and hasattr(self.turn_system, "combat_log"):
                            self.turn_system.combat_log.add(msg)
                        return

                # Enter GameState.TARGETING mode
                if self.state_manager is not None:
                    self.state_manager.start_targeting(
                        skill=skill,
                        origin_x=pos.x,
                        origin_y=pos.y,
                        origin_z=pos.z,
                        max_range=getattr(skill, "range", 5),
                    )
                return
            return

        # 7. Check for Pass Turn / Wait ('.' or TK_PERIOD)
        if self._is_wait_key(key):
            if self.turn_system is not None:
                for ent, _player in esper.get_components(Player):
                    self.turn_system.pass_turn(ent)
                    return
            else:
                for ent, _player in esper.get_components(Player):
                    esper.add_component(ent, MovementIntent(dx=0, dy=0, dz=0))
                return

        dx = 0
        dy = 0
        dz = 0

        # 3. Check arrow keys and numpad
        if key in DIRECTION_KEYS:
            dx, dy = DIRECTION_KEYS[key]
        # 4. Check Z-level movement (< for Up, > for Down)
        elif self._is_up_key(key):
            dz = 1
        elif self._is_down_key(key):
            dz = -1
        else:
            return

        # Attach MovementIntent to all player entities
        for ent, _player in esper.get_components(Player):
            esper.add_component(ent, MovementIntent(dx=dx, dy=dy, dz=dz))

    def _is_map_toggle_key(self, key: int) -> bool:
        """Check if the key corresponds to 'M' (toggle between Local and Regional map)."""
        if key in (terminal.TK_M, ord("M"), ord("m")):
            return True
        try:
            if terminal.check(terminal.TK_CHAR) and chr(terminal.state(terminal.TK_CHAR)) in ("m", "M"):
                return True
        except Exception:
            pass
        return False

    def _is_door_interact_key(self, key: int) -> bool:
        """Check if the key corresponds to a door interact key ('E' or 'O')."""
        if key in (terminal.TK_E, terminal.TK_O):
            return True
        try:
            if terminal.check(terminal.TK_CHAR) and chr(terminal.state(terminal.TK_CHAR)).lower() in ("e", "o"):
                return True
        except Exception:
            pass
        return False

    def _is_character_key(self, key: int) -> bool:
        """Check if the key corresponds to 'C' (Open/close character screen)."""
        if key in (terminal.TK_C, ord("C"), ord("c")):
            return True
        try:
            if terminal.check(terminal.TK_CHAR) and chr(terminal.state(terminal.TK_CHAR)).lower() == "c":
                return True
        except Exception:
            pass
        return False

    def _get_char_item_index(self, key: int) -> int | None:
        """Map key event to a 0-based inventory item index (a=0, b=1, ...)."""
        if terminal.TK_A <= key <= terminal.TK_Z:
            return key - terminal.TK_A
        if ord("a") <= key <= ord("z"):
            return key - ord("a")
        if ord("A") <= key <= ord("Z"):
            return key - ord("A")
        try:
            if terminal.check(terminal.TK_CHAR):
                ch = chr(terminal.state(terminal.TK_CHAR)).lower()
                if "a" <= ch <= "z":
                    return ord(ch) - ord("a")
        except Exception:
            pass
        return None

    def _get_slot_from_key(self, key: int) -> EquipmentSlot | None:
        """Map key event to one of the 11 EquipmentSlots for unequip."""
        slot_map = {
            terminal.TK_1: EquipmentSlot.HEAD,
            ord("1"): EquipmentSlot.HEAD,
            terminal.TK_2: EquipmentSlot.CAPE,
            ord("2"): EquipmentSlot.CAPE,
            terminal.TK_3: EquipmentSlot.TORSO,
            ord("3"): EquipmentSlot.TORSO,
            terminal.TK_4: EquipmentSlot.GLOVES,
            ord("4"): EquipmentSlot.GLOVES,
            terminal.TK_5: EquipmentSlot.LEGS,
            ord("5"): EquipmentSlot.LEGS,
            terminal.TK_6: EquipmentSlot.BOOTS,
            ord("6"): EquipmentSlot.BOOTS,
            terminal.TK_7: EquipmentSlot.HAIR_ORNAMENT,
            ord("7"): EquipmentSlot.HAIR_ORNAMENT,
            terminal.TK_8: EquipmentSlot.NECKLACE,
            ord("8"): EquipmentSlot.NECKLACE,
            terminal.TK_9: EquipmentSlot.BELT,
            ord("9"): EquipmentSlot.BELT,
            terminal.TK_0: EquipmentSlot.WRISTBAND,
            ord("0"): EquipmentSlot.WRISTBAND,
            terminal.TK_MINUS: EquipmentSlot.RING,
            ord("-"): EquipmentSlot.RING,
        }
        return slot_map.get(key)

    def _is_inventory_key(self, key: int) -> bool:
        """Check if the key corresponds to 'I' (Open/close inventory overlay)."""
        if key in (terminal.TK_I, ord("I"), ord("i")):
            return True
        try:
            if terminal.check(terminal.TK_CHAR) and chr(terminal.state(terminal.TK_CHAR)).lower() == "i":
                return True
        except Exception:
            pass
        return False

    def _is_pickup_key(self, key: int) -> bool:
        """Check if the key corresponds to 'G' (Get / Pick up item from ground)."""
        if key in (terminal.TK_G, ord("G"), ord("g")):
            return True
        try:
            if terminal.check(terminal.TK_CHAR) and chr(terminal.state(terminal.TK_CHAR)).lower() == "g":
                return True
        except Exception:
            pass
        return False

    def _is_up_key(self, key: int) -> bool:
        """Check if the key corresponds to '<' (move up Z-level)."""
        if key == ord("<"):
            return True
        try:
            if terminal.check(terminal.TK_CHAR) and terminal.state(terminal.TK_CHAR) == ord("<"):
                return True
            if key == terminal.TK_COMMA and terminal.check(terminal.TK_SHIFT):
                return True
        except Exception:
            pass
        return False

    def _is_skill_key(self, key: int, slot: int) -> bool:
        """Check if key corresponds to skill slot (1..9)."""
        target_char = str(slot)
        tk_constants = {
            1: terminal.TK_1,
            2: terminal.TK_2,
            3: terminal.TK_3,
            4: terminal.TK_4,
            5: terminal.TK_5,
            6: terminal.TK_6,
            7: terminal.TK_7,
            8: terminal.TK_8,
            9: terminal.TK_9,
        }
        if slot in tk_constants and key == tk_constants[slot]:
            return True
        if key == ord(target_char):
            return True
        try:
            if terminal.check(terminal.TK_CHAR) and chr(terminal.state(terminal.TK_CHAR)) == target_char:
                return True
        except Exception:
            pass
        return False

    def _is_wait_key(self, key: int) -> bool:
        """Check if key corresponds to wait/pass turn ('.' or TK_PERIOD without shift)."""
        try:
            if terminal.check(terminal.TK_SHIFT):
                return False
        except Exception:
            pass

        if key in (terminal.TK_PERIOD, ord(".")):
            return True
        try:
            if terminal.check(terminal.TK_CHAR) and terminal.state(terminal.TK_CHAR) == ord("."):
                return True
        except Exception:
            pass
        return False

    def _is_down_key(self, key: int) -> bool:
        """Check if the key corresponds to '>' (move down Z-level)."""
        if key == ord(">"):
            return True
        try:
            if terminal.check(terminal.TK_CHAR) and terminal.state(terminal.TK_CHAR) == ord(">"):
                return True
            if key == terminal.TK_PERIOD and terminal.check(terminal.TK_SHIFT):
                return True
        except Exception:
            pass
        return False
