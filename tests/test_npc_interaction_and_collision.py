"""Unit and integration tests for:
1. Entity collision system (entities block movement and cannot occupy the same tile).
2. Global FactManager (stores global knowledge/events with unique IDs).
3. NPC ECS Components: Memory (set of Fact IDs), Mindset (mood 0-100), Personality (Enum).
4. InteractionSystem and bump-to-talk mechanic opening a dialogue text window instead of attacking.
5. Dialogue formatting function:
   - Mood > 50: Greets player and shares known Fact text flavored by Personality Enum.
   - Mood < 50: Complains and refuses to share Facts flavored by Personality Enum.
6. Dialogue window display and dismissal via SPACE / ESC.
"""

import unittest
from bearlibterminal import terminal
import esper

from components import (
    BlocksTile,
    Fighter,
    Memory,
    Mindset,
    Name,
    NPC,
    Personality,
    Player,
    Position,
    Renderable,
)
from facts import Fact, FactManager, global_fact_manager
from game_map import GameMap
from systems import (
    CombatLog,
    DoorSystem,
    InputSystem,
    InteractionSystem,
    MovementSystem,
    RenderSystem,
    TurnManagementSystem,
    format_npc_dialogue,
)
import main


class TestFactManager(unittest.TestCase):
    """Test suite for the global FactManager and Fact data objects."""

    def setUp(self) -> None:
        self.fm = FactManager()

    def test_register_and_retrieve_fact(self) -> None:
        """Registering a Fact by ID or object allows retrieval by ID."""
        fact = self.fm.register_fact(
            fact_id="fact_dragon_cave",
            text="A slumbering red dragon was spotted in the eastern crags.",
            subject="Red Dragon",
            location="Eastern Crags",
        )
        self.assertEqual(fact.id, "fact_dragon_cave")
        self.assertEqual(fact.subject, "Red Dragon")
        self.assertTrue(self.fm.has_fact("fact_dragon_cave"))

        retrieved = self.fm.get_fact("fact_dragon_cave")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.text, fact.text)

    def test_retrieving_unknown_fact_returns_none(self) -> None:
        """Querying an unregistered Fact ID returns None."""
        self.assertIsNone(self.fm.get_fact("fact_nonexistent"))
        self.assertFalse(self.fm.has_fact("fact_nonexistent"))

    def test_register_fact_instance_directly(self) -> None:
        """Registering a pre-instantiated Fact object."""
        f = Fact(id="fact_relic", text="The Sun Amulet was lost in the catacombs.")
        self.fm.register_fact(f)
        self.assertEqual(self.fm.get_fact("fact_relic"), f)


class TestDialogueFormatting(unittest.TestCase):
    """Test suite for the dialogue formatting function based on mood, personality, and facts."""

    def setUp(self) -> None:
        self.fm = FactManager()
        self.fm.register_fact(
            fact_id="fact_mines",
            text="The silver mines were abandoned due to strange tremors.",
            subject="Silver Mines",
        )

    def test_helpful_personality_good_mood_greets_and_shares_fact(self) -> None:
        """Mood > 50 with HELPFUL personality greets and shares the known Fact text."""
        mindset = Mindset(mood=75)
        memory = Memory(known_facts={"fact_mines"})

        dialogue = format_npc_dialogue(
            npc_name="Bari the Helpful",
            personality=Personality.HELPFUL,
            mindset=mindset,
            memory=memory,
            fact_manager=self.fm,
        )

        self.assertFalse(dialogue.refused)
        self.assertEqual(dialogue.personality, Personality.HELPFUL)
        self.assertIn("Hello there, traveler!", dialogue.greeting)
        self.assertIn("The silver mines were abandoned due to strange tremors.", dialogue.body)
        self.assertIsNotNone(dialogue.shared_fact)
        self.assertEqual(dialogue.shared_fact.id, "fact_mines")

    def test_cynical_personality_good_mood_greets_cynically_and_shares_fact(self) -> None:
        """Mood > 50 with CYNICAL personality shares the fact with cynical flavor."""
        mindset = Mindset(mood=65)
        memory = Memory(known_facts={"fact_mines"})

        dialogue = format_npc_dialogue(
            npc_name="Grimm the Cynic",
            personality=Personality.CYNICAL,
            mindset=mindset,
            memory=memory,
            fact_manager=self.fm,
        )

        self.assertFalse(dialogue.refused)
        self.assertEqual(dialogue.personality, Personality.CYNICAL)
        self.assertIn("What do you want?", dialogue.greeting)
        self.assertIn("The silver mines were abandoned due to strange tremors.", dialogue.body)
        self.assertIn("not that it will do you any good", dialogue.body)

    def test_helpful_personality_bad_mood_complains_and_refuses(self) -> None:
        """Mood < 50 with HELPFUL personality complains and refuses to share facts."""
        mindset = Mindset(mood=30)
        memory = Memory(known_facts={"fact_mines"})

        dialogue = format_npc_dialogue(
            npc_name="Bari the Helpful",
            personality=Personality.HELPFUL,
            mindset=mindset,
            memory=memory,
            fact_manager=self.fm,
        )

        self.assertTrue(dialogue.refused)
        self.assertIn("terrible day", dialogue.body)
        self.assertIn("leave me be", dialogue.body)
        self.assertNotIn("silver mines", dialogue.body)
        self.assertIsNone(dialogue.shared_fact)

    def test_cynical_personality_bad_mood_complains_and_refuses(self) -> None:
        """Mood < 50 with CYNICAL personality aggressively refuses and complains."""
        mindset = Mindset(mood=20)
        memory = Memory(known_facts={"fact_mines"})

        dialogue = format_npc_dialogue(
            npc_name="Grimm the Cynic",
            personality=Personality.CYNICAL,
            mindset=mindset,
            memory=memory,
            fact_manager=self.fm,
        )

        self.assertTrue(dialogue.refused)
        self.assertIn("Get lost!", dialogue.greeting)
        self.assertIn("Buzz off", dialogue.body)
        self.assertNotIn("silver mines", dialogue.body)
        self.assertIsNone(dialogue.shared_fact)


class TestEntityCollisionAndNPCInteraction(unittest.TestCase):
    """Test suite for entity collision and bump-to-talk NPC interactions."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        self.interaction_system = main.current_interaction_system
        self.combat_log = main.current_combat_log
        self.render_system = esper.get_processor(RenderSystem)
        esper.process()

    def test_spawned_npc_components(self) -> None:
        """Verify Garrick the Local has NPC, Personality, Mindset, and Memory with injected Fact."""
        pos = esper.component_for_entity(self.player, Position)

        # Locate NPC spawned at (player.x - 1, player.y, player.z)
        npc_ent = None
        for ent, (n_pos, _) in esper.get_components(Position, NPC):
            if (n_pos.x, n_pos.y, n_pos.z) == (pos.x - 1, pos.y, pos.z):
                npc_ent = ent
                break

        self.assertIsNotNone(npc_ent, "Garrick the Local should spawn adjacent to player")
        self.assertTrue(esper.has_component(npc_ent, Personality))
        self.assertTrue(esper.has_component(npc_ent, Mindset))
        self.assertTrue(esper.has_component(npc_ent, Memory))
        self.assertTrue(esper.has_component(npc_ent, BlocksTile))

        memory = esper.component_for_entity(npc_ent, Memory)
        self.assertIn("fact_bandits_north_woods", memory.known_facts)

        mindset = esper.component_for_entity(npc_ent, Mindset)
        self.assertGreater(mindset.mood, 50)

    def test_entity_collision_blocks_walking_into_dummy(self) -> None:
        """Attempting to walk into a tile occupied by the Training Dummy is blocked."""
        pos = esper.component_for_entity(self.player, Position)
        initial_x, initial_y, initial_z = pos.x, pos.y, pos.z

        # Dummy is at (player.x + 1, player.y, player.z)
        self.combat_log.clear()
        esper.process(key=terminal.TK_RIGHT)

        # Movement blocked: player position has not changed
        self.assertEqual((pos.x, pos.y, pos.z), (initial_x, initial_y, initial_z))

        # Combat log records movement blocked
        messages = self.combat_log.get_latest(1)
        self.assertIn("Movement blocked by Training Dummy", messages[0])

    def test_bumping_npc_triggers_dialogue_window_instead_of_attack(self) -> None:
        """Bumping into an interactable NPC opens dialogue text window and does not move into tile."""
        pos = esper.component_for_entity(self.player, Position)
        initial_x, initial_y, initial_z = pos.x, pos.y, pos.z

        # NPC Garrick is at (player.x - 1, player.y, player.z)
        self.combat_log.clear()
        # Move Left towards the NPC
        esper.process(key=terminal.TK_LEFT)

        # Player remains in original tile (does not step onto NPC)
        self.assertEqual((pos.x, pos.y, pos.z), (initial_x, initial_y, initial_z))

        # Dialogue window is active!
        self.assertTrue(self.interaction_system.has_active_dialogue())
        active = self.interaction_system.get_active_dialogue()
        self.assertIsNotNone(active)
        self.assertEqual(active.speaker_name, "Garrick the Local")
        self.assertIn("Hello there, traveler!", active.greeting)
        self.assertIn("iron-masked bandits", active.body)

        # Logged to combat/system log
        messages = self.combat_log.get_latest(1)
        self.assertIn("Garrick the Local", messages[0])
        self.assertIn("bandits", messages[0])

    def test_dismiss_dialogue_window_with_space(self) -> None:
        """Pressing SPACE dismisses the active dialogue window."""
        # Trigger dialogue by bumping NPC to the Left
        esper.process(key=terminal.TK_LEFT)
        self.assertTrue(self.interaction_system.has_active_dialogue())

        # Press SPACE to close window
        esper.process(key=terminal.TK_SPACE)
        self.assertFalse(self.interaction_system.has_active_dialogue())

    def test_dismiss_dialogue_window_with_esc(self) -> None:
        """Pressing ESCAPE dismisses the active dialogue window."""
        esper.process(key=terminal.TK_LEFT)
        self.assertTrue(self.interaction_system.has_active_dialogue())

        # Press ESC to close window
        esper.process(key=terminal.TK_ESCAPE)
        self.assertFalse(self.interaction_system.has_active_dialogue())

    def test_npc_mood_below_fifty_refuses_dialogue(self) -> None:
        """When NPC mood drops below 50, bumping them triggers complaint and refusal."""
        pos = esper.component_for_entity(self.player, Position)

        # Find NPC and set mood to 25
        npc_ent = None
        for ent, (n_pos, _) in esper.get_components(Position, NPC):
            if (n_pos.x, n_pos.y, n_pos.z) == (pos.x - 1, pos.y, pos.z):
                npc_ent = ent
                break
        self.assertIsNotNone(npc_ent)
        mindset = esper.component_for_entity(npc_ent, Mindset)
        mindset.mood = 25

        # Bump into NPC
        esper.process(key=terminal.TK_LEFT)
        self.assertTrue(self.interaction_system.has_active_dialogue())
        dialogue = self.interaction_system.get_active_dialogue()

        self.assertTrue(dialogue.refused)
        self.assertIn("terrible day", dialogue.body)
        self.assertNotIn("iron-masked bandits", dialogue.body)

    def test_render_system_renders_active_dialogue_window_cleanly(self) -> None:
        """RenderSystem renders active dialogue window on Layer 3 without errors."""
        # Open dialogue
        esper.process(key=terminal.TK_LEFT)
        self.assertTrue(self.interaction_system.has_active_dialogue())

        # Calling RenderSystem process() draws the window overlay
        self.render_system.process()


if __name__ == "__main__":
    unittest.main()
