"""ECS Components for the Sandbox Roguelike RPG.

Follows the architectural guidelines of strict separation between Data (Components)
and Logic (Systems).
"""

from dataclasses import dataclass, field
from enum import Enum, IntEnum


class RenderOrder(IntEnum):
    """Hierarchy determining which character is rendered when multiple entities share an X,Y tile."""

    FLOOR = 0
    CORPSE = 10
    FURNITURE = 20
    ITEM = 30
    NPC = 40
    PLAYER = 50


@dataclass
class Position:
    """Represents a 3D location in the world grid (X, Y, Z)."""

    x: int
    y: int
    z: int = 0


@dataclass
class Renderable:
    """Represents visual character, color, layer, and rendering priority order."""

    char: str = "@"
    color: str = "white"
    layer: int = 1
    render_order: int = RenderOrder.FLOOR


@dataclass
class Player:
    """Tag component identifying the player entity."""

    pass


@dataclass
class MovementIntent:
    """Represents an intended movement offset for an entity in 3D space."""

    dx: int = 0
    dy: int = 0
    dz: int = 0


@dataclass
class Door:
    """Represents an interactable door component with open/closed state."""

    is_open: bool = False
    closed_char: str = "+"
    open_char: str = "/"
    closed_color: str = "white"
    open_color: str = "gray"

    def toggle(self) -> bool:
        """Toggle the open/closed state of the door."""
        self.is_open = not self.is_open
        return self.is_open


@dataclass
class Name:
    """Descriptive display name for an entity."""

    name: str


@dataclass
class Fighter:
    """Combat component holding health and damage handling."""

    hp: int
    max_hp: int
    defense: int = 0
    power: int = 0

    def take_damage(self, amount: int) -> int:
        """Apply damage reducing current HP. Returns actual damage dealt."""
        actual = min(self.hp, amount)
        self.hp = max(0, self.hp - amount)
        return actual

    @property
    def is_alive(self) -> bool:
        """Check whether entity has remaining HP."""
        return self.hp > 0


@dataclass
class Energy:
    """Turn management resource component. Entities must have enough energy to act."""

    current: int = 100
    max_energy: int = 100
    gain_per_tick: int = 10
    regen_rate: int = 10
    action_cost: int = 20
    consumed_this_tick: bool = False

    def can_act(self, cost: int | None = None) -> bool:
        """Return True if current energy meets or exceeds the action cost."""
        c = cost if cost is not None else self.action_cost
        return self.current >= c

    def consume(self, cost: int | None = None) -> bool:
        """Consume energy for an action if sufficient. Returns True on success."""
        c = cost if cost is not None else self.action_cost
        if c > 0:
            if self.current >= c:
                self.current -= c
                self.consumed_this_tick = True
                return True
            return False
        elif c == 0:
            return True
        return False

    def gain(self, amount: int | None = None) -> int:
        """Accumulate energy per turn/tick up to max_energy. Returns actual gained."""
        a = amount if amount is not None else self.gain_per_tick
        before = self.current
        self.current = min(self.max_energy, self.current + a)
        return self.current - before

    def regenerate(self, amount: int | None = None, force: bool = False) -> int:
        """Regenerate energy per turn tick up to max_energy if energy was not consumed."""
        if self.consumed_this_tick and not force:
            self.consumed_this_tick = False
            return 0
        self.consumed_this_tick = False
        r = amount if amount is not None else self.regen_rate
        return self.gain(r)


@dataclass
class Skill:
    """Represents an active skill action available on an entity's skill bar."""

    name: str
    energy_cost: int = 20
    damage: int = 15
    cooldown: int = 0
    current_cooldown: int = 0
    description: str = ""
    range: int = 1


@dataclass
class SkillBar:
    """List of available skill actions for turn-based combat."""

    skills: list[Skill] = field(default_factory=list)

    def get_skill(self, index: int) -> Skill | None:
        """Return the skill in the specified slot index, or None."""
        if 0 <= index < len(self.skills):
            return self.skills[index]
        return None


@dataclass
class StructureFootprint:
    """Defines spatial boundary, Z-level, and optional room ID for a structure."""

    x: int
    y: int
    width: int
    height: int
    z: int = 0
    name: str = "Building"
    room_id: int | None = None
    building_id: str | int | None = None

    def __post_init__(self) -> None:
        if self.building_id is None:
            self.building_id = self.name

    def contains(self, px: int, py: int, pz: int) -> bool:
        """Check whether coordinates (px, py, pz) lie inside this structure footprint."""
        return (
            self.z == pz
            and self.x <= px < self.x + self.width
            and self.y <= py < self.y + self.height
        )


@dataclass
class Viewshed:
    """Holds Field of View (FOV) and interior occlusion state for an entity."""

    radius: int = 15
    visible_tiles: set[tuple[int, int]] = field(default_factory=set)
    inside_structure: bool = False
    active_structure: StructureFootprint | None = None
    active_building_id: str | int | None = None
    current_room_id: int | None = None

    def is_visible(self, x: int, y: int) -> bool:
        """Check if coordinates (x, y) are currently visible in FOV."""
        return (x, y) in self.visible_tiles


# --- Dwarf Fortress-Style NPC Knowledge and Personality Components ---

class Personality(Enum):
    """Personality archetypes influencing dialogue generation, greetings, and mood thresholds."""

    HELPFUL = "HELPFUL"
    CYNICAL = "CYNICAL"
    OPTIMISTIC = "OPTIMISTIC"
    STOIC = "STOIC"


@dataclass
class Memory:
    """Holds a set of known Fact IDs for dialogue and inquiry."""

    known_facts: set[str] = field(default_factory=set)

    def learn_fact(self, fact_id: str) -> None:
        """Add a Fact ID to known facts."""
        self.known_facts.add(fact_id)

    def forget_fact(self, fact_id: str) -> None:
        """Remove a Fact ID from known facts."""
        self.known_facts.discard(fact_id)

    def knows_fact(self, fact_id: str) -> bool:
        """Check if a Fact ID is known."""
        return fact_id in self.known_facts


@dataclass
class Mindset:
    """Holds current mood integer (0-100) and emotional state of an NPC."""

    mood: int = 50  # 0 (despair/furious) to 100 (ecstatic/optimistic)

    def modify_mood(self, delta: int) -> None:
        """Adjust mood clamping between 0 and 100."""
        self.mood = max(0, min(100, self.mood + delta))


@dataclass
class NPC:
    """Tag component identifying an NPC character."""

    pass


@dataclass
class BlocksTile:
    """Tag component indicating an entity occupies and blocks its tile from other entities."""

    pass


# --- Inventory and Item Components ---

@dataclass
class Item:
    """Item component holding identity, weight, and descriptive metadata."""

    name: str
    weight: float = 1.0
    description: str = ""
    slot: "EquipmentSlot | None" = None
    stat_bonuses: dict[str, int] = field(default_factory=dict)


@dataclass
class Inventory:
    """Inventory container component holding a collection of item entity IDs."""

    items: list[int] = field(default_factory=list)
    max_capacity: int = 20

    def is_full(self) -> bool:
        """Check if inventory has reached maximum capacity."""
        return len(self.items) >= self.max_capacity

    def add_item(self, item_entity: int) -> bool:
        """Add an item entity to the inventory. Returns True on success, False if full."""
        if self.is_full():
            return False
        self.items.append(item_entity)
        return True

    def remove_item(self, item_entity: int) -> bool:
        """Remove an item entity from the inventory. Returns True if found."""
        if item_entity in self.items:
            self.items.remove(item_entity)
            return True
        return False


# --- 3-Tier Stats and 11-Slot Equipment Components ---

class EquipmentSlot(Enum):
    """The 11 distinct equipment slots: 6 Armor slots and 5 Trinket slots."""

    # Armor Slots
    HEAD = "Head"
    CAPE = "Cape"
    TORSO = "Torso"
    GLOVES = "Glove"
    LEGS = "Legs"
    BOOTS = "Boots"

    # Trinket Slots
    HAIR_ORNAMENT = "Hair_Orn"
    NECKLACE = "Necklace"
    BELT = "Belt"
    WRISTBAND = "Wristband"
    RING = "Ring"


@dataclass
class Equippable:
    """Component identifying an item as equippable into a designated slot with stat bonuses."""

    slot: EquipmentSlot
    stat_bonuses: dict[str, int] = field(default_factory=dict)


@dataclass
class Equipment:
    """Equipment component managing exactly 11 slots (6 Armor + 5 Trinkets)."""

    slots: dict[EquipmentSlot, int | None] = field(
        default_factory=lambda: {
            EquipmentSlot.HEAD: None,
            EquipmentSlot.CAPE: None,
            EquipmentSlot.TORSO: None,
            EquipmentSlot.GLOVES: None,
            EquipmentSlot.LEGS: None,
            EquipmentSlot.BOOTS: None,
            EquipmentSlot.HAIR_ORNAMENT: None,
            EquipmentSlot.NECKLACE: None,
            EquipmentSlot.BELT: None,
            EquipmentSlot.WRISTBAND: None,
            EquipmentSlot.RING: None,
        }
    )

    def get_equipped(self, slot: EquipmentSlot) -> int | None:
        """Return the item entity equipped in slot, or None."""
        return self.slots.get(slot)

    def equip(self, slot: EquipmentSlot, item_entity: int) -> int | None:
        """Equip item_entity into slot. Returns previously equipped item entity if any."""
        old = self.slots.get(slot)
        self.slots[slot] = item_entity
        return old

    def unequip(self, slot: EquipmentSlot) -> int | None:
        """Unequip item in slot. Returns previously equipped item entity if any."""
        old = self.slots.get(slot)
        self.slots[slot] = None
        return old

    def is_equipped(self, item_entity: int) -> bool:
        """Check if an item entity is currently equipped in any slot."""
        return item_entity in self.slots.values()

    def get_slot_of(self, item_entity: int) -> EquipmentSlot | None:
        """Return the slot that item_entity is equipped in, or None."""
        for slot, ent in self.slots.items():
            if ent == item_entity:
                return slot
        return None


@dataclass
class Stats:
    """3-Tier Character Stats Component.

    Tier 1: Base Stats (Level, XP)
    Tier 2: D&D Substats (STR, DEX, CON, INT, WIS, CHA)
    Tier 3: Battle Stats (Max HP, Speed, Damage, Defense, Crit Rate, Crit Damage, Evasion)

    Strict Derivation Rules:
    - 1 CON = +5 Max HP
    - 1 STR = +1 Damage
    - 1 DEX = +1 Speed and +0.5% Evasion
    - 1 INT = +0.5% Crit Rate
    - 1 WIS = +1 Defense
    """

    # Tier 1: Base Stats
    level: int = 1
    xp: int = 0
    max_xp: int = 100

    # Tier 2: D&D Substats (Base unmodified)
    strength: int = 10       # STR
    dexterity: int = 10      # DEX
    constitution: int = 10   # CON
    intelligence: int = 10   # INT
    wisdom: int = 10         # WIS
    charisma: int = 10       # CHA

    # Equipment / Buff modifiers to D&D Substats
    bonus_strength: int = 0
    bonus_dexterity: int = 0
    bonus_constitution: int = 0
    bonus_intelligence: int = 0
    bonus_wisdom: int = 0
    bonus_charisma: int = 0

    # Tier 3: Battle Stats (Derived)
    max_hp: int = 50
    speed: int = 10
    damage: int = 10
    defense: int = 10
    crit_rate: float = 5.0      # in %
    crit_damage: float = 150.0  # in %
    evasion: float = 5.0        # in %

    # Direct battle stat modifiers
    bonus_max_hp: int = 0
    bonus_speed: int = 0
    bonus_damage: int = 0
    bonus_defense: int = 0
    bonus_crit_rate: float = 0.0
    bonus_crit_damage: float = 0.0
    bonus_evasion: float = 0.0

    def __post_init__(self) -> None:
        self.recalculate()

    def total_strength(self) -> int:
        return self.strength + self.bonus_strength

    def total_dexterity(self) -> int:
        return self.dexterity + self.bonus_dexterity

    def total_constitution(self) -> int:
        return self.constitution + self.bonus_constitution

    def total_intelligence(self) -> int:
        return self.intelligence + self.bonus_intelligence

    def total_wisdom(self) -> int:
        return self.wisdom + self.bonus_wisdom

    def total_charisma(self) -> int:
        return self.charisma + self.bonus_charisma

    def recalculate(self) -> None:
        """Strict derivation logic calculating Battle Stats from total D&D Substats.

        Derivation rules:
        - 1 CON = +5 Max HP
        - 1 STR = +1 Damage
        - 1 DEX = +1 Speed and +0.5% Evasion
        - 1 INT = +0.5% Crit Rate
        - 1 WIS = +1 Defense
        """
        tot_con = self.total_constitution()
        tot_str = self.total_strength()
        tot_dex = self.total_dexterity()
        tot_int = self.total_intelligence()
        tot_wis = self.total_wisdom()

        self.max_hp = tot_con * 5 + self.bonus_max_hp
        self.damage = tot_str * 1 + self.bonus_damage
        self.speed = tot_dex * 1 + self.bonus_speed
        self.evasion = round(tot_dex * 0.5 + self.bonus_evasion, 1)
        self.crit_rate = round(tot_int * 0.5 + self.bonus_crit_rate, 1)
        self.defense = tot_wis * 1 + self.bonus_defense
        self.crit_damage = 150.0 + self.bonus_crit_damage


# --- Survival and Overworld Components ---

@dataclass
class SurvivalStats:
    """Tracks survival resources (Food and Water) for overworld exploration."""

    food: int = 100
    max_food: int = 100
    water: int = 100
    max_water: int = 100

    def consume(self, food_amount: int = 1, water_amount: int = 1) -> tuple[int, int]:
        """Consume food and water, clamping values to 0. Returns (actual_food_lost, actual_water_lost)."""
        f_loss = min(self.food, food_amount)
        w_loss = min(self.water, water_amount)
        self.food = max(0, self.food - food_amount)
        self.water = max(0, self.water - water_amount)
        return f_loss, w_loss

    def restore(self, food_amount: int = 0, water_amount: int = 0) -> None:
        """Restore food and water, clamping to max values."""
        self.food = min(self.max_food, self.food + food_amount)
        self.water = min(self.max_water, self.water + water_amount)

    @property
    def is_starving(self) -> bool:
        """Check if food supply is exhausted."""
        return self.food <= 0

    @property
    def is_dehydrated(self) -> bool:
        """Check if water supply is exhausted."""
        return self.water <= 0


@dataclass
class RegionalPosition:
    """Tracks an entity's 2D grid coordinates on the Regional Map and descend status."""

    x: int
    y: int
    is_descended: bool = False



