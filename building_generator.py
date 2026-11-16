"""Building generation using networkx graph representations and room prefabs.

Implements Section 3.2 of the GDD: Graph-Based Building Generation.
Constructs multi-level structure graphs, resolves spatial positions, and stamps
prefabs into the GameMap with room ID tagging and staircase Z-level connections.
"""

from dataclasses import dataclass, field
import networkx as nx

from components import StructureFootprint
from game_map import GameMap, Tile


@dataclass
class RoomPrefab:
    """Represents a 2D tile template for an individual room."""

    name: str
    layout: list[str]
    connectors: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def height(self) -> int:
        """Number of rows in the prefab."""
        return len(self.layout)

    @property
    def width(self) -> int:
        """Number of columns in the prefab."""
        return len(self.layout[0]) if self.layout else 0


# --- Hardcoded Room Prefabs ---

# Node A: Main Room (Z=0, 8 wide x 7 high)
# - local (5, 2): Stairs up to Bedrooms ('<')
# - local (7, 3): Door to Kitchen ('+')
# - local (3, 6): Exterior entrance door ('+')
# - local (2, 3): World spawn at (100, 100) when anchored at (98, 97)
MAIN_ROOM_PREFAB = RoomPrefab(
    name="Main Room",
    layout=[
        "########",  # y=0: North wall
        "#......#",  # y=1: Interior floor
        "#....<.#",  # y=2: Stairs up at local (5, 2)
        "#......+",  # y=3: Door to Kitchen on East wall at local (7, 3)
        "#......#",  # y=4: Interior floor
        "#......#",  # y=5: Interior floor
        "###+####",  # y=6: Exterior door on South wall at local (3, 6)
    ],
    connectors={
        "exterior_door": (3, 6),
        "kitchen_door": (7, 3),
        "stairs_up": (5, 2),
    },
)

# Node B: Kitchen (Z=0, 6 wide x 6 high)
# - local (0, 3): Door to Main Room on West wall ('+')
KITCHEN_PREFAB = RoomPrefab(
    name="Kitchen",
    layout=[
        "######",  # y=0: North wall
        "#....#",  # y=1: Interior floor
        "#....#",  # y=2: Interior floor
        "+....#",  # y=3: Door to Main Room on West wall at local (0, 3)
        "#....#",  # y=4: Interior floor
        "######",  # y=5: South wall
    ],
    connectors={
        "main_room_door": (0, 3),
    },
)

# Node C: Bedrooms (Z=1, 8 wide x 7 high)
# - local (5, 2): Stairs down to Main Room ('>'), aligned with '<' at Z=0
# - local (2, 3): Interior partition door ('+')
BEDROOMS_PREFAB = RoomPrefab(
    name="Bedrooms",
    layout=[
        "########",  # y=0: North wall
        "#...#..#",  # y=1: Partition wall
        "#...#>.#",  # y=2: Stairs down at local (5, 2)
        "#...#..#",  # y=3: Floor at local (2, 3) -> (100, 100, 1) is floor
        "#...#..#",  # y=4: Partition door at local (2, 4)
        "#...+..#",  # y=5: Hallway floor
        "########",  # y=6: South wall
    ],
    connectors={
        "stairs_down": (5, 2),
        "partition_door": (4, 5),
    },
)


class BuildingGraph:
    """Manages the logical graph topology of a building using networkx."""

    def __init__(self, name: str = "Building", building_id: str | None = None) -> None:
        self.name = name
        self.building_id = building_id if building_id is not None else name
        self.graph = nx.Graph()

    def add_room(
        self,
        node_id: str,
        name: str,
        z: int,
        room_id: int,
        prefab: RoomPrefab,
        offset: tuple[int, int] = (0, 0),
    ) -> None:
        """Add a room node with spatial attributes to the building graph."""
        self.graph.add_node(
            node_id,
            name=name,
            z=z,
            room_id=room_id,
            prefab=prefab,
            offset=offset,
        )

    def add_connection(
        self,
        node_a: str,
        node_b: str,
        connection_type: str,
        connector_a: str | None = None,
        connector_b: str | None = None,
    ) -> None:
        """Add an edge representing a connection (e.g. door or staircase) between rooms."""
        self.graph.add_edge(
            node_a,
            node_b,
            connection_type=connection_type,
            connector_a=connector_a,
            connector_b=connector_b,
        )

    def get_room(self, node_id: str) -> dict:
        """Return the dictionary of attributes for a room node."""
        return self.graph.nodes[node_id]

    def nodes(self):
        """Iterate over all room nodes with their attribute dicts."""
        return self.graph.nodes(data=True)

    def edges(self):
        """Iterate over all edges with their connection attribute dicts."""
        return self.graph.edges(data=True)


def create_tavern_graph() -> BuildingGraph:
    """Generate a 3-node graph representing a 'Tavern'.

    - Node A is 'Main Room' (Z=0).
    - Node B is 'Kitchen' (Z=0).
    - Node C is 'Bedrooms' (Z=1).
    - Edge A->B is a door.
    - Edge A->C is a staircase.
    """
    bg = BuildingGraph(name="Tavern")

    # Node A: Main Room (Z=0), anchored at (0, 0)
    bg.add_room(
        node_id="A",
        name="Main Room",
        z=0,
        room_id=1,
        prefab=MAIN_ROOM_PREFAB,
        offset=(0, 0),
    )

    # Node B: Kitchen (Z=0), placed adjacent to East wall of Main Room (offset x = 7)
    bg.add_room(
        node_id="B",
        name="Kitchen",
        z=0,
        room_id=2,
        prefab=KITCHEN_PREFAB,
        offset=(7, 0),
    )

    # Node C: Bedrooms (Z=1), directly above Main Room
    bg.add_room(
        node_id="C",
        name="Bedrooms",
        z=1,
        room_id=3,
        prefab=BEDROOMS_PREFAB,
        offset=(0, 0),
    )

    # Edge A->B: Door connection
    bg.add_connection(
        "A",
        "B",
        connection_type="door",
        connector_a="kitchen_door",
        connector_b="main_room_door",
    )

    # Edge A->C: Staircase connection
    bg.add_connection(
        "A",
        "C",
        connection_type="staircase",
        connector_a="stairs_up",
        connector_b="stairs_down",
    )

    return bg


def stamp_building_graph(
    building_graph: BuildingGraph,
    game_map: GameMap,
    anchor_x: int = 98,
    anchor_y: int = 97,
) -> dict:
    """Resolves room positions on the GameMap and stamps prefabs into the grid.

    Connects rooms via stairs on the Z-axis, assigns room_id to stamped tiles,
    registers StructureFootprint instances, and returns metadata including
    doors to spawn and the player's spawn position inside the Main Room.
    """
    resolved_rooms: dict[str, dict] = {}
    doors_to_spawn: list[tuple[int, int, int]] = []
    footprints: list[StructureFootprint] = []

    # Player spawn inside Main Room at local (2, 3) -> (anchor_x + 2, anchor_y + 3)
    player_spawn = (anchor_x + 2, anchor_y + 3, 0)
    building_id = getattr(building_graph, "building_id", building_graph.name)

    for node_id, data in building_graph.nodes():
        prefab: RoomPrefab = data["prefab"]
        offset_x, offset_y = data["offset"]
        room_z: int = data["z"]
        room_id: int = data["room_id"]
        room_name: str = data["name"]

        room_x = anchor_x + offset_x
        room_y = anchor_y + offset_y

        # Stamp prefab tiles into the game map grid
        for ly, row in enumerate(prefab.layout):
            for lx, char in enumerate(row):
                gx = room_x + lx
                gy = room_y + ly

                if char == "#":
                    tile = Tile.wall(room_id=room_id, building_id=building_id)
                elif char == ".":
                    tile = Tile.floor(room_id=room_id, building_id=building_id)
                elif char == "+":
                    tile = Tile.closed_door(room_id=room_id, building_id=building_id)
                    doors_to_spawn.append((gx, gy, room_z))
                elif char == "<":
                    # Staircase leading UP to upper floor
                    tile = Tile(
                        walkable=True,
                        transparent=True,
                        char="<",
                        color="white",
                        room_id=room_id,
                        building_id=building_id,
                    )
                elif char == ">":
                    # Staircase leading DOWN to lower floor
                    tile = Tile(
                        walkable=True,
                        transparent=True,
                        char=">",
                        color="white",
                        room_id=room_id,
                        building_id=building_id,
                    )
                else:
                    tile = Tile.floor(room_id=room_id, building_id=building_id)

                game_map.set_tile(gx, gy, room_z, tile)

        # Register structure footprint for occlusion tracking
        footprint = StructureFootprint(
            x=room_x,
            y=room_y,
            width=prefab.width,
            height=prefab.height,
            z=room_z,
            name=room_name,
            room_id=room_id,
            building_id=building_id,
        )
        game_map.structures.append(footprint)
        footprints.append(footprint)

        resolved_rooms[node_id] = {
            "name": room_name,
            "x": room_x,
            "y": room_y,
            "z": room_z,
            "width": prefab.width,
            "height": prefab.height,
            "room_id": room_id,
            "footprint": footprint,
        }

    # Deduplicate door coordinates (e.g. shared wall doorways between rooms)
    unique_doors = list(dict.fromkeys(doors_to_spawn))

    return {
        "building_name": building_graph.name,
        "resolved_rooms": resolved_rooms,
        "doors_to_spawn": unique_doors,
        "footprints": footprints,
        "player_spawn": player_spawn,
    }


if __name__ == "__main__":
    # Standalone verification script
    print("Generating Tavern BuildingGraph...")
    tavern = create_tavern_graph()
    print(f"Building: {tavern.name}")
    print(f"Nodes ({len(tavern.graph.nodes)}):")
    for nid, d in tavern.nodes():
        print(f"  [{nid}] {d['name']} (Z={d['z']}, room_id={d['room_id']}) - {d['prefab'].width}x{d['prefab'].height}")
    print(f"Edges ({len(tavern.graph.edges)}):")
    for u, v, d in tavern.edges():
        print(f"  {u} <--> {v}: {d['connection_type']}")

    print("\nStamping into GameMap...")
    test_map = GameMap(width=200, height=200)
    result = stamp_building_graph(tavern, test_map, anchor_x=98, anchor_y=97)
    print("Resolved Rooms:")
    for nid, r in result["resolved_rooms"].items():
        print(f"  Room [{nid}] '{r['name']}': at ({r['x']}, {r['y']}, {r['z']}) footprint {r['width']}x{r['height']}")
    print(f"Doors to spawn ({len(result['doors_to_spawn'])}): {result['doors_to_spawn']}")
    print(f"Player spawn: {result['player_spawn']}")
