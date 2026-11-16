"""Sandbox Roguelike RPG - Main Entry Point.

Initializes the game window via BearLibTerminal, configures
the Entity Component System (esper), and runs the main game loop.
Supports Local Map tactical gameplay (with FOV, doors, graph-based building generation,
and interior occlusion) and smoothed Regional Map world overview (with Lloyd's Relaxation).
"""

from bearlibterminal import terminal
import esper

from building_generator import create_tavern_graph, stamp_building_graph
from components import (
    BlocksTile,
    Door,
    Energy,
    Equipment,
    EquipmentSlot,
    Equippable,
    Fighter,
    Inventory,
    Item,
    Memory,
    Mindset,
    MovementIntent,
    Name,
    NPC,
    Personality,
    Player,
    Position,
    RegionalPosition,
    RenderOrder,
    Renderable,
    Skill,
    SkillBar,
    Stats,
    StructureFootprint,
    SurvivalStats,
    Viewshed,
)
from facts import Fact, FactManager, global_fact_manager
from game_map import GameMap, Tile
from game_state import GameState, GameStateManager
from local_map_generator import LocalMapGenerator
from message_log import MessageLog, global_message_log
from regional_map_generator import RegionalMap, RegionalMapGenerator
from systems import (
    CombatLog,
    DoorSystem,
    EquipmentSystem,
    InputSystem,
    InteractionSystem,
    ItemCollectionSystem,
    MapTransitionSystem,
    MovementSystem,
    RegionalMovementSystem,
    RenderSystem,
    TurnManagementSystem,
    VisibilitySystem,
)
from world_clock import WorldClock, global_world_clock

# --- Screen & Map Configuration ---
SCREEN_WIDTH: int = 120
SCREEN_HEIGHT: int = 40
MAP_VIEWPORT_WIDTH: int = 85
MAP_VIEWPORT_HEIGHT: int = 30
SIDEBAR_WIDTH: int = 35
CONSOLE_HEIGHT: int = 10
MAP_WIDTH: int = 200
MAP_HEIGHT: int = 200
WINDOW_TITLE: str = "Sandbox Roguelike RPG"

# Active references
current_game_map: GameMap | None = None
current_regional_map: RegionalMap | None = None
current_state_manager: GameStateManager | None = None
current_door_system: DoorSystem | None = None
current_turn_system: TurnManagementSystem | None = None
current_combat_log: CombatLog | None = None
current_interaction_system: InteractionSystem | None = None
current_item_collection_system: ItemCollectionSystem | None = None
current_equipment_system: EquipmentSystem | None = None
current_fact_manager: FactManager | None = None
current_message_log: MessageLog | None = None
current_local_map_generator: LocalMapGenerator | None = None
current_regional_movement_system: RegionalMovementSystem | None = None
current_map_transition_system: MapTransitionSystem | None = None
current_world_clock: WorldClock = global_world_clock


def init_ecs(
    game_map: GameMap | None = None,
    regional_map: RegionalMap | None = None,
    state_manager: GameStateManager | None = None,
    fact_manager: FactManager | None = None,
) -> int:
    """Initialize the ECS world, register processors, and spawn entities."""
    global current_game_map, current_regional_map, current_state_manager, current_door_system, current_turn_system, current_combat_log, current_interaction_system, current_item_collection_system, current_equipment_system, current_fact_manager, current_local_map_generator, current_regional_movement_system, current_map_transition_system, current_world_clock

    if regional_map is None:
        regional_map = RegionalMapGenerator(
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
            num_cells=35,
            relaxation_steps=3,
        ).generate()
    current_regional_map = regional_map

    generator: LocalMapGenerator | None = None
    if game_map is None:
        start_rx = regional_map.width // 2
        start_ry = regional_map.height // 2
        start_tile = regional_map.get_regional_tile(start_rx, start_ry)
        generator = LocalMapGenerator(
            width=MAP_WIDTH,
            height=MAP_HEIGHT,
            regional_tile=start_tile,
            seed=start_tile.seed,
        )
        game_map = generator.generate(seed=start_tile.seed, clear_starting_area=True)
        current_local_map_generator = generator
    current_game_map = game_map

    # Stamp the 3-node graph Tavern into the game map
    tavern_graph = create_tavern_graph()
    tavern_data = stamp_building_graph(tavern_graph, game_map, anchor_x=98, anchor_y=97)

    if state_manager is None:
        state_manager = GameStateManager(initial_state=GameState.LOCAL_MAP)
    current_state_manager = state_manager

    door_system = DoorSystem(game_map=game_map)
    current_door_system = door_system

    combat_log = CombatLog()
    current_combat_log = combat_log

    turn_system = TurnManagementSystem(combat_log=combat_log)
    current_turn_system = turn_system

    if fact_manager is None:
        fact_manager = global_fact_manager
    current_fact_manager = fact_manager

    # Register initial global Facts into FactManager
    fact_bandits_id = "fact_bandits_north_woods"
    fact_manager.register_fact(
        fact_id=fact_bandits_id,
        text="A notorious band of iron-masked bandits has set up camp in the northern woods.",
        subject="Bandit Camp",
        location="North Woods",
    )

    interaction_system = InteractionSystem(fact_manager=fact_manager, combat_log=combat_log)
    current_interaction_system = interaction_system

    item_collection_system = ItemCollectionSystem(message_log=combat_log)
    current_item_collection_system = item_collection_system

    equipment_system = EquipmentSystem(message_log=combat_log)
    current_equipment_system = equipment_system

    regional_movement_system = RegionalMovementSystem(
        regional_map=regional_map,
        state_manager=state_manager,
        world_clock=global_world_clock,
        combat_log=combat_log,
    )
    current_regional_movement_system = regional_movement_system

    transition_system = MapTransitionSystem(
        state_manager=state_manager,
        regional_map=regional_map,
        game_map=game_map,
        combat_log=combat_log,
        door_system=door_system,
    )
    current_map_transition_system = transition_system

    # Reset existing entities in the world
    esper.clear_database()

    # Cleanly unregister any existing processors before adding
    esper.remove_processor(TurnManagementSystem)
    esper.remove_processor(InteractionSystem)
    esper.remove_processor(ItemCollectionSystem)
    esper.remove_processor(EquipmentSystem)
    esper.remove_processor(DoorSystem)
    esper.remove_processor(RegionalMovementSystem)
    esper.remove_processor(InputSystem)
    esper.remove_processor(MovementSystem)
    esper.remove_processor(VisibilitySystem)
    esper.remove_processor(RenderSystem)

    # Register ECS systems in priority order (higher priority runs first):
    # Priority 6: TurnManagementSystem manages energy ticks, turn advancement, and skill actions
    # Priority 5: InteractionSystem manages NPC dialogues and text window states
    # Priority 5: ItemCollectionSystem handles picking up items into inventory ('G')
    # Priority 5: EquipmentSystem handles equipping items and stat derivations
    # Priority 5: DoorSystem synchronizes and handles door interactions
    # Priority 5: RegionalMovementSystem processes overworld movement and resource drain
    # Priority 4: InputSystem captures keyboard events -> MovementIntents, skills, door, inventory & character toggles
    # Priority 3: MovementSystem updates Positions respecting map collisions, entity collision, & bump interactions
    # Priority 2: VisibilitySystem calculates FOV via tcod, room reveals & interior occlusion
    # Priority 1: RenderSystem centers camera & draws visible map tiles, entities, dialogue window, HUD & combat log
    esper.add_processor(turn_system, priority=6)
    esper.add_processor(interaction_system, priority=5)
    esper.add_processor(item_collection_system, priority=5)
    esper.add_processor(equipment_system, priority=5)
    esper.add_processor(door_system, priority=5)
    esper.add_processor(regional_movement_system, priority=5)

    input_system = InputSystem(
        state_manager=state_manager,
        door_system=door_system,
        turn_system=turn_system,
        interaction_system=interaction_system,
        item_collection_system=item_collection_system,
        equipment_system=equipment_system,
        game_map=game_map,
        regional_movement_system=regional_movement_system,
        transition_system=transition_system,
    )
    movement_system = MovementSystem(
        game_map=game_map,
        state_manager=state_manager,
        door_system=door_system,
        turn_system=turn_system,
        interaction_system=interaction_system,
        transition_system=transition_system,
    )
    visibility_system = VisibilitySystem(game_map=game_map, state_manager=state_manager)
    render_system = RenderSystem(
        game_map=game_map,
        viewport_width=MAP_VIEWPORT_WIDTH,
        viewport_height=MAP_VIEWPORT_HEIGHT,
        screen_width=SCREEN_WIDTH,
        screen_height=SCREEN_HEIGHT,
        state_manager=state_manager,
        regional_map=regional_map,
        combat_log=combat_log,
        message_log=combat_log,
        interaction_system=interaction_system,
        world_clock=global_world_clock,
    )

    # Cross-wire systems with transition_system
    transition_system.input_system = input_system
    transition_system.movement_system = movement_system
    transition_system.visibility_system = visibility_system
    transition_system.render_system = render_system

    esper.add_processor(input_system, priority=4)
    esper.add_processor(movement_system, priority=3)
    esper.add_processor(visibility_system, priority=2)
    esper.add_processor(render_system, priority=1)

    # Spawn structure entities in the ECS world
    for footprint in game_map.structures:
        struct_ent = esper.create_entity()
        esper.add_component(struct_ent, Position(x=footprint.x, y=footprint.y, z=footprint.z))
        esper.add_component(struct_ent, footprint)

    # Spawn door entities for all doors in the world (Tavern doors)
    all_doors = set(tavern_data["doors_to_spawn"])

    for dx, dy, dz in all_doors:
        door_ent = esper.create_entity()
        esper.add_component(door_ent, Position(x=dx, y=dy, z=dz))
        esper.add_component(
            door_ent,
            Renderable(char="+", color="white", layer=1, render_order=RenderOrder.FURNITURE),
        )
        esper.add_component(door_ent, Door(is_open=False))

    # Spawn player entity inside the Main Room of the Tavern
    player_x, player_y, player_z = tavern_data["player_spawn"]

    player = esper.create_entity()
    esper.add_component(player, Position(x=player_x, y=player_y, z=player_z))
    esper.add_component(
        player,
        Renderable(char="@", color="white", layer=1, render_order=RenderOrder.PLAYER),
    )
    esper.add_component(player, Viewshed(radius=15))
    esper.add_component(player, Player())
    esper.add_component(player, BlocksTile())
    esper.add_component(player, Name("Player"))
    player_stats = Stats(
        level=1,
        xp=0,
        max_xp=100,
        strength=10,
        dexterity=10,
        constitution=10,
        intelligence=10,
        wisdom=10,
        charisma=10,
    )
    esper.add_component(player, player_stats)
    esper.add_component(player, Equipment())
    esper.add_component(player, Fighter(hp=player_stats.max_hp, max_hp=player_stats.max_hp))
    esper.add_component(player, Energy(current=100, max_energy=100, gain_per_tick=10, action_cost=20))
    esper.add_component(player, Inventory(max_capacity=20))
    esper.add_component(player, SurvivalStats(food=100, max_food=100, water=100, max_water=100))
    esper.add_component(
        player,
        RegionalPosition(
            x=regional_map.width // 2,
            y=regional_map.height // 2,
            is_descended=True,
        ),
    )
    esper.add_component(
        player,
        SkillBar(
            skills=[
                Skill(
                    name="Cleave",
                    energy_cost=20,
                    damage=15,
                    description="Strikes all adjacent enemies",
                    range=1,
                ),
                Skill(
                    name="Fireball",
                    energy_cost=20,
                    damage=25,
                    range=5,
                    description="Ranged fire projectile (Range: 5)",
                ),
            ]
        ),
    )

    # Spawn test item (Health Potion, '!') on the ground near the player at (player_x, player_y + 1, player_z)
    potion = esper.create_entity()
    esper.add_component(potion, Position(x=player_x, y=player_y + 1, z=player_z))
    esper.add_component(
        potion,
        Renderable(char="!", color="light magenta", layer=1, render_order=RenderOrder.ITEM),
    )
    esper.add_component(
        potion,
        Item(name="Health Potion", weight=0.5, description="Restores 25 Health Points."),
    )
    esper.add_component(potion, Name("Health Potion"))

    # Spawn Bronze Ring (Trinket, +2 STR) at (player_x - 1, player_y + 1, player_z)
    ring = esper.create_entity()
    esper.add_component(ring, Position(x=player_x - 1, y=player_y + 1, z=player_z))
    esper.add_component(
        ring,
        Renderable(char="=", color="amber", layer=1, render_order=RenderOrder.ITEM),
    )
    esper.add_component(
        ring,
        Item(
            name="Bronze Ring",
            weight=0.1,
            description="A sturdy bronze ring that enhances strength.",
            slot=EquipmentSlot.RING,
            stat_bonuses={"strength": 2},
        ),
    )
    esper.add_component(
        ring,
        Equippable(slot=EquipmentSlot.RING, stat_bonuses={"strength": 2}),
    )
    esper.add_component(ring, Name("Bronze Ring"))

    # Spawn Leather Tunic (Torso, +2 CON) at (player_x + 1, player_y + 1, player_z)
    tunic = esper.create_entity()
    esper.add_component(tunic, Position(x=player_x + 1, y=player_y + 1, z=player_z))
    esper.add_component(
        tunic,
        Renderable(char="[", color="light brown", layer=1, render_order=RenderOrder.ITEM),
    )
    esper.add_component(
        tunic,
        Item(
            name="Leather Tunic",
            weight=3.0,
            description="Tough boiled leather vest providing health.",
            slot=EquipmentSlot.TORSO,
            stat_bonuses={"constitution": 2},
        ),
    )
    esper.add_component(
        tunic,
        Equippable(slot=EquipmentSlot.TORSO, stat_bonuses={"constitution": 2}),
    )
    esper.add_component(tunic, Name("Leather Tunic"))

    # Spawn Training Dummy NPC adjacent to the player at (player_x + 1, player_y, player_z)
    dummy = esper.create_entity()
    esper.add_component(dummy, Position(x=player_x + 1, y=player_y, z=player_z))
    esper.add_component(
        dummy,
        Renderable(char="D", color="yellow", layer=1, render_order=RenderOrder.NPC),
    )
    esper.add_component(dummy, Name("Training Dummy"))
    esper.add_component(dummy, BlocksTile())
    esper.add_component(dummy, Fighter(hp=50, max_hp=50))
    esper.add_component(dummy, Energy(current=0, max_energy=100, gain_per_tick=10))

    # Spawn test NPC (Garrick the Local) adjacent to the player at (player_x - 1, player_y, player_z)
    npc = esper.create_entity()
    esper.add_component(npc, Position(x=player_x - 1, y=player_y, z=player_z))
    esper.add_component(
        npc,
        Renderable(char="N", color="cyan", layer=1, render_order=RenderOrder.NPC),
    )
    esper.add_component(npc, Name("Garrick the Local"))
    esper.add_component(npc, NPC())
    esper.add_component(npc, BlocksTile())
    esper.add_component(npc, Personality.HELPFUL)
    esper.add_component(npc, Mindset(mood=75))  # Friendly mood (> 50)
    esper.add_component(npc, Memory(known_facts={fact_bandits_id}))

    # Spawn interactable herbs across the local map
    if generator is not None:
        generator.spawn_herbs()

    return player


def main() -> None:
    """Main game initialization and event loop."""
    terminal.open()
    terminal.set(
        f"window: size={SCREEN_WIDTH}x{SCREEN_HEIGHT}, title='{WINDOW_TITLE}'; font: default; palette: light brown = #c48a56, brown = #8b5a2b;"
    )

    # Initialize ECS entities, map, and processors
    init_ecs()

    # Initial frame processing (computes initial FOV and renders)
    esper.process()

    try:
        while True:
            # Wait for user input
            key = terminal.read()

            # Handle window close
            if key == terminal.TK_CLOSE:
                break

            # Handle ESC key: close modal screens (inventory, character, or dialogue) if active, else exit game
            if key == terminal.TK_ESCAPE:
                if current_state_manager is not None and current_state_manager.state in (
                    GameState.INVENTORY,
                    GameState.CHARACTER,
                ):
                    esper.process(key=key)
                    continue
                if current_interaction_system is not None and current_interaction_system.has_active_dialogue():
                    esper.process(key=key)
                    continue
                break

            # Execute ECS frame with the input event
            esper.process(key=key)
    finally:
        # Cleanly shut down BearLibTerminal
        terminal.close()


if __name__ == "__main__":
    main()
