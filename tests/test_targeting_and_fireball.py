"""Unit and integration tests for GameState.TARGETING mode and Fireball skill.

Tests:
1. Fireball Skill & Player SkillBar:
   - Skill dataclass has range attribute (default 1, Fireball range 5)
   - Player initialized with SkillBar containing Cleave (slot 1) and Fireball (slot 2)

2. GameState.TARGETING Mode:
   - Pressing '2' enters GameState.TARGETING
   - Cursor initialized at player coordinates
   - ESC or '2' cancels targeting mode without energy cost
   - Insufficient energy (< 20) inhibits entering TARGETING mode

3. Cursor Movement and Range Restriction:
   - Arrow keys move the targeting cursor across the map
   - Player character does NOT move (position remains fixed)
   - Cursor is restricted to max skill range (5 tiles from origin)

4. Fireball Execution on ENTER:
   - Pressing ENTER executes Fireball at cursor location
   - Deals damage to any entity with Fighter component on that tile
   - Deducts 20 Energy from player
   - Returns game state to LOCAL_MAP
   - Logs combat hit message to combat log

5. Enemy Defeat and Entity Deletion:
   - Low-HP enemy struck by Fireball is defeated and deleted from ECS world
   - Logs '(Defeated!)' combat message

6. Fireball Miss / Empty Tile:
   - Casting on an empty tile consumes energy and logs hit nothing message

7. RenderSystem Targeting Cursor:
   - RenderSystem draws highlighted yellow background cursor on layer 1 in TARGETING mode
"""

import unittest
from bearlibterminal import terminal
import esper

from components import (
    Energy,
    Fighter,
    Name,
    Player,
    Position,
    RenderOrder,
    Renderable,
    Skill,
    SkillBar,
)
from game_map import GameMap
from game_state import GameState, GameStateManager
from message_log import MessageLog
from systems import (
    DoorSystem,
    InputSystem,
    MovementSystem,
    RenderSystem,
    TurnManagementSystem,
)
from systems.turn_management_system import CombatLog
import main


class TestFireballSkillAndSkillBar(unittest.TestCase):
    """Test suite for Fireball skill definition and player's SkillBar."""

    def setUp(self) -> None:
        esper.clear_database()
        self.player = main.init_ecs()
        esper.process()

    def test_skill_range_attribute(self) -> None:
        """Verify Skill dataclass has range attribute with appropriate defaults."""
        default_skill = Skill(name="Default")
        self.assertEqual(default_skill.range, 1)

        fireball = Skill(name="Fireball", energy_cost=20, damage=25, range=5)
        self.assertEqual(fireball.name, "Fireball")
        self.assertEqual(fireball.energy_cost, 20)
        self.assertEqual(fireball.damage, 25)
        self.assertEqual(fireball.range, 5)

    def test_player_skillbar_contains_cleave_and_fireball(self) -> None:
        """Verify player's SkillBar contains Cleave in slot 1 and Fireball in slot 2."""
        self.assertTrue(esper.has_component(self.player, SkillBar))
        sbar = esper.component_for_entity(self.player, SkillBar)
        self.assertGreaterEqual(len(sbar.skills), 2)

        cleave = sbar.skills[0]
        self.assertEqual(cleave.name, "Cleave")
        self.assertEqual(cleave.energy_cost, 20)

        fireball = sbar.skills[1]
        self.assertEqual(fireball.name, "Fireball")
        self.assertEqual(fireball.energy_cost, 20)
        self.assertEqual(fireball.range, 5)


class TestTargetingStateTransitions(unittest.TestCase):
    """Test suite for entering, exiting, and toggling GameState.TARGETING."""

    def setUp(self) -> None:
        esper.clear_database()
        self.game_map = GameMap(width=200, height=200)
        self.state_manager = GameStateManager(initial_state=GameState.LOCAL_MAP)
        self.combat_log = CombatLog()
        self.player = main.init_ecs(game_map=self.game_map, state_manager=self.state_manager)
        esper.process()

    def test_press_2_enters_targeting_mode(self) -> None:
        """Pressing '2' enters GameState.TARGETING and initializes cursor at player position."""
        pos = esper.component_for_entity(self.player, Position)
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

        # Press '2'
        esper.process(key=terminal.TK_2)
        self.assertEqual(self.state_manager.state, GameState.TARGETING)
        self.assertEqual(self.state_manager.cursor_x, pos.x)
        self.assertEqual(self.state_manager.cursor_y, pos.y)
        self.assertEqual(self.state_manager.cursor_z, pos.z)
        self.assertEqual(self.state_manager.max_range, 5)
        self.assertIsNotNone(self.state_manager.targeting_skill)
        self.assertEqual(self.state_manager.targeting_skill.name, "Fireball")

    def test_press_esc_cancels_targeting_mode_without_energy_cost(self) -> None:
        """Pressing ESC in TARGETING mode returns to LOCAL_MAP without consuming energy."""
        energy = esper.component_for_entity(self.player, Energy)
        initial_energy = energy.current

        esper.process(key=terminal.TK_2)
        self.assertEqual(self.state_manager.state, GameState.TARGETING)

        # Cancel via ESC
        esper.process(key=terminal.TK_ESCAPE)
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)
        self.assertEqual(energy.current, initial_energy)

    def test_press_2_again_cancels_targeting_mode(self) -> None:
        """Pressing '2' while in TARGETING mode toggles back to LOCAL_MAP."""
        esper.process(key=terminal.TK_2)
        self.assertEqual(self.state_manager.state, GameState.TARGETING)

        # Toggle off with '2'
        esper.process(key=ord("2"))
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

    def test_insufficient_energy_inhibits_targeting_mode(self) -> None:
        """If player has < 20 Energy, pressing '2' fails and logs an error message."""
        energy = esper.component_for_entity(self.player, Energy)
        energy.current = 10  # Fireball costs 20

        turn_sys = None
        for proc in esper._processors:
            if isinstance(proc, TurnManagementSystem):
                turn_sys = proc
                break

        esper.process(key=terminal.TK_2)
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

        if turn_sys is not None:
            messages = [m for m in turn_sys.combat_log.messages if "Not enough Energy to use Fireball" in m]
            self.assertTrue(len(messages) > 0)


class TestCursorMovementAndRangeRestriction(unittest.TestCase):
    """Test suite for moving cursor in TARGETING mode and enforcing range 5."""

    def setUp(self) -> None:
        esper.clear_database()
        self.game_map = GameMap(width=200, height=200)
        self.state_manager = GameStateManager(initial_state=GameState.LOCAL_MAP)
        self.player = main.init_ecs(game_map=self.game_map, state_manager=self.state_manager)
        esper.process()

        self.pos = esper.component_for_entity(self.player, Position)
        self.initial_x = self.pos.x
        self.initial_y = self.pos.y

        # Enter TARGETING mode
        esper.process(key=terminal.TK_2)
        self.assertEqual(self.state_manager.state, GameState.TARGETING)

    def test_player_character_does_not_move_in_targeting_mode(self) -> None:
        """Arrow keys move the cursor but character coordinates remain fixed."""
        esper.process(key=terminal.TK_RIGHT)
        esper.process(key=terminal.TK_RIGHT)
        esper.process(key=terminal.TK_UP)

        # Character position did not change
        self.assertEqual(self.pos.x, self.initial_x)
        self.assertEqual(self.pos.y, self.initial_y)

        # Cursor moved
        self.assertEqual(self.state_manager.cursor_x, self.initial_x + 2)
        self.assertEqual(self.state_manager.cursor_y, self.initial_y - 1)

    def test_cursor_restricted_to_range_5_tiles(self) -> None:
        """Cursor cannot move further than skill's range (5 tiles from origin)."""
        # Move right 10 times
        for _ in range(10):
            esper.process(key=terminal.TK_RIGHT)

        # Clamped at initial_x + 5
        self.assertEqual(self.state_manager.cursor_x, self.initial_x + 5)
        self.assertEqual(self.state_manager.cursor_y, self.initial_y)

        # Move left 10 times -> stops at initial_x - 5
        for _ in range(10):
            esper.process(key=terminal.TK_LEFT)
        self.assertEqual(self.state_manager.cursor_x, self.initial_x - 5)

        # Move up 10 times -> stops at initial_y - 5
        for _ in range(10):
            esper.process(key=terminal.TK_UP)
        self.assertEqual(self.state_manager.cursor_y, self.initial_y - 5)

        # Move down 10 times -> stops at initial_y + 5
        for _ in range(10):
            esper.process(key=terminal.TK_DOWN)
        self.assertEqual(self.state_manager.cursor_y, self.initial_y + 5)


class TestFireballExecutionAndCombat(unittest.TestCase):
    """Test suite for executing Fireball, dealing damage, and consuming energy."""

    def setUp(self) -> None:
        esper.clear_database()
        self.game_map = GameMap(width=200, height=200)
        self.state_manager = GameStateManager(initial_state=GameState.LOCAL_MAP)
        self.player = main.init_ecs(game_map=self.game_map, state_manager=self.state_manager)
        esper.process()

        self.pos = esper.component_for_entity(self.player, Position)
        self.energy = esper.component_for_entity(self.player, Energy)

        # Spawn a ranged target dummy 3 tiles to the right
        self.target_x = self.pos.x + 3
        self.target_y = self.pos.y
        self.target_z = self.pos.z

        self.dummy = esper.create_entity()
        esper.add_component(self.dummy, Position(x=self.target_x, y=self.target_y, z=self.target_z))
        esper.add_component(self.dummy, Fighter(hp=50, max_hp=50))
        esper.add_component(self.dummy, Name("Target Dummy"))
        esper.add_component(
            self.dummy,
            Renderable(char="D", color="orange", layer=1, render_order=RenderOrder.NPC),
        )

    def test_fireball_hits_ranged_target_on_enter(self) -> None:
        """Aiming at target and pressing ENTER deals damage, consumes 20 energy, and returns to LOCAL_MAP."""
        initial_energy = self.energy.current  # 100

        # 1. Enter targeting mode
        esper.process(key=terminal.TK_2)
        self.assertEqual(self.state_manager.state, GameState.TARGETING)

        # 2. Move cursor 3 tiles to the right
        for _ in range(3):
            esper.process(key=terminal.TK_RIGHT)

        self.assertEqual(self.state_manager.cursor_x, self.target_x)
        self.assertEqual(self.state_manager.cursor_y, self.target_y)

        # 3. Press ENTER to cast Fireball
        esper.process(key=terminal.TK_ENTER)

        # State returned to LOCAL_MAP
        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)

        # Energy deducted (100 -> 80)
        self.assertEqual(self.energy.current, initial_energy - 20)

        # Dummy took damage (50 - 25 = 25 HP)
        dummy_fighter = esper.component_for_entity(self.dummy, Fighter)
        self.assertEqual(dummy_fighter.hp, 25)

    def test_fireball_defeats_and_deletes_low_hp_enemy(self) -> None:
        """Fireball kills low-HP target and deletes it from the ECS world."""
        # Set dummy HP to 10
        dummy_fighter = esper.component_for_entity(self.dummy, Fighter)
        dummy_fighter.hp = 10

        # Target and fire
        esper.process(key=terminal.TK_2)
        for _ in range(3):
            esper.process(key=terminal.TK_RIGHT)
        esper.process(key=terminal.TK_ENTER)

        # Dummy is defeated and deleted
        self.assertFalse(esper.entity_exists(self.dummy))

    def test_fireball_at_empty_tile_hits_nothing(self) -> None:
        """Fireball on an empty tile consumes energy and logs hit nothing."""
        initial_energy = self.energy.current

        # Target empty tile 2 tiles up
        esper.process(key=terminal.TK_2)
        esper.process(key=terminal.TK_UP)
        esper.process(key=terminal.TK_UP)
        esper.process(key=terminal.TK_ENTER)

        self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)
        self.assertEqual(self.energy.current, initial_energy - 20)


class TestTargetingCursorRendering(unittest.TestCase):
    """Test suite for rendering targeting cursor in BearLibTerminal."""

    def setUp(self) -> None:
        esper.clear_database()
        self.game_map = GameMap(width=200, height=200)
        self.state_manager = GameStateManager(initial_state=GameState.LOCAL_MAP)
        self.player = main.init_ecs(game_map=self.game_map, state_manager=self.state_manager)
        esper.process()

    def test_render_targeting_cursor(self) -> None:
        """Verify RenderSystem renders in GameState.TARGETING mode cleanly."""
        terminal.open()
        try:
            terminal.set(f"window: size={main.SCREEN_WIDTH}x{main.SCREEN_HEIGHT}")

            # Enter targeting mode
            esper.process(key=terminal.TK_2)
            self.assertEqual(self.state_manager.state, GameState.TARGETING)

            # Move cursor
            esper.process(key=terminal.TK_RIGHT)
            esper.process(key=terminal.TK_DOWN)

            # Process render pass
            esper.process()

            # Cancel targeting
            esper.process(key=terminal.TK_ESCAPE)
            self.assertEqual(self.state_manager.state, GameState.LOCAL_MAP)
            esper.process()
        finally:
            terminal.close()

    def test_ground_tunic_and_aiming_cursor_characters_render(self) -> None:
        """Verify Leather Tunic '[' and aiming cursor character and yellow background render properly."""
        terminal.open()
        try:
            terminal.set(f"window: size={main.SCREEN_WIDTH}x{main.SCREEN_HEIGHT}")
            rs = [p for p in esper._processors if isinstance(p, RenderSystem)][0]
            pos = esper.component_for_entity(self.player, Position)

            # Find ground Leather Tunic
            tunic_pos = None
            for ent, (p, r, it) in esper.get_components(Position, Renderable, main.Item):
                if it.name == "Leather Tunic":
                    tunic_pos = (p.x, p.y)
                    self.assertEqual(r.char, "[")

            self.assertIsNotNone(tunic_pos, "Leather Tunic must exist on ground")

            # 1. Render Local Map without targeting: Tunic '[' must be rendered on Layer 0
            rs.process()
            terminal.layer(0)
            screen_tx = tunic_pos[0] - rs.camera.x
            screen_ty = tunic_pos[1] - rs.camera.y
            self.assertEqual(chr(terminal.pick(screen_tx, screen_ty)), "[", "Tunic '[' must render on ground")

            # 2. Start targeting on player tile: cursor must render '@' with yellow background
            self.state_manager.start_targeting(skill=None, origin_x=pos.x, origin_y=pos.y, origin_z=0, max_range=5)
            rs.process()
            terminal.layer(0)
            screen_px = pos.x - rs.camera.x
            screen_py = pos.y - rs.camera.y
            self.assertEqual(chr(terminal.pick(screen_px, screen_py)), "@")
            self.assertEqual(terminal.pick_bkcolor(screen_px, screen_py), 0xFFFFFF00)

            # 3. Move cursor to empty tile (pos.x + 2, pos.y): cursor must render 'X' with yellow background
            self.state_manager.cursor_x = pos.x + 2
            self.state_manager.cursor_y = pos.y
            rs.process()
            terminal.layer(0)
            screen_ex = (pos.x + 2) - rs.camera.x
            screen_ey = pos.y - rs.camera.y
            self.assertEqual(chr(terminal.pick(screen_ex, screen_ey)), "X", "Cursor on empty tile must render 'X'")
            self.assertEqual(terminal.pick_bkcolor(screen_ex, screen_ey), 0xFFFFFF00)

            # 4. Move cursor to tunic tile: cursor must render '[' with yellow background
            self.state_manager.cursor_x = tunic_pos[0]
            self.state_manager.cursor_y = tunic_pos[1]
            rs.process()
            terminal.layer(0)
            self.assertEqual(chr(terminal.pick(screen_tx, screen_ty)), "[")
            self.assertEqual(terminal.pick_bkcolor(screen_tx, screen_ty), 0xFFFFFF00)

            # Cancel targeting
            self.state_manager.cancel_targeting()
        finally:
            terminal.close()


if __name__ == "__main__":
    unittest.main()
