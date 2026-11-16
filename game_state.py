"""Game state definitions and management for Sandbox Roguelike RPG.

Provides top-level state tracking (e.g. Local Map vs. Regional Map) to allow
modular transitions between game modes.
"""

from enum import Enum, auto


class GameState(Enum):
    """Represents the active game mode or viewport."""

    LOCAL_MAP = auto()
    REGIONAL_MAP = auto()
    INVENTORY = auto()
    CHARACTER = auto()
    TARGETING = auto()


class GameStateManager:
    """Manages transitions and queries for the active game state."""

    def __init__(self, initial_state: GameState = GameState.LOCAL_MAP) -> None:
        self.state: GameState = initial_state
        self.previous_state: GameState = initial_state
        # Targeting state variables
        self.targeting_skill = None
        self.cursor_x: int = 0
        self.cursor_y: int = 0
        self.cursor_z: int = 0
        self.origin_x: int = 0
        self.origin_y: int = 0
        self.origin_z: int = 0
        self.max_range: int = 5

    def toggle_map(self) -> GameState:
        """Toggle between LOCAL_MAP and REGIONAL_MAP modes."""
        if self.state == GameState.LOCAL_MAP:
            self.previous_state = self.state
            self.state = GameState.REGIONAL_MAP
        elif self.state == GameState.REGIONAL_MAP:
            self.state = GameState.LOCAL_MAP
        return self.state

    def open_inventory(self) -> None:
        """Switch to INVENTORY state preserving previous state."""
        if self.state != GameState.INVENTORY:
            self.previous_state = self.state
            self.state = GameState.INVENTORY

    def close_inventory(self) -> None:
        """Exit INVENTORY state returning to previous state (default LOCAL_MAP)."""
        if self.state == GameState.INVENTORY:
            self.state = self.previous_state if self.previous_state not in (GameState.INVENTORY, GameState.CHARACTER) else GameState.LOCAL_MAP

    def toggle_inventory(self) -> GameState:
        """Toggle between INVENTORY and previous/local map state."""
        if self.state == GameState.INVENTORY:
            self.close_inventory()
        else:
            self.open_inventory()
        return self.state

    def open_character(self) -> None:
        """Switch to CHARACTER screen state preserving previous state."""
        if self.state != GameState.CHARACTER:
            self.previous_state = self.state
            self.state = GameState.CHARACTER

    def close_character(self) -> None:
        """Exit CHARACTER state returning to previous state (default LOCAL_MAP)."""
        if self.state == GameState.CHARACTER:
            self.state = self.previous_state if self.previous_state not in (GameState.CHARACTER, GameState.INVENTORY) else GameState.LOCAL_MAP

    def toggle_character(self) -> GameState:
        """Toggle between CHARACTER screen and previous/local map state."""
        if self.state == GameState.CHARACTER:
            self.close_character()
        else:
            self.open_character()
        return self.state

    def set_state(self, new_state: GameState) -> None:
        """Directly update the current game state."""
        self.previous_state = self.state
        self.state = new_state

    def start_targeting(
        self,
        skill=None,
        origin_x: int = 0,
        origin_y: int = 0,
        origin_z: int = 0,
        max_range: int = 5,
    ) -> None:
        """Switch to TARGETING state and initialize cursor at origin position."""
        if self.state != GameState.TARGETING:
            self.previous_state = self.state
            self.state = GameState.TARGETING
        self.targeting_skill = skill
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.origin_z = origin_z
        self.cursor_x = origin_x
        self.cursor_y = origin_y
        self.cursor_z = origin_z
        self.max_range = max_range if skill is None or not hasattr(skill, "range") else skill.range

    def move_cursor(self, dx: int, dy: int, map_width: int = 99999, map_height: int = 99999) -> bool:
        """Move cursor if within max_range of origin and within map bounds."""
        new_x = self.cursor_x + dx
        new_y = self.cursor_y + dy
        dist = max(abs(new_x - self.origin_x), abs(new_y - self.origin_y))
        if dist <= self.max_range and 0 <= new_x < map_width and 0 <= new_y < map_height:
            self.cursor_x = new_x
            self.cursor_y = new_y
            return True
        return False

    def cancel_targeting(self) -> None:
        """Cancel TARGETING state and return to previous state (default LOCAL_MAP)."""
        if self.state == GameState.TARGETING:
            self.state = (
                self.previous_state
                if self.previous_state not in (GameState.TARGETING, GameState.INVENTORY, GameState.CHARACTER)
                else GameState.LOCAL_MAP
            )
            self.targeting_skill = None

    def close_targeting(self) -> None:
        """Exit TARGETING state returning to previous state (alias for cancel_targeting)."""
        self.cancel_targeting()
