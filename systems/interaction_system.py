"""Interaction and Dialogue System for Dwarf Fortress-style NPC interactions.

Implements Section 6 of the GDD:
- Formats NPC greetings and known facts based on Mindset (mood 0-100) and Personality Enum.
- Opens a dialogue text window when the player bumps into an interactable NPC.
- If mood > 50: greets player and shares known Fact text flavored by Personality.
- If mood < 50 (or <= 50): complains and refuses to share Facts flavored by Personality.
"""

from dataclasses import dataclass
import esper

from components import Memory, Mindset, Name, Personality, Player
from facts import Fact, FactManager, global_fact_manager
from systems.turn_management_system import CombatLog


@dataclass
class FormattedDialogue:
    """Encapsulates the dialogue response generated for an interaction."""

    speaker_name: str
    greeting: str
    body: str
    full_text: str
    mood: int
    personality: Personality
    shared_fact: Fact | None = None
    refused: bool = False


def format_npc_dialogue(
    npc_name: str,
    personality: Personality | str,
    mindset: Mindset | int,
    memory: Memory | set[str] | None,
    fact_manager: FactManager | None = None,
) -> FormattedDialogue:
    """Format dialogue for an NPC based on their mood, personality, and known facts.

    Rules:
    - If mood > 50: greets player and prints the text of the Fact they know, flavored by Personality.
    - If mood < 50 (or <= 50): complains and refuses to share Facts, flavored by Personality.
    """
    fm = fact_manager if fact_manager is not None else global_fact_manager

    # Resolve personality Enum
    if isinstance(personality, Personality):
        pers_enum = personality
    else:
        try:
            pers_enum = Personality(str(personality).upper())
        except (ValueError, KeyError):
            pers_enum = Personality.HELPFUL

    # Resolve mood integer
    mood_val = mindset.mood if isinstance(mindset, Mindset) else int(mindset)

    # Resolve known facts set
    if isinstance(memory, Memory):
        known_ids = memory.known_facts
    elif isinstance(memory, set):
        known_ids = memory
    else:
        known_ids = set()

    # Determine if NPC shares facts or refuses
    if mood_val > 50:
        refused = False
        # Find first known fact registered in FactManager
        shared_fact: Fact | None = None
        for f_id in known_ids:
            found = fm.get_fact(f_id)
            if found is not None:
                shared_fact = found
                break

        fact_text = shared_fact.text if shared_fact is not None else "I haven't heard any fresh rumors today."

        if pers_enum == Personality.HELPFUL:
            greeting = "Hello there, traveler! Glad to see a friendly face."
            if shared_fact is not None:
                body = f'I\'d be glad to share what I know: "{fact_text}" Stay safe out there!'
            else:
                body = "I don't have any particular news right now, but please let me know if you need anything!"
        elif pers_enum == Personality.CYNICAL:
            greeting = "What do you want? Don't just stand there staring."
            if shared_fact is not None:
                body = f'Hmph, if you really must know: "{fact_text}" ...not that it will do you any good.'
            else:
                body = "I've got nothing to say to you. Go bother someone else."
        elif pers_enum == Personality.OPTIMISTIC:
            greeting = "Greetings, friend! Wonderful day for an adventure!"
            if shared_fact is not None:
                body = f'Listen to this fascinating news: "{fact_text}" Great opportunities ahead!'
            else:
                body = "The future looks bright, even if there's no big news today!"
        elif pers_enum == Personality.STOIC:
            greeting = "Greetings."
            if shared_fact is not None:
                body = f'The word is: "{fact_text}"'
            else:
                body = "All is quiet."
        else:
            greeting = "Hello."
            body = fact_text

    else:
        # Mood <= 50: NPC complains and refuses to share Facts
        refused = True
        shared_fact = None

        if pers_enum == Personality.HELPFUL:
            greeting = "Oh... hello..."
            body = "I'm really having a terrible day and feel completely overwhelmed right now. Please leave me be, I can't help you with anything."
        elif pers_enum == Personality.CYNICAL:
            greeting = "Get lost!"
            body = "I don't give a damn about you or your questions! Buzz off and leave me alone!"
        elif pers_enum == Personality.OPTIMISTIC:
            greeting = "Sigh..."
            body = "Even I can't find a silver lining today. Things are just awful. Please leave me alone."
        elif pers_enum == Personality.STOIC:
            greeting = "..."
            body = "I have nothing to say to you. Move along."
        else:
            greeting = "Leave me alone."
            body = "I am in no mood to speak with you."

    full_text = f"{greeting} {body}"

    return FormattedDialogue(
        speaker_name=npc_name,
        greeting=greeting,
        body=body,
        full_text=full_text,
        mood=mood_val,
        personality=pers_enum,
        shared_fact=shared_fact,
        refused=refused,
    )


class InteractionSystem(esper.Processor):
    """Manages player interactions with NPCs and active dialogue windows."""

    def __init__(
        self,
        fact_manager: FactManager | None = None,
        combat_log: CombatLog | None = None,
    ) -> None:
        super().__init__()
        self.fact_manager = fact_manager if fact_manager is not None else global_fact_manager
        self.combat_log = combat_log
        self.active_dialogue: FormattedDialogue | None = None

    def process(self, *args, **kwargs) -> None:
        """Process interaction updates if necessary."""
        pass

    def interact(self, player_ent: int, npc_ent: int) -> FormattedDialogue:
        """Initiate dialogue interaction between player and NPC, opening the text window."""
        npc_name = "NPC"
        if esper.has_component(npc_ent, Name):
            npc_name = esper.component_for_entity(npc_ent, Name).name

        personality = Personality.HELPFUL
        if esper.has_component(npc_ent, Personality):
            personality = esper.component_for_entity(npc_ent, Personality)

        mindset = Mindset(mood=50)
        if esper.has_component(npc_ent, Mindset):
            mindset = esper.component_for_entity(npc_ent, Mindset)

        memory = Memory()
        if esper.has_component(npc_ent, Memory):
            memory = esper.component_for_entity(npc_ent, Memory)

        dialogue = format_npc_dialogue(
            npc_name=npc_name,
            personality=personality,
            mindset=mindset,
            memory=memory,
            fact_manager=self.fact_manager,
        )

        self.active_dialogue = dialogue

        if self.combat_log is not None:
            self.combat_log.add(f'{npc_name}: "{dialogue.full_text}"')

        return dialogue

    def close_dialogue(self) -> None:
        """Close the currently active dialogue text window."""
        self.active_dialogue = None

    def has_active_dialogue(self) -> bool:
        """Return True if a dialogue text window is currently open."""
        return self.active_dialogue is not None

    def get_active_dialogue(self) -> FormattedDialogue | None:
        """Return the active FormattedDialogue or None."""
        return self.active_dialogue
