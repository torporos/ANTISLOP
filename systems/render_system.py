"""Rendering System for displaying map tiles, entities, and UI via BearLibTerminal.

Layout (120x40):
- Map Viewport: Top Left, 85 x 30 (Layer 0)
- GUI Sidebar: Top Right, 35 x 30 (Layer 2)
- Message Console & Dialogue Box: Bottom, 120 x 10 (Layer 2)

Features:
- Strict Single-Character Rendering: Hierarchy (Player > NPC > Item > Furniture > Floor).
  Entities suppress underlying floor/stairs/wall tiles so tiles never bleed through.
- Message Console doubles as Dialogue Box when active dialogue is open.
- Proper bracket escaping for BearLibTerminal keybind reminders and hotbar slots.
"""

import textwrap
from bearlibterminal import terminal
import esper

from camera import Camera
from components import (
    Energy,
    Equipment,
    EquipmentSlot,
    Equippable,
    Fighter,
    Inventory,
    Item,
    Name,
    Player,
    Position,
    RegionalPosition,
    RenderOrder,
    Renderable,
    SkillBar,
    Stats,
    SurvivalStats,
    Viewshed,
)
from game_map import GameMap
from game_state import GameState, GameStateManager
from message_log import MessageLog, global_message_log
from regional_map_generator import BIOME_REGISTRY, RegionalMap
from systems.turn_management_system import CombatLog


# 16x16 Static ASCII Portrait for Character Screen Paper Doll
PORTRAIT_16X16: list[str] = [
    r"     ______     ",
    r"   .-'      '-. ",
    r"  /            \ ",
    r" |   .----.   | ",
    r" |  /  __  \  | ",
    r" | |  /  \  | | ",
    r" | | | () | | | ",
    r" | |  \__/  | | ",
    r" |  \  __  /  | ",
    r" |   '----'   | ",
    r"  \  [====]  /  ",
    r"   '.  __  .'   ",
    r"    | |  | |    ",
    r"   /  |  |  \   ",
    r"  /   |  |   \  ",
    r" '----'  '----' ",
]


# 5x5 ASCII Box Art for Equipment Slots
EMPTY_SLOT_ART: list[str] = [
    "_____",
    "|   |",
    "|   |",
    "|   |",
    "¯¯¯¯¯",
]

RING_ART: list[str] = [
    "_____",
    "| _ |",
    "|< >|",
    "| ¯ |",
    "¯¯¯¯¯",
]

TORSO_ART: list[str] = [
    "_____",
    "| _ |",
    "|{ }|",
    "|[-]|",
    "¯¯¯¯¯",
]

HEAD_ART: list[str] = [
    "_____",
    r"|/-\|",
    "|o o|",
    r"|\_/|",
    "¯¯¯¯¯",
]

CAPE_ART: list[str] = [
    "_____",
    "|~v~|",
    r"|/ \|",
    r"|/ \|",
    "¯¯¯¯¯",
]

GLOVES_ART: list[str] = [
    "_____",
    "|nnn|",
    "|(_)|",
    "|   |",
    "¯¯¯¯¯",
]

LEGS_ART: list[str] = [
    "_____",
    "|===|",
    r"|/ \|",
    "|| ||",
    "¯¯¯¯¯",
]

BOOTS_ART: list[str] = [
    "_____",
    "|! !|",
    "|L J|",
    "|___|",
    "¯¯¯¯¯",
]

HAIR_ORNAMENT_ART: list[str] = [
    "_____",
    r"|\*/|",
    "| ~ |",
    "|   |",
    "¯¯¯¯¯",
]

NECKLACE_ART: list[str] = [
    "_____",
    r"|\ /|",
    "| v |",
    "| * |",
    "¯¯¯¯¯",
]

BELT_ART: list[str] = [
    "_____",
    "|---|",
    "|[o]|",
    "|---|",
    "¯¯¯¯¯",
]

WRISTBAND_ART: list[str] = [
    "_____",
    "| | |",
    "|(=)|",
    "| | |",
    "¯¯¯¯¯",
]

SLOT_ART_PRESETS: dict[EquipmentSlot, list[str]] = {
    EquipmentSlot.HEAD: HEAD_ART,
    EquipmentSlot.CAPE: CAPE_ART,
    EquipmentSlot.TORSO: TORSO_ART,
    EquipmentSlot.GLOVES: GLOVES_ART,
    EquipmentSlot.LEGS: LEGS_ART,
    EquipmentSlot.BOOTS: BOOTS_ART,
    EquipmentSlot.HAIR_ORNAMENT: HAIR_ORNAMENT_ART,
    EquipmentSlot.NECKLACE: NECKLACE_ART,
    EquipmentSlot.BELT: BELT_ART,
    EquipmentSlot.WRISTBAND: WRISTBAND_ART,
    EquipmentSlot.RING: RING_ART,
}

SLOT_DEFAULT_COLORS: dict[EquipmentSlot, str] = {
    EquipmentSlot.HEAD: "light cyan",
    EquipmentSlot.CAPE: "light blue",
    EquipmentSlot.TORSO: "light brown",
    EquipmentSlot.GLOVES: "light gray",
    EquipmentSlot.LEGS: "gray",
    EquipmentSlot.BOOTS: "brown",
    EquipmentSlot.HAIR_ORNAMENT: "light magenta",
    EquipmentSlot.NECKLACE: "cyan",
    EquipmentSlot.BELT: "orange",
    EquipmentSlot.WRISTBAND: "yellow",
    EquipmentSlot.RING: "amber",
}


class RenderSystem(esper.Processor):
    """Handles rendering of map tiles, entities, and UI elements with camera and FOV."""

    ROOF_CHAR: str = "^"
    ROOF_COLOR: str = "brown"
    EXPLORED_COLOR: str = "dark gray"
    DIMMED_COLOR: str = "darkest gray"

    # Layout constants
    DEFAULT_SCREEN_WIDTH: int = 120
    DEFAULT_SCREEN_HEIGHT: int = 40
    DEFAULT_MAP_VIEWPORT_WIDTH: int = 85
    DEFAULT_MAP_VIEWPORT_HEIGHT: int = 30
    DEFAULT_SIDEBAR_WIDTH: int = 35
    DEFAULT_CONSOLE_HEIGHT: int = 10

    def __init__(
        self,
        game_map: GameMap | None = None,
        viewport_width: int = DEFAULT_MAP_VIEWPORT_WIDTH,
        viewport_height: int = DEFAULT_MAP_VIEWPORT_HEIGHT,
        screen_width: int = DEFAULT_SCREEN_WIDTH,
        screen_height: int = DEFAULT_SCREEN_HEIGHT,
        dim_outside: bool = True,
        state_manager: GameStateManager | None = None,
        regional_map: RegionalMap | None = None,
        roof_char: str = ROOF_CHAR,
        roof_color: str = ROOF_COLOR,
        explored_color: str = EXPLORED_COLOR,
        combat_log: CombatLog | None = None,
        message_log: MessageLog | None = None,
        interaction_system=None,
        leaf_char: str = "%",
        leaf_color: int | str | None = None,
        leaf_alpha: int = 120,
        world_clock=None,
    ) -> None:
        super().__init__()
        try:
            terminal.set("palette: light brown = #c48a56, brown = #8b5a2b;")
        except Exception:
            pass
        self.game_map = game_map if game_map is not None else GameMap()
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.camera = Camera(viewport_width=viewport_width, viewport_height=viewport_height)
        self.dim_outside = dim_outside
        self.state_manager = state_manager
        self.regional_map = regional_map
        self.world_clock = world_clock
        self.roof_char = roof_char
        self.roof_color = roof_color
        self.explored_color = explored_color
        self.combat_log = combat_log
        self.message_log = (
            message_log
            if message_log is not None
            else (combat_log if combat_log is not None else global_message_log)
        )
        self.interaction_system = interaction_system
        self.leaf_char = leaf_char
        self.leaf_alpha = leaf_alpha
        if leaf_color is not None:
            self.leaf_color = leaf_color
        else:
            try:
                self.leaf_color = terminal.color_from_argb(leaf_alpha, 20, 85, 20)
            except Exception:
                self.leaf_color = 0x78145514
        try:
            self.dimmed_leaf_color = terminal.color_from_argb(max(30, leaf_alpha // 2), 10, 40, 10)
        except Exception:
            self.dimmed_leaf_color = 0x3c0a280a

    def get_tile_render_info(
        self,
        map_x: int,
        map_y: int,
        z: int,
        active_viewshed: Viewshed | None = None,
    ) -> tuple[str, str] | None:
        """Return (char, color) to render for a map tile, or None if hidden in fog of war."""
        tile = self.game_map.get_tile(map_x, map_y, z)
        if tile is None:
            return None

        is_in_fov = (
            active_viewshed.is_visible(map_x, map_y)
            if active_viewshed is not None
            else True
        )
        is_explored = self.game_map.is_explored(map_x, map_y, z)

        tile_building_id = tile.building_id or self.game_map.get_building_id_at(map_x, map_y, z)
        if tile_building_id is None and tile.room_id is not None:
            tile_building_id = self.game_map.get_building_id_for_room(tile.room_id, z)

        is_building_discovered = (
            tile_building_id is not None
            and self.game_map.is_building_discovered(tile_building_id)
        )

        # A tile can be rendered if in active FOV, explored, or part of a discovered building
        if not is_in_fov and not is_explored and not is_building_discovered:
            return None

        player_room_id = active_viewshed.current_room_id if active_viewshed else None
        inside_structure = active_viewshed.inside_structure if active_viewshed else False
        active_structure = active_viewshed.active_structure if active_viewshed else None

        # Determine whether player is inside a building and whether this tile is in that same building
        player_in_building = inside_structure or (player_room_id is not None)
        is_same_building = False
        if player_in_building and active_viewshed is not None:
            p_bldg = (
                getattr(active_viewshed, "active_building_id", None)
                or (active_structure.building_id if active_structure else None)
                or (self.game_map.get_building_id_for_room(player_room_id, z) if player_room_id else None)
            )
            t_bldg = tile_building_id

            if p_bldg is not None and t_bldg is not None:
                is_same_building = (p_bldg == t_bldg)
            elif active_structure is not None and active_structure.contains(map_x, map_y, z):
                is_same_building = True
            elif player_room_id is not None and tile.room_id is not None:
                is_same_building = self.game_map.are_rooms_in_same_building(player_room_id, tile.room_id)

        if is_in_fov:
            # 1. Tile is in active FOV: normal bright colors, subject to interior occlusion
            render_char = tile.char
            if player_in_building:
                if is_same_building or (player_room_id is not None and tile.room_id == player_room_id):
                    tile_color = tile.color
                else:
                    if self.dim_outside:
                        tile_color = self.DIMMED_COLOR
                    else:
                        return None
            else:
                tile_color = tile.color
            return render_char, tile_color
        else:
            # 2. Tile is explored or part of discovered building, but NOT in active FOV:
            is_outer = self.game_map.is_outer_wall(map_x, map_y, z)
            if is_outer:
                # Rule: "the roof doesnt render over the outer walls of the building"
                return tile.char, self.explored_color

            if tile.room_id is not None or tile_building_id is not None:
                # Rule: "Also, if you are inside a building, never render roof of that buildings other rooms"
                if player_in_building and is_same_building:
                    # Inside the building: do not render roof over other rooms of this building!
                    return tile.char, self.explored_color
                else:
                    # Exterior view or different building: render roof tile so building appears solid
                    return self.roof_char, self.roof_color
            else:
                # Exterior tile in fog of war: render darker/muted colors
                return tile.char, self.explored_color

    def is_entity_rendered(
        self,
        pos: Position,
        active_viewshed: Viewshed | None = None,
    ) -> bool:
        """Check whether an entity at pos is rendered according to FOV and camera."""
        if active_viewshed is not None and not active_viewshed.is_visible(pos.x, pos.y):
            return False
        return self.camera.in_view(pos.x, pos.y)

    def process(self, *args, **kwargs) -> None:
        """Route rendering based on active GameState."""
        if self.state_manager is not None and self.state_manager.state == GameState.REGIONAL_MAP:
            self._render_regional_map()
        elif self.state_manager is not None and self.state_manager.state == GameState.INVENTORY:
            self._render_inventory_screen()
        elif self.state_manager is not None and self.state_manager.state == GameState.CHARACTER:
            self._render_character_screen()
        else:
            self._render_local_map(refresh=True)

    def _render_regional_map(self) -> None:
        """Render the 2D Voronoi cells and biomes of the Regional Map."""
        terminal.clear()

        if self.regional_map is not None:
            # 1. Draw Voronoi Biome Cells (Layer 0)
            terminal.layer(0)
            active_color = None
            render_w = min(self.screen_width, self.regional_map.width)
            render_h = min(self.screen_height - 3, self.regional_map.height)

            for y in range(render_h):
                for x in range(render_w):
                    biome_data = self.regional_map.get_biome_data(x, y)
                    if biome_data.color != active_color:
                        terminal.color(biome_data.color)
                        active_color = biome_data.color
                    terminal.puts(x, y, biome_data.char)

        # 2. Draw Player '@' on Regional Map (Layer 1)
        terminal.layer(1)
        for _ent, (reg_pos, _player) in esper.get_components(RegionalPosition, Player):
            terminal.color("white")
            terminal.puts(reg_pos.x, reg_pos.y, "@")
            break

        # 3. Regional Map HUD & Biome Legend (Layer 2)
        terminal.layer(2)
        terminal.color("white")
        terminal.puts(1, 1, "[[REGIONAL MAP]] Move: Arrows | Descend to Wilderness: ENTER | Toggle: M")

        # World Clock and Survival Stats Header
        time_display = self.world_clock.time_str if self.world_clock is not None else "Day 1, 08:00"
        survival_display = ""
        for _ent, (surv, _player) in esper.get_components(SurvivalStats, Player):
            survival_display = f" | Food: {surv.food}/{surv.max_food}  Water: {surv.water}/{surv.max_water}"
            break
        terminal.puts(1, 2, f"Time: {time_display}{survival_display}")

        # Bottom Legend
        legend_y = self.screen_height - 2
        terminal.color("white")
        terminal.puts(1, legend_y, "Biomes:")
        terminal.color("green")
        terminal.puts(9, legend_y, ". Plains")
        terminal.color("dark green")
        terminal.puts(19, legend_y, "T Forest")
        terminal.color("gray")
        terminal.puts(29, legend_y, "^ Mountains")

        terminal.refresh()

    def _render_local_map(self, refresh: bool = True) -> None:
        """Render tactical Local Map, GUI Sidebar, Message Console, and Dialogue."""
        if not getattr(self, "_palette_configured", False):
            try:
                ok = terminal.set("palette: light brown = #c48a56, brown = #8b5a2b;")
                if ok:
                    self._palette_configured = True
            except Exception:
                pass

        terminal.clear()

        # Find current player coordinates, active Z-level, and Viewshed
        player_x = 0
        player_y = 0
        current_z = 0
        player_found = False
        player_ent: int | None = None
        active_viewshed: Viewshed | None = None

        for _ent, (pos, _player) in esper.get_components(Position, Player):
            player_ent = _ent
            player_x = pos.x
            player_y = pos.y
            current_z = pos.z
            player_found = True
            if esper.has_component(_ent, Viewshed):
                active_viewshed = esper.component_for_entity(_ent, Viewshed)
            break

        # Center camera on player within map boundaries
        if player_found:
            self.camera.update(
                target_x=player_x,
                target_y=player_y,
                map_width=self.game_map.width,
                map_height=self.game_map.height,
            )

        # Check interior occlusion status
        player_room_id = active_viewshed.current_room_id if active_viewshed else None
        inside_structure = active_viewshed.inside_structure if active_viewshed else False
        active_structure = active_viewshed.active_structure if active_viewshed else None

        # 1. Collect all visible entities on active Z-level within the viewport
        # Grouped by (map_x, map_y)
        entities_by_pos: dict[tuple[int, int], list[tuple[int, Position, Renderable, str]]] = {}
        for ent, (pos, rend) in esper.get_components(Position, Renderable):
            if pos.z == current_z and self.camera.in_view(pos.x, pos.y):
                if active_viewshed is not None and not active_viewshed.is_visible(pos.x, pos.y):
                    continue

                rend_color = rend.color

                # Apply interior occlusion to entities outside active room/building
                if player_room_id is not None:
                    ent_tile = self.game_map.get_tile(pos.x, pos.y, pos.z)
                    is_same_bldg = False
                    p_bldg = getattr(active_viewshed, "active_building_id", None) or (
                        active_structure.building_id if active_structure else None
                    )
                    t_bldg = ent_tile.building_id if ent_tile else None
                    if p_bldg and t_bldg:
                        is_same_bldg = (p_bldg == t_bldg)

                    if (ent_tile is None or ent_tile.room_id != player_room_id) and not is_same_bldg:
                        if self.dim_outside:
                            rend_color = self.DIMMED_COLOR
                        else:
                            continue
                elif inside_structure and active_structure is not None:
                    if not active_structure.contains(pos.x, pos.y, current_z):
                        if self.dim_outside:
                            rend_color = self.DIMMED_COLOR
                        else:
                            continue

                entities_by_pos.setdefault((pos.x, pos.y), []).append((ent, pos, rend, rend_color))

        # 2. Strict Single-Character Rendering for Map Viewport (Layer 0, 85x30)
        # Hierarchy: Player (50) > NPC (40) > Item (30) > Furniture (20) > Floor (0)
        # Only render the single highest-priority character on each specific (X, Y) tile!
        # If an entity is present, it suppresses the floor/stairs/wall tile underneath so
        # tiles never render or bleed under moving entities.
        terminal.layer(0)
        active_color = None

        for screen_y in range(self.camera.viewport_height):
            map_y = self.camera.y + screen_y
            for screen_x in range(self.camera.viewport_width):
                map_x = self.camera.x + screen_x

                # Check if there are visible entities on this tile
                ent_candidates = entities_by_pos.get((map_x, map_y))
                if ent_candidates:
                    # Pick the single highest priority entity
                    best_ent, best_pos, best_rend, best_color = max(
                        ent_candidates,
                        key=lambda item: getattr(item[2], "render_order", 0),
                    )
                    if best_color != active_color:
                        terminal.color(best_color)
                        active_color = best_color
                    escaped_char = best_rend.char.replace("[", "[[").replace("]", "]]")
                    terminal.puts(screen_x, screen_y, escaped_char)
                    # Suppress map tile underneath: strict single-character rendering!
                    continue

                # No entities on this tile: render the underlying map tile
                render_info = self.get_tile_render_info(map_x, map_y, current_z, active_viewshed)
                if render_info is not None:
                    render_char, tile_color = render_info
                    if tile_color != active_color:
                        terminal.color(tile_color)
                        active_color = tile_color
                    escaped_tile_char = render_char.replace("[", "[[").replace("]", "]]")
                    terminal.puts(screen_x, screen_y, escaped_tile_char)

        # 2a. Tree Canopy Leaf Rendering (Layer 1):
        # Trees are represented by trunks ('T') on Layer 0, while leaves/canopy spread to surrounding tiles.
        # Draw leaves on top of the terrain using a darker green color with a lower alpha value (transparency)
        # in BearLibTerminal so the ground underneath is still slightly visible.
        terminal.layer(1)
        active_canopy_color = None
        for screen_y in range(self.camera.viewport_height):
            map_y = self.camera.y + screen_y
            for screen_x in range(self.camera.viewport_width):
                map_x = self.camera.x + screen_x
                if self.game_map.has_canopy(map_x, map_y, current_z):
                    is_in_fov = (
                        active_viewshed.is_visible(map_x, map_y)
                        if active_viewshed is not None
                        else True
                    )
                    is_explored = self.game_map.is_explored(map_x, map_y, current_z)
                    if not is_in_fov and not is_explored:
                        continue

                    # Interior occlusion check
                    c_color = self.leaf_color
                    if player_room_id is not None or inside_structure:
                        if self.dim_outside:
                            c_color = self.dimmed_leaf_color
                        else:
                            continue
                    elif not is_in_fov:
                        c_color = self.dimmed_leaf_color

                    if c_color != active_canopy_color:
                        terminal.color(c_color)
                        active_canopy_color = c_color
                    terminal.puts(screen_x, screen_y, self.leaf_char)

        # Reset to Layer 0 for cursor or other map-level elements
        terminal.layer(0)

        # 2b. Render Targeting Cursor (Layer 0) and status banner if in TARGETING state
        if self.state_manager is not None and self.state_manager.state == GameState.TARGETING:
            cursor_x = getattr(self.state_manager, "cursor_x", player_x)
            cursor_y = getattr(self.state_manager, "cursor_y", player_y)
            screen_x = cursor_x - self.camera.x
            screen_y = cursor_y - self.camera.y

            if 0 <= screen_x < self.camera.viewport_width and 0 <= screen_y < self.camera.viewport_height:
                terminal.layer(0)
                ent_cands = entities_by_pos.get((cursor_x, cursor_y))
                if ent_cands:
                    best_ent, best_pos, best_rend, best_color = max(
                        ent_cands,
                        key=lambda item: getattr(item[2], "render_order", 0),
                    )
                    target_char = best_rend.char
                else:
                    target_char = "X"

                terminal.bkcolor("yellow")
                terminal.color("black")
                escaped_target_char = target_char.replace("[", "[[").replace("]", "]]")
                terminal.puts(screen_x, screen_y, escaped_target_char)
                terminal.bkcolor("none")

            skill_name = (
                self.state_manager.targeting_skill.name
                if getattr(self.state_manager, "targeting_skill", None)
                else "Skill"
            )
            range_val = getattr(self.state_manager, "max_range", 5)

            target_desc = f"Cursor: ({cursor_x}, {cursor_y})"
            ent_cands = entities_by_pos.get((cursor_x, cursor_y))
            if ent_cands:
                best_ent = max(ent_cands, key=lambda item: getattr(item[2], "render_order", 0))[0]
                t_name = f"Entity {best_ent}"
                if esper.has_component(best_ent, Name):
                    t_name = esper.component_for_entity(best_ent, Name).name
                if esper.has_component(best_ent, Fighter):
                    t_fighter = esper.component_for_entity(best_ent, Fighter)
                    target_desc = f"Target: {t_name} ({t_fighter.hp}/{t_fighter.max_hp} HP)"
                else:
                    target_desc = f"Target: {t_name}"

            terminal.layer(2)
            terminal.color("yellow")
            terminal.puts(
                1,
                1,
                f"[[TARGETING: {skill_name}]] Range: {range_val} | {target_desc} | [[ENTER]] Cast | [[ESC]] Cancel",
            )

        # 3. GUI Sidebar (Top Right, 35x30, Layer 2)
        self._render_gui_sidebar(player_ent, player_x, player_y, current_z, active_viewshed)

        # 4. Message Console & Dialogue Box (Bottom, 120x10, Layer 2)
        # The bottom console acts as the dialogue box when dialogue is active,
        # replacing the floating center-screen window.
        self._render_message_console()

        if refresh:
            terminal.refresh()

    def _render_gui_sidebar(
        self,
        player_ent: int | None,
        player_x: int,
        player_y: int,
        current_z: int,
        active_viewshed: Viewshed | None,
    ) -> None:
        """Render the GUI Sidebar on the top-right (35x30) with player stats, hotbar, and location."""
        terminal.layer(2)

        sidebar_x = self.camera.viewport_width  # 85
        sidebar_w = self.screen_width - sidebar_x  # 35
        sidebar_h = self.camera.viewport_height  # 30

        # Clear sidebar background
        terminal.color("black")
        for r in range(sidebar_h):
            terminal.puts(sidebar_x, r, " " * sidebar_w)

        # Draw framing border
        terminal.color("gray")
        header = "+-[[ CHARACTER INFO ]]"
        terminal.puts(sidebar_x, 0, header + "-" * max(0, sidebar_w - len(header) - 1) + "+")
        for r in range(1, sidebar_h - 1):
            terminal.puts(sidebar_x, r, "|")
            terminal.puts(self.screen_width - 1, r, "|")
        terminal.puts(sidebar_x, sidebar_h - 1, "+" + "-" * (sidebar_w - 2) + "+")

        # Player Name
        player_name = "Player"
        if player_ent is not None and esper.has_component(player_ent, Name):
            player_name = esper.component_for_entity(player_ent, Name).name

        terminal.color("white")
        terminal.puts(sidebar_x + 2, 1, f"Name:     {player_name[:20]}")

        # HP (Fighter)
        hp_str = "100/100"
        if player_ent is not None and esper.has_component(player_ent, Fighter):
            fighter = esper.component_for_entity(player_ent, Fighter)
            hp_str = f"{fighter.hp}/{fighter.max_hp}"

        terminal.color("light red")
        terminal.puts(sidebar_x + 2, 2, f"HP:       {hp_str}")

        # Energy Level (Energy)
        energy_str = "100/100"
        if player_ent is not None and esper.has_component(player_ent, Energy):
            energy = esper.component_for_entity(player_ent, Energy)
            energy_str = f"{energy.current}/{energy.max_energy}"

        terminal.color("light green")
        terminal.puts(sidebar_x + 2, 3, f"Energy:   {energy_str}")

        # Current Z-Level & Map Coordinates
        terminal.color("white")
        terminal.puts(sidebar_x + 2, 4, f"Z-Level:  {current_z}")
        terminal.puts(sidebar_x + 2, 5, f"Pos:      ({player_x}, {player_y})")

        # Hotbar Divider
        terminal.color("gray")
        hotbar_hdr = "+-[[ HOTBAR (1-5) ]]"
        terminal.puts(sidebar_x, 7, hotbar_hdr + "-" * max(0, sidebar_w - len(hotbar_hdr) - 1) + "+")

        # Equipped Skills list (Hotbar 1-5)
        # Using [[ to properly escape brackets in BearLibTerminal
        skills = []
        if player_ent is not None and esper.has_component(player_ent, SkillBar):
            sbar = esper.component_for_entity(player_ent, SkillBar)
            skills = sbar.skills

        for slot in range(1, 6):
            slot_y = 8 + (slot - 1)
            if slot - 1 < len(skills):
                sk = skills[slot - 1]
                is_targeting_this = (
                    self.state_manager is not None
                    and self.state_manager.state == GameState.TARGETING
                    and getattr(self.state_manager, "targeting_skill", None) is not None
                    and self.state_manager.targeting_skill.name.lower() == sk.name.lower()
                )
                if is_targeting_this:
                    terminal.color("light green")
                    terminal.puts(sidebar_x + 2, slot_y, f"[[{slot}]] {sk.name} (Aiming)")
                else:
                    terminal.color("yellow")
                    terminal.puts(sidebar_x + 2, slot_y, f"[[{slot}]] {sk.name} ({sk.energy_cost} En)")
            else:
                terminal.color("dark gray")
                terminal.puts(sidebar_x + 2, slot_y, f"[[{slot}]] ---")

        # Location Divider
        terminal.color("gray")
        loc_hdr = "+-[[ LOCATION ]]"
        terminal.puts(sidebar_x, 14, loc_hdr + "-" * max(0, sidebar_w - len(loc_hdr) - 1) + "+")

        # Location / Room details
        room_name = (
            f"Room {active_viewshed.current_room_id}"
            if active_viewshed and active_viewshed.current_room_id
            else "Exterior"
        )
        bldg_name = (
            str(getattr(active_viewshed, "active_building_id", "Wilderness"))
            if active_viewshed and getattr(active_viewshed, "active_building_id", None)
            else "Wilderness"
        )

        terminal.color("light cyan")
        terminal.puts(sidebar_x + 2, 15, f"Building: {bldg_name[:20]}")
        terminal.puts(sidebar_x + 2, 16, f"Zone:     {room_name[:20]}")

        # Controls Divider
        terminal.color("gray")
        ctrl_hdr = "+-[[ CONTROLS ]]"
        terminal.puts(sidebar_x, 18, ctrl_hdr + "-" * max(0, sidebar_w - len(ctrl_hdr) - 1) + "+")

        # Keybind reminders properly escaped with [[ for BearLibTerminal
        terminal.color("white")
        terminal.puts(sidebar_x + 2, 20, "[[Arrows]] Move")
        terminal.puts(sidebar_x + 2, 21, "[[.]]      Wait / Pass Turn")
        terminal.puts(sidebar_x + 2, 22, "[[1-5]]    Use Skill")
        terminal.puts(sidebar_x + 2, 23, "[[E]]      Door Interact")
        terminal.puts(sidebar_x + 2, 24, "[[M]]      Regional Map")
        terminal.puts(sidebar_x + 2, 25, "[[G]]      Get / Pick Up")
        terminal.puts(sidebar_x + 2, 26, "[[I]]      Inventory")
        terminal.puts(sidebar_x + 2, 27, "[[C]]      Character Sheet")

    def _render_message_console(self) -> None:
        """Render the bottom Message Console (120x10), acting as either Message Log or Dialogue Box."""
        terminal.layer(2)

        console_y = self.camera.viewport_height  # 30
        console_w = self.screen_width  # 120
        console_h = self.screen_height - console_y  # 10

        # Check if an active NPC dialogue is open
        dialogue = (
            self.interaction_system.get_active_dialogue()
            if self.interaction_system is not None and self.interaction_system.has_active_dialogue()
            else None
        )

        if dialogue is not None:
            # --- DIALOGUE BOX MODE ---
            # Clear console area
            terminal.color("black")
            for r in range(console_h):
                terminal.puts(0, console_y + r, " " * console_w)

            # Framing border
            terminal.color("cyan")
            pers_name = (
                dialogue.personality.name
                if hasattr(dialogue.personality, "name")
                else str(dialogue.personality)
            )
            title = f"+-[[ DIALOGUE: {dialogue.speaker_name} | Mood: {dialogue.mood}/100 | {pers_name} ]]"
            terminal.puts(0, console_y, title + "-" * max(0, console_w - len(title) - 1) + "+")
            for r in range(1, console_h - 1):
                terminal.puts(0, console_y + r, "|")
                terminal.puts(console_w - 1, console_y + r, "|")
            terminal.puts(0, self.screen_height - 1, "+" + "-" * (console_w - 2) + "+")

            # Dialogue content
            max_line_len = console_w - 6  # 114 chars
            dialogue_lines: list[tuple[str, str]] = []

            # Greeting line in cyan
            if dialogue.greeting:
                dialogue_lines.append((f'"{dialogue.greeting}"', "light cyan"))

            # Body lines in white (or light red if refused)
            body_color = "white" if not dialogue.refused else "light red"
            if dialogue.body:
                for wrapped in textwrap.wrap(dialogue.body, width=max_line_len):
                    dialogue_lines.append((wrapped, body_color))

            # Available lines: console_y + 1 (31) to console_y + 6 (36)
            for idx, (text_line, color) in enumerate(dialogue_lines[:6]):
                terminal.color(color)
                # Escape any brackets in dialogue text
                escaped = text_line.replace("[", "[[").replace("]", "]]")
                terminal.puts(3, console_y + 2 + idx, escaped)

            # Prompt line at console_y + 8 (38)
            terminal.color("yellow")
            terminal.puts(3, console_y + 8, "[[ Press SPACE or ESC to close dialogue ]]")

        else:
            # --- NORMAL MESSAGE LOG MODE ---
            # Clear console area
            terminal.color("black")
            for r in range(console_h):
                terminal.puts(0, console_y + r, " " * console_w)

            # Framing border
            terminal.color("gray")
            hdr = "+-[[ MESSAGE LOG ]]"
            terminal.puts(0, console_y, hdr + "-" * max(0, console_w - len(hdr) - 1) + "+")
            for r in range(1, console_h - 1):
                terminal.puts(0, console_y + r, "|")
                terminal.puts(console_w - 1, console_y + r, "|")
            terminal.puts(0, self.screen_height - 1, "+" + "-" * (console_w - 2) + "+")

            # Retrieve up to 8 most recent messages
            recent = self.message_log.get_recent(8) if self.message_log else []
            max_display_lines = 8

            # Push older messages up as new ones arrive
            start_offset = max_display_lines - len(recent)
            for i, msg in enumerate(recent):
                line_y = console_y + 1 + start_offset + i
                # Color gradient: newest message is bright yellow, recent is white, older are dimmed gray
                if i == len(recent) - 1:
                    terminal.color("yellow")
                elif i >= len(recent) - 3:
                    terminal.color("white")
                else:
                    terminal.color("gray")

                # Escape square brackets in messages so BLT doesn't parse them as tags
                escaped_msg = msg.replace("[", "[[").replace("]", "]]")
                trimmed_msg = escaped_msg[: console_w - 6]
                terminal.puts(2, line_y, f"> {trimmed_msg}")

    def _render_dialogue_window(self, dialogue=None) -> None:
        """Helper for dialogue rendering; forwards to the message console dialogue box."""
        self._render_message_console()

    def _render_inventory_screen(self) -> None:
        """Render the inventory screen taking over the 85x30 map viewport, alongside GUI and Console."""
        terminal.clear()

        # Find current player coordinates, active Z-level, and Viewshed for sidebar
        player_x = 0
        player_y = 0
        current_z = 0
        player_ent: int | None = None
        active_viewshed: Viewshed | None = None

        for _ent, (pos, _player) in esper.get_components(Position, Player):
            player_ent = _ent
            player_x = pos.x
            player_y = pos.y
            current_z = pos.z
            if esper.has_component(_ent, Viewshed):
                active_viewshed = esper.component_for_entity(_ent, Viewshed)
            break

        # 1. Inventory View takes over the 85x30 Map Viewport area (Layer 0)
        self._render_inventory_view(player_ent)

        # 2. GUI Sidebar (Top Right, 35x30, Layer 2)
        self._render_gui_sidebar(player_ent, player_x, player_y, current_z, active_viewshed)

        # 3. Message Console (Bottom, 120x10, Layer 2)
        self._render_message_console()

        terminal.refresh()

    def _render_inventory_view(self, player_ent: int | None = None) -> None:
        """Render the Inventory panel taking over the 85x30 Map Viewport area."""
        terminal.layer(0)
        map_w = self.camera.viewport_width   # 85
        map_h = self.camera.viewport_height  # 30

        # Framing border around the 85x30 map viewport
        terminal.color("cyan")
        hdr_tag = "+-[[ INVENTORY ]]"
        hdr_vis = "+-[ INVENTORY ]"
        terminal.puts(0, 0, hdr_tag + "-" * max(0, map_w - len(hdr_vis) - 1) + "+")
        for y in range(1, map_h - 1):
            terminal.puts(0, y, "|")
            terminal.puts(map_w - 1, y, "|")
        terminal.puts(0, map_h - 1, "+" + "-" * (map_w - 2) + "+")

        # Find player's inventory
        inv: Inventory | None = None
        if player_ent is not None and esper.has_component(player_ent, Inventory):
            inv = esper.component_for_entity(player_ent, Inventory)
        else:
            for _ent, (_player, p_inv) in esper.get_components(Player, Inventory):
                inv = p_inv
                break

        if inv is None:
            terminal.color("dark gray")
            terminal.puts(4, 3, "(No inventory component found)")
            terminal.color("yellow")
            terminal.puts(2, map_h - 2, "[[ ESC ]] or [[ I ]] Return to Map View")
            return

        # Calculate inventory statistics
        total_items = len(inv.items)
        total_weight = 0.0
        for item_ent in inv.items:
            if esper.has_component(item_ent, Item):
                total_weight += esper.component_for_entity(item_ent, Item).weight

        # Summary Header
        terminal.color("white")
        terminal.puts(
            2,
            1,
            f"Capacity: {total_items} / {inv.max_capacity} items   |   Total Weight: {total_weight:.1f} kg",
        )
        terminal.color("gray")
        terminal.puts(1, 2, "-" * (map_w - 2))

        # Column Headers
        terminal.color("light cyan")
        terminal.puts(2, 3, "Slot  Item Name                            Weight    Description")
        terminal.color("dark gray")
        terminal.puts(1, 4, "-" * (map_w - 2))

        # Items listing
        if not inv.items:
            terminal.color("dark gray")
            terminal.puts(4, 7, "(Your inventory is currently empty)")
        else:
            max_display_items = map_h - 8  # 22 slots (rows 5 to 26)
            for idx, item_ent in enumerate(inv.items[:max_display_items]):
                row_y = 5 + idx
                letter = chr(ord("a") + idx) if idx < 26 else str(idx + 1)

                item_name = f"Item #{item_ent}"
                weight = 0.0
                desc = ""
                slot_info = ""
                if esper.has_component(item_ent, Item):
                    item_comp = esper.component_for_entity(item_ent, Item)
                    item_name = item_comp.name
                    weight = item_comp.weight
                    desc = item_comp.description
                    if item_comp.slot is not None:
                        slot_info = f"[{item_comp.slot.value}]"
                elif esper.has_component(item_ent, Name):
                    item_name = esper.component_for_entity(item_ent, Name).name

                if esper.has_component(item_ent, Equippable):
                    eq_comp = esper.component_for_entity(item_ent, Equippable)
                    slot_info = f"[{eq_comp.slot.value}]"

                terminal.color("yellow")
                terminal.puts(2, row_y, f"[[{letter}]]")

                terminal.color("white")
                full_name = f"{item_name} {slot_info}".strip()
                terminal.puts(8, row_y, full_name[:34])

                terminal.color("gray")
                weight_str = f"{weight:.1f} kg" if weight else "--"
                terminal.puts(45, row_y, f"{weight_str:>7}")

                terminal.color("light gray")
                desc_escaped = desc.replace("[", "[[").replace("]", "]]")
                terminal.puts(55, row_y, desc_escaped[:27])

            if total_items > max_display_items:
                terminal.color("yellow")
                terminal.puts(
                    2,
                    27,
                    f"... and {total_items - max_display_items} more items",
                )

        # Footer Prompt
        terminal.color("yellow")
        terminal.puts(2, map_h - 2, "[[a-z]] Equip Gear to Slot   |   [[ESC]] or [[I]] Return to Map View")

    def _render_inventory_overlay(self) -> None:
        """Backward-compatible helper redirecting to inventory view rendering."""
        self._render_inventory_view(None)

    def _render_character_screen(self) -> None:
        """Render the full Character Screen across the 120x40 window."""
        terminal.clear()

        player_ent: int | None = None
        for _ent, (_player,) in esper.get_components(Player):
            player_ent = _ent
            break

        self._render_character_view(player_ent, width=self.screen_width, height=self.screen_height)
        terminal.refresh()

    def _render_character_view(
        self,
        player_ent: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """Render the 'Shakes & Fidget' style ASCII Paper Doll (5x5 slot art) and 3-Tier Stat Grid."""
        terminal.layer(0)
        scr_w = width if width is not None else self.screen_width
        scr_h = height if height is not None else self.screen_height

        # Framing border
        terminal.color("cyan")
        hdr_tag = "+-[[ CHARACTER SHEET & PAPER DOLL ]]"
        hdr_vis = "+-[ CHARACTER SHEET & PAPER DOLL ]"
        terminal.puts(0, 0, hdr_tag + "-" * max(0, scr_w - len(hdr_vis) - 1) + "+")
        for y in range(1, scr_h - 1):
            terminal.puts(0, y, "|")
            terminal.puts(scr_w - 1, y, "|")
        terminal.puts(0, scr_h - 1, "+" + "-" * (scr_w - 2) + "+")

        # Fetch player Equipment, Stats, and Inventory
        equipment: Equipment | None = None
        stats: Stats | None = None
        inv: Inventory | None = None

        if player_ent is not None:
            if esper.has_component(player_ent, Equipment):
                equipment = esper.component_for_entity(player_ent, Equipment)
            if esper.has_component(player_ent, Stats):
                stats = esper.component_for_entity(player_ent, Stats)
            if esper.has_component(player_ent, Inventory):
                inv = esper.component_for_entity(player_ent, Inventory)
        else:
            for _ent, (_player, p_eq, p_stats) in esper.get_components(Player, Equipment, Stats):
                player_ent = _ent
                equipment = p_eq
                stats = p_stats
                if esper.has_component(_ent, Inventory):
                    inv = esper.component_for_entity(_ent, Inventory)
                break

        # Helper to get equipped item info and art
        def get_slot_info(slot: EquipmentSlot) -> tuple[int | None, str, str, str, list[str]]:
            """Return (item_ent, name_str, bonus_str, color, art_lines)."""
            item_ent = equipment.get_equipped(slot) if equipment else None
            if item_ent is None:
                return None, "[ Empty ]", "", "dark gray", EMPTY_SLOT_ART

            name_str = f"Item #{item_ent}"
            bonus_str = ""
            color = SLOT_DEFAULT_COLORS.get(slot, "white")

            if esper.has_component(item_ent, Renderable):
                r_color = esper.component_for_entity(item_ent, Renderable).color
                if r_color:
                    color = r_color

            if esper.has_component(item_ent, Item):
                it = esper.component_for_entity(item_ent, Item)
                name_str = it.name
                if it.stat_bonuses:
                    parts = [f"+{v} {k.upper()}" for k, v in it.stat_bonuses.items()]
                    bonus_str = f"({', '.join(parts)})"
            elif esper.has_component(item_ent, Name):
                name_str = esper.component_for_entity(item_ent, Name).name

            if esper.has_component(item_ent, Equippable):
                eq = esper.component_for_entity(item_ent, Equippable)
                if eq.stat_bonuses and not bonus_str:
                    parts = [f"+{v} {k.upper()}" for k, v in eq.stat_bonuses.items()]
                    bonus_str = f"({', '.join(parts)})"

            art = SLOT_ART_PRESETS.get(slot, EMPTY_SLOT_ART)
            return item_ent, name_str, bonus_str, color, art

        def render_slot_widget(slot: EquipmentSlot, label: str, box_x: int, text_x: int, y_pos: int) -> None:
            item_ent, iname, ibonus, color, art_lines = get_slot_info(slot)
            is_empty = item_ent is None

            # 1. Render 5x5 ASCII Box Art
            terminal.color(color if not is_empty else "dark gray")
            for r_idx, art_line in enumerate(art_lines):
                escaped_art = art_line.replace("[", "[[").replace("]", "]]")
                terminal.puts(box_x, y_pos + r_idx, escaped_art)

            # 2. Render Slot Label and Details next to the box
            # Line 0: Slot Label
            terminal.color("light cyan" if not is_empty else "gray")
            terminal.puts(text_x, y_pos, label.replace("[", "[[").replace("]", "]]"))

            # Line 1: Item Name
            terminal.color("white" if not is_empty else "dark gray")
            terminal.puts(text_x, y_pos + 1, iname[:35])

            # Line 2: Stat Bonuses
            if ibonus:
                terminal.color("light green")
                terminal.puts(text_x, y_pos + 2, ibonus[:35])
            else:
                terminal.color("dark gray")
                terminal.puts(text_x, y_pos + 2, "--" if is_empty else "")

        # ---------------------------------------------------------
        # TOP SECTION: Paper Doll with 16x16 ASCII Portrait in Center
        # ---------------------------------------------------------
        # 6 Armor Slots on Left: Head, Cape, Torso, Glove, Legs, Boots
        armor_slots = [
            ("[ Head ]", EquipmentSlot.HEAD),
            ("[ Cape ]", EquipmentSlot.CAPE),
            ("[ Torso]", EquipmentSlot.TORSO),
            ("[ Glove]", EquipmentSlot.GLOVES),
            ("[ Legs ]", EquipmentSlot.LEGS),
            ("[ Boots]", EquipmentSlot.BOOTS),
        ]
        left_box_x = 3
        left_text_x = 10
        left_y_coords = [1, 6, 11, 16, 21, 26]

        for (label, slot), y_pos in zip(armor_slots, left_y_coords):
            render_slot_widget(slot, label, left_box_x, left_text_x, y_pos)

        # Portrait (x: 52..67, y: 8..23)
        portrait_x = (scr_w - 16) // 2  # 52
        portrait_y = 8
        terminal.color("cyan")
        terminal.puts(portrait_x, 6, "+-- PORTRAIT --+")
        for idx, line in enumerate(PORTRAIT_16X16):
            escaped_line = line.replace("[", "[[").replace("]", "]]")
            terminal.color("light cyan")
            terminal.puts(portrait_x, portrait_y + idx, escaped_line)
        terminal.color("cyan")
        terminal.puts(portrait_x, portrait_y + 16, "+--------------+")

        # 5 Trinket Slots on Right: Hair_Orn, Necklace, Belt, Wristband, Ring
        trinket_slots = [
            ("[ Hair_Orn ]", EquipmentSlot.HAIR_ORNAMENT),
            ("[ Necklace ]", EquipmentSlot.NECKLACE),
            ("[ Belt     ]", EquipmentSlot.BELT),
            ("[ Wristband]", EquipmentSlot.WRISTBAND),
            ("[ Ring     ]", EquipmentSlot.RING),
        ]
        right_box_x = 72
        right_text_x = 79
        right_y_coords = [1, 6, 11, 16, 21]

        for (label, slot), y_pos in zip(trinket_slots, right_y_coords):
            render_slot_widget(slot, label, right_box_x, right_text_x, y_pos)

        # 6th slot on right (reserved empty slot as in wireframe)
        terminal.color("dark gray")
        terminal.puts(right_text_x, 28, "[  Reserved Slot  ]")

        # Section Divider
        terminal.color("cyan")
        stats_hdr = "+-[[ 3-TIER STATS SYSTEM ]]"
        stats_vis = "+-[ 3-TIER STATS SYSTEM ]"
        terminal.puts(0, 31, stats_hdr + "-" * max(0, scr_w - len(stats_vis) - 1) + "+")

        # ---------------------------------------------------------
        # BOTTOM SECTION: 3-Tier Stats Grid (Exact Layout Wireframe)
        # Base Stats    | D&D Substats       | Battle Stats
        # Level: 1      | STR: 10  INT: 10   | HP: 50  Crit: 5%
        # XP: 0/100     | DEX: 10  WIS: 10   | Dmg: 10 Def: 10
        #               | CON: 10  CHA: 10   | Spd: 10 Eva: 5%
        # ---------------------------------------------------------
        col1_x = 4
        div1_x = 25
        col2_x = 30
        div2_x = 70
        col3_x = 75

        # Row 32: Column Headers
        terminal.color("yellow")
        terminal.puts(col1_x, 32, "Base Stats")
        terminal.color("gray")
        terminal.puts(div1_x, 32, "|")
        terminal.color("yellow")
        terminal.puts(col2_x, 32, "D&D Substats")
        terminal.color("gray")
        terminal.puts(div2_x, 32, "|")
        terminal.color("yellow")
        terminal.puts(col3_x, 32, "Battle Stats")

        # Stats values
        if stats is not None:
            # Row 33 (Level / STR, INT / HP, Crit)
            terminal.color("white")
            terminal.puts(col1_x, 33, f"Level: {stats.level}")
            terminal.color("gray")
            terminal.puts(div1_x, 33, "|")
            terminal.color("white")
            terminal.puts(col2_x, 33, f"STR: {stats.total_strength():<2}   INT: {stats.total_intelligence():<2}")
            terminal.color("gray")
            terminal.puts(div2_x, 33, "|")
            terminal.color("white")
            terminal.puts(col3_x, 33, f"HP:   {stats.max_hp:<3}   Crit: {stats.crit_rate:.1f}%")

            # Row 34 (XP / DEX, WIS / Dmg, Def)
            terminal.color("white")
            terminal.puts(col1_x, 34, f"XP: {stats.xp}/{stats.max_xp}")
            terminal.color("gray")
            terminal.puts(div1_x, 34, "|")
            terminal.color("white")
            terminal.puts(col2_x, 34, f"DEX: {stats.total_dexterity():<2}   WIS: {stats.total_wisdom():<2}")
            terminal.color("gray")
            terminal.puts(div2_x, 34, "|")
            terminal.color("white")
            terminal.puts(col3_x, 34, f"Dmg:  {stats.damage:<3}   Def:  {stats.defense:<2}")

            # Row 35 (CON, CHA / Spd, Eva)
            terminal.color("gray")
            terminal.puts(div1_x, 35, "|")
            terminal.color("white")
            terminal.puts(col2_x, 35, f"CON: {stats.total_constitution():<2}   CHA: {stats.total_charisma():<2}")
            terminal.color("gray")
            terminal.puts(div2_x, 35, "|")
            terminal.color("white")
            terminal.puts(col3_x, 35, f"Spd:  {stats.speed:<3}   Eva:  {stats.evasion:.1f}%")
        else:
            terminal.color("dark gray")
            terminal.puts(col1_x, 33, "(No stats component found)")

        # Divider line
        terminal.color("gray")
        terminal.puts(1, 36, "-" * (scr_w - 2))

        # Row 37: Info line
        terminal.color("light green")
        terminal.puts(4, 37, "Gear is equipped via Inventory [[I]]. Equipping gear dynamically recalculates Battle Stats.")

        # Row 38: Footer prompt
        terminal.color("yellow")
        terminal.puts(4, 38, "[[ESC]] or [[C]] Return to Map View   |   [[I]] Open Inventory (Equip Gear)")
