# Game Design Document: Sandbox Roguelike RPG

## 1. Core Information & Architecture

* **Genre:** Sandbox roguelike RPG in a D&D-style fantasy setting.
* **Player Perspective:** The player controls a single character (avatar).
* **Graphics:** ASCII art (similar to *Rogue* or *Dwarf Fortress*), played on a grid of characters.
* **Core Gameplay Loop:** Divided into two main pillars:
  1. Character progression (leveling up, getting equipment, exploring, becoming powerful/famous).
  2. Base management (building a stronghold, recruiting companions, managing resources).
* **Map Structure:** Two-tier system (similar to *Mount & Blade*).
  * *Regional Map:* Used for fast travel, uses up resources (food/water), and simulates time passage.
  * *Local Map:* A 200x200 grid where actual gameplay occurs. Wilderness maps reset upon exit; dungeons, settlements, and the player's base are persistent.
* **World Generation:** Procedural and infinite. Generated region by region based on the player's movement.

### 1.1 Codebase Architecture (For AI Agent)

* **Paradigm:** Entity Component System (ECS).
* **Separation of Concerns:** Strict separation into `DATA` (Components) and `SYSTEMS` (Logic).
* **Modularity:** Highly modular. Systems do not interact directly with each other. "Glue" manager classes (or an Event Bus) will handle cross-module communication to prevent spaghetti code.
* **Vibecoding Strategy:** The prototype will be built in Python (using libraries like `esper` for ECS and `BearLibTerminal` for advanced pseudo-terminal rendering and input). The architecture must use strict typing and decoupled data structures to allow specific, heavy systems (like map generation or line-of-sight) to be ported to C++ via `pybind11` later.

## 2. World Generation (Regional Map)

* **Visuals:** Uses ASCII graphics similar to the *Dwarf Fortress* regional map.
* **Generation Method:** Approximate Voronoi cells. Cells not touching the screen border are merged/smoothed to create regions (similar to *Azgaar's Fantasy Map Generator*).
* **Biomes & Races:** Each region has a dominant biome inhabited by a specific race:
  * Plains -> HUMANS
  * Swamps -> LIZARDMEN
  * Desert -> CATFOLK
  * Forest -> ELVES
  * Badlands -> TROLLS
  * Mountains -> DWARVES
  * Hills -> GNOMES
  * Wastes -> GOBLINS (Default evil alignment)
* **Biome Gradients:** Biomes interpolate at the borders (e.g., OCEAN -> CLIFF -> MOUNTAIN).
* **Hydrology:** Rivers follow smoothed Voronoi borders. Lakes act as natural drains if water doesn't reach the region's edge. Water recalculates and overrides surrounding biomes.
* **Hidden Layers:** Three Perlin noise overlays (Underground Water, Alignment [Good/Evil], pH level). These affect local map generation (flora/fauna) but aren't rendered on the regional map.
* **Points of Interest (POIs):**
  * *Settlements* (Cities/Towns/Villages) are biased toward water. Ports spawn near water borders.
  * *Special Settlements* (Monasteries, Magical Universities, Fortresses).
  * *Dungeons* are biased toward wilderness areas, far from settlements.
  * *Roads* are generated connecting settlements and exiting the region borders.

## 3. Local Map Generation (Wilderness/Tactical Map)

* **Trigger:** Generated dynamically when a player enters a tile on the regional map.
* **Dimensions:** 200x200 grid tiles, with multiple Z-levels (for basements, upper floors, and terrain elevation).
* **Terrain:** Ground tiles match the regional biome. Brooks and ponds are carved out.
* **Flora:**
  * *Large Flora (Trees):* Generated based on biome, pH, alignment, moisture, and distance to water. Rendered like *Dwarf Fortress* (leaves have smaller alpha values/different color depths).
  * *Small Flora (Bushes/Fungi):* Dependent on terrain and surrounding large flora.
* **Spawns:** Entities and structures override local flora appropriately.

### 3.1 Multi-Tile Structures & Interiors

* **Generation:** Points of interest on the local map (caves, bandit camps, ruins) are generated as **multi-tile structures**. They occupy footprints of varying sizes and can span **multiple Z-levels** (e.g., multi-story towers or deep cave networks).
* **Geometry:** Structures will have defined outer walls, entrance points, stairs for vertical traversal, and internal layouts.
* **FOV & LOS Dynamics (Interior vs. Exterior):**
  * *Exterior View:* When the player is outside a structure, the structure's walls block Line of Sight (LOS).
  * *Interior View (Entering):* When the player steps onto a designated entrance tile, their Field of View (FOV) recalculates to adapt to the interior layout of that specific floor/Z-level.
  * *Occlusion:* While inside, the outside world and other Z-levels dim or become completely occluded, focusing the player's view entirely on the structure's interior.

### 3.2 Settlement & Building Generation (Graph-Based + Prefabs)

Settlements (like cities and towns) are generated using a hierarchical ruleset combining procedural logic with handcrafted components:
* **City Level:** The settlement generates an overarching road network and perimeter.
* **District Level:** The city area is divided into distinct zones (e.g., Market, Noble, Slums).
* **Building Level (Graph Generation):** Before a building is placed on the grid, the generator creates a logical **graph** of the building's layout.
  * *Nodes* represent abstract rooms (e.g., "Kitchen," "Hallway," "Upper Bedroom").
  * *Edges* represent connections (e.g., "Door," "Staircase").
  * The graph handles constraints and multi-level logic.
* **Room Level (Instantiation):** Once the graph is validated, the system resolves it into physical space by pulling appropriate **room prefabs** and stitching them together on the grid along the X, Y, and Z axes. Connectors (doors/stairs) align based on the graph edges.

## 4. Combat & Skill System

* **Style:** A mix of *Rogue* (turn-based, grid movement) and *World of Warcraft* (hotbar skills, cooldowns, distinct resource pools).
* **Turn Flow:** Energy-based or standard turn-based. Moving/attacking uses action points or advances the time tick.
* **Skills:** Instead of simply bumping into enemies to attack, the player has a hotbar of skills (e.g., Cleave, Fireball, Dash, Shield Wall).
* **Resources:** Skills cost specific resources (Mana for mages, Rage/Stamina for warriors) and have turn-based cooldowns.
* **AoE & Positioning:** Attacks can target specific geometric shapes (cones, lines, radius) requiring strategic positioning on the 3D grid (taking Z-levels into account).

## 5. Base Building & Companions

* **Base Foundation:** The player can claim an empty local map or clear a dungeon/ruin to establish a persistent base.
* **Construction:** Using resources gathered from the local maps (wood, stone, metal), the player can place walls, floors, doors, stairs, and functional furniture.
* **Companions:** NPCs can be recruited from settlements or rescued from dungeons.
* **Camp Management:** Companions have basic needs (food, morale) and can be assigned to tasks using a lightweight job system while the player is out exploring the regional map.

## 6. NPC Interaction & Dialogue System

NPC dialogue is dynamically generated based on a hybrid system that tracks the NPC's internal state (Thoughts) and historical awareness (Facts), processed through a Context-Free Grammar (CFG) engine.

* **The Data Layer (Facts & Thoughts):**
  * *Facts (Knowledge):* Global or regional events exist as data objects (e.g., `Fact {Subject: Bandit Camp, Location: North Woods}`). NPCs learn these by witnessing events or trading Facts with others.
  * *Thoughts (Experiences):* Personal events generate temporary Thoughts that affect the NPC's mood (e.g., `Thought {Type: Saw Dead Body, MoodMod: -50}`).
* **Mood-Driven Greetings:**
  * When dialogue initiates, the game checks the NPC's `Mindset`. 
  * If their mood is neutral/happy, the CFG engine generates a standard greeting based on their personality.
  * If overwhelmed by a strong Thought (e.g., panic), the NPC bypasses standard greetings to express their immediate concern.
* **The Inquiry Layer (Player Investigation):**
  * The player uses an Inquiry Menu to ask about specific subjects/tags (e.g., "Ask about: Bandits").
  * The game searches the NPC's `Memory` for related Facts. The CFG engine then formats the known Fact into dialogue colored by the NPC's `Personality` (e.g., Cynical, Helpful).
  * *Deception:* NPCs belonging to hostile factions can use the CFG engine to deliberately alter Facts, providing the player with false information.
* **Spontaneous Rumors:** NPCs can share a random, previously unshared Fact from their memory during idle conversation.

## 7. ECS Blueprint (For AI Agent Implementation)

When the AI begins scaffolding the ECS, it should use these foundational structures:

* **Core Components:** 
  * `Position` (x, y, z - for multi-level tracking)
  * `Renderable` (char, color, layer)
  * `Name`, `Health` (hp, max_hp), `Stats` (str, dex, int)
  * `Fighter` (combat logic), `Inventory`, `AI` (behavior states)
  * `StructureFootprint` (defines interior bounds and Z-levels for buildings/caves)
  * `Memory` (Holds a set of known Fact IDs for dialogue)
  * `Mindset` (Holds current mood integers and active Thought objects)
  * `Personality` (An Enum used to select the correct CFG dictionary for dialogue generation)

* **Core Systems:**
  * `MovementSystem`: Checks collision and updates `Position`. Detects crossing interior/exterior thresholds and traversing stairs (Z-axis).
  * `VisibilitySystem`: Calculates FOV and LOS. Handles occlusion when transitioning between multi-tile structure interiors, exteriors, and different floors.
  * `CombatSystem`: Resolves skill use, applies damage, triggers death states.
  * `RenderSystem`: Interfaces directly with **BearLibTerminal**. Draws the map (handling Z-level occlusion and interior layers), then entities, then UI.
  * `TurnManagementSystem`: Tracks energy/speed to determine which entity acts next.
  * `FactManager`: A central registry of all generated Facts in the world (NPCs only store IDs).
  * `DialogueSystem`: Takes a Fact ID, Mindset, and Personality Enum, passes it to the CFG library (like `tracery`), and outputs the final text.