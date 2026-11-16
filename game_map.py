"""GameMap and Tile data structures for local map representation.

Follows the architectural guidelines of strict separation between Data and Systems.
Supports 3D multi-level grids (200x200 per Z-level), room ID tagging,
structure footprints, doors, and transparency arrays for fast FOV math.
"""

from dataclasses import dataclass
import numpy as np

from components import StructureFootprint


@dataclass
class Tile:
    """Represents an individual map cell in the local grid with optional room_id."""

    walkable: bool = True
    transparent: bool = True
    char: str = "."
    color: str = "gray"
    room_id: int | None = None
    building_id: str | int | None = None
    explored: bool = False
    movement_cost: int = 1
    is_hard: bool = False
    has_canopy: bool = False
    tree_species: str | None = None

    @classmethod
    def floor(
        cls,
        room_id: int | None = None,
        building_id: str | int | None = None,
        movement_cost: int = 1,
        is_hard: bool = False,
        char: str = ".",
        color: str = "gray",
    ) -> "Tile":
        """Create a standard walkable, transparent floor tile with movement cost 1."""
        return cls(
            walkable=True,
            transparent=True,
            char=char,
            color=color,
            room_id=room_id,
            building_id=building_id,
            explored=False,
            movement_cost=movement_cost,
            is_hard=is_hard,
        )

    @classmethod
    def hard_floor(
        cls,
        room_id: int | None = None,
        building_id: str | int | None = None,
        movement_cost: int = 3,
        char: str = "~",
        color: str = "dark yellow",
    ) -> "Tile":
        """Create a difficult/hard terrain floor tile with higher movement cost."""
        return cls(
            walkable=True,
            transparent=True,
            char=char,
            color=color,
            room_id=room_id,
            building_id=building_id,
            explored=False,
            movement_cost=movement_cost,
            is_hard=True,
        )

    @classmethod
    def rock(
        cls,
        walkable: bool = True,
        transparent: bool = True,
        movement_cost: int = 1,
        char: str = "*",
        color: str = "gray",
    ) -> "Tile":
        """Create a rock terrain tile."""
        return cls(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            movement_cost=movement_cost,
        )

    @classmethod
    def tall_grass(
        cls,
        walkable: bool = True,
        transparent: bool = True,
        movement_cost: int = 1,
        char: str = '"',
        color: str = "green",
    ) -> "Tile":
        """Create a tall grass terrain tile."""
        return cls(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            movement_cost=movement_cost,
        )

    @classmethod
    def reeds(
        cls,
        walkable: bool = True,
        transparent: bool = True,
        movement_cost: int = 1,
        char: str = "|",
        color: str = "dark green",
    ) -> "Tile":
        """Create a reeds terrain tile found along brooks and high moisture areas."""
        return cls(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            movement_cost=movement_cost,
        )

    @classmethod
    def thick_grass(
        cls,
        walkable: bool = True,
        transparent: bool = True,
        movement_cost: int = 1,
        char: str = ",",
        color: str = "green",
    ) -> "Tile":
        """Create a thick grass terrain tile found in medium moisture bands."""
        return cls(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            movement_cost=movement_cost,
        )

    @classmethod
    def sparse_grass(
        cls,
        walkable: bool = True,
        transparent: bool = True,
        movement_cost: int = 1,
        char: str = ".",
        color: str = "green",
    ) -> "Tile":
        """Create a sparse grass terrain tile found in low moisture bands."""
        return cls(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            movement_cost=movement_cost,
        )

    @classmethod
    def dirt(
        cls,
        walkable: bool = True,
        transparent: bool = True,
        movement_cost: int = 1,
        char: str = ".",
        color: str = "brown",
    ) -> "Tile":
        """Create a dirt / pure soil terrain tile found in extremely low moisture areas."""
        return cls(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            movement_cost=movement_cost,
        )

    @classmethod
    def tree_trunk(
        cls,
        walkable: bool = False,
        transparent: bool = False,
        char: str = "T",
        color: str = "brown",
        tree_species: str | None = None,
    ) -> "Tile":
        """Create a solid, blocking tree trunk tile with optional tree species."""
        return cls(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            movement_cost=1,
            has_canopy=False,
            tree_species=tree_species,
        )

    @classmethod
    def willow_trunk(
        cls,
        walkable: bool = False,
        transparent: bool = False,
        char: str = "T",
        color: str = "brown",
    ) -> "Tile":
        """Create a willow tree trunk tile found near water."""
        return cls.tree_trunk(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            tree_species="willow",
        )

    @classmethod
    def oak_trunk(
        cls,
        walkable: bool = False,
        transparent: bool = False,
        char: str = "T",
        color: str = "brown",
    ) -> "Tile":
        """Create an oak tree trunk tile found in sparse grass and open woodlands."""
        return cls.tree_trunk(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            tree_species="oak",
        )

    @classmethod
    def water(
        cls,
        walkable: bool = True,
        transparent: bool = True,
        movement_cost: int = 2,
        char: str = "~",
        color: str = "blue",
    ) -> "Tile":
        """Create a water tile (shallow pond or brook)."""
        return cls(
            walkable=walkable,
            transparent=transparent,
            char=char,
            color=color,
            movement_cost=movement_cost,
        )

    @classmethod
    def biome_floor(cls, biome) -> "Tile":
        """Create a ground tile matching the regional biome.

        - Forest: green '.'
        - Desert: yellow '~'
        - Plains: green '.'
        - Mountains: gray '*'
        """
        b_name = biome.value if hasattr(biome, "value") else str(biome)
        b_lower = b_name.lower()
        if "desert" in b_lower:
            return cls.hard_floor(char="~", color="yellow", movement_cost=2)
        elif "forest" in b_lower:
            return cls.floor(char=".", color="green")
        elif "mountain" in b_lower:
            return cls.rock(char="*", color="gray")
        elif "plain" in b_lower:
            return cls.floor(char=".", color="green")
        else:
            return cls.floor(char=".", color="gray")

    @classmethod
    def wall(cls, room_id: int | None = None, building_id: str | int | None = None) -> "Tile":
        """Create a solid, non-transparent wall tile."""
        return cls(walkable=False, transparent=False, char="#", color="white", room_id=room_id, building_id=building_id, explored=False, movement_cost=1)

    @classmethod
    def closed_door(cls, room_id: int | None = None, building_id: str | int | None = None) -> "Tile":
        """Create a closed door tile (blocks movement and FOV)."""
        return cls(walkable=False, transparent=False, char="+", color="white", room_id=room_id, building_id=building_id, explored=False, movement_cost=1)

    @classmethod
    def open_door(cls, room_id: int | None = None, building_id: str | int | None = None) -> "Tile":
        """Create an open door tile (allows movement and FOV)."""
        return cls(walkable=True, transparent=True, char="/", color="gray", room_id=room_id, building_id=building_id, explored=False, movement_cost=1)


class _ExploredDict(dict):
    """Dictionary mapping Z-level to 2D boolean numpy array, auto-generating levels on demand."""

    def __init__(self, game_map: "GameMap") -> None:
        super().__init__()
        self._game_map = game_map

    def __getitem__(self, z: int) -> np.ndarray:
        if z not in self:
            self._game_map.generate_level(z)
        return super().__getitem__(z)


class GameMap:
    """Manages the multi-level grid of tiles for the local map (200x200)."""

    def __init__(self, width: int = 200, height: int = 200) -> None:
        self.width = width
        self.height = height
        # Maps z-level (int) -> 2D array [x][y] of Tile
        self.tiles: dict[int, list[list[Tile]]] = {}
        # Explored boolean grid per Z-level (dict of 2D numpy boolean arrays)
        self.explored: dict[int, np.ndarray] = _ExploredDict(self)
        # Registered structure footprints
        self.structures: list[StructureFootprint] = []
        # Discovered buildings (buildings where at least one part has been seen)
        self.discovered_buildings: set[str | int] = set()
        # Cache for 2D numpy boolean transparency arrays per Z-level
        self._transparency_cache: dict[int, np.ndarray] = {}
        # Canopy boolean grid per Z-level (dict of 2D numpy boolean arrays)
        self.canopy: dict[int, np.ndarray] = {}

        # Fill Z-level 0 with generic floor tiles ('.') and boundary walls ('#')
        self.generate_level(0)

    def generate_level(self, z: int) -> None:
        """Generate a 200x200 level filled with floor tiles and boundary walls."""
        level: list[list[Tile]] = [
            [
                Tile.wall(room_id=None) if (x == 0 or x == self.width - 1 or y == 0 or y == self.height - 1)
                else Tile.floor(room_id=None)
                for y in range(self.height)
            ]
            for x in range(self.width)
        ]
        self.tiles[z] = level
        self.explored[z] = np.zeros((self.width, self.height), dtype=bool)
        self.canopy[z] = np.zeros((self.width, self.height), dtype=bool)

        # Invalidate transparency cache for this level
        if z in self._transparency_cache:
            del self._transparency_cache[z]

    def create_structure(
        self,
        x: int,
        y: int,
        width: int = 5,
        height: int = 5,
        z: int = 0,
        door_x: int | None = None,
        door_y: int | None = None,
        name: str = "Building",
        room_id: int | None = 1,
        building_id: str | int | None = None,
        door_is_open: bool = False,
    ) -> StructureFootprint:
        """Carve a rectangular structure with perimeter walls, floor interior, and an open/closed door."""
        if building_id is None:
            building_id = name

        footprint = StructureFootprint(
            x=x, y=y, width=width, height=height, z=z, name=name, room_id=room_id, building_id=building_id
        )

        if door_x is None:
            door_x = x + width // 2
        if door_y is None:
            door_y = y + height - 1

        for bx in range(x, x + width):
            for by in range(y, y + height):
                # Perimeter of the structure
                if bx == x or bx == x + width - 1 or by == y or by == y + height - 1:
                    if bx == door_x and by == door_y:
                        # Doorway: place open or closed door tagged with room_id and building_id
                        if door_is_open:
                            self.set_tile(bx, by, z, Tile.open_door(room_id=room_id, building_id=building_id))
                        else:
                            self.set_tile(bx, by, z, Tile.closed_door(room_id=room_id, building_id=building_id))
                    else:
                        # Wall tile tagged with room_id and building_id
                        self.set_tile(bx, by, z, Tile.wall(room_id=room_id, building_id=building_id))
                else:
                    # Interior floor tile tagged with room_id and building_id
                    self.set_tile(bx, by, z, Tile.floor(room_id=room_id, building_id=building_id))

        self.structures.append(footprint)
        return footprint

    def get_structure_at(self, x: int, y: int, z: int) -> StructureFootprint | None:
        """Find the structure footprint covering (x, y, z), if any."""
        for s in self.structures:
            if s.contains(x, y, z):
                return s
        return None

    def get_building_id_at(self, x: int, y: int, z: int) -> str | int | None:
        """Return the building identifier for coordinates (x, y, z), if any."""
        tile = self.get_tile(x, y, z)
        if tile is not None and tile.building_id is not None:
            return tile.building_id
        footprint = self.get_structure_at(x, y, z)
        if footprint is not None:
            return footprint.building_id
        return None

    def get_building_id_for_room(self, room_id: int, z: int | None = None) -> str | int | None:
        """Return the building identifier for a given room_id."""
        for s in self.structures:
            if s.room_id == room_id and (z is None or s.z == z):
                return s.building_id
        return None

    def get_building_rooms(self, building_id: str | int) -> set[int]:
        """Return the set of room_ids that belong to the given building."""
        rooms = set()
        for s in self.structures:
            if s.building_id == building_id and s.room_id is not None:
                rooms.add(s.room_id)
        return rooms

    def are_rooms_in_same_building(self, room_a: int | None, room_b: int | None) -> bool:
        """Check if two room_ids belong to the same building."""
        if room_a is None or room_b is None:
            return False
        if room_a == room_b:
            return True
        b_a = self.get_building_id_for_room(room_a)
        b_b = self.get_building_id_for_room(room_b)
        if b_a is not None and b_b is not None:
            return b_a == b_b
        return False

    def get_room_footprints(self, room_id: int, z: int | None = None) -> list[StructureFootprint]:
        """Find all structure footprints matching room_id on Z-level."""
        return [
            s for s in self.structures
            if s.room_id == room_id and (z is None or s.z == z)
        ]

    def is_building_discovered(self, building_id: str | int) -> bool:
        """Return True if at least one part of this building has been seen by the player."""
        return building_id in self.discovered_buildings

    def discover_building(self, building_id: str | int) -> None:
        """Mark a building as discovered."""
        self.discovered_buildings.add(building_id)

    def is_outer_wall(self, x: int, y: int, z: int) -> bool:
        """Return True if (x, y, z) is an outer perimeter wall of a building."""
        tile = self.get_tile(x, y, z)
        if tile is None or tile.char != "#":
            return False

        bldg = tile.building_id or self.get_building_id_at(x, y, z)
        if bldg is None and tile.room_id is None:
            return False

        # Check 4 cardinal neighbors - if any neighbor is exterior/different building, it's an outer wall
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = x + dx, y + dy
            if not self.in_bounds(nx, ny):
                return True
            n_tile = self.get_tile(nx, ny, z)
            if n_tile is None:
                return True
            n_bldg = n_tile.building_id or self.get_building_id_at(nx, ny, z)
            if n_bldg != bldg or n_tile.room_id is None:
                return True
        return False

    def in_bounds(self, x: int, y: int) -> bool:
        """Check whether (x, y) coordinates fall within the map dimensions."""
        return 0 <= x < self.width and 0 <= y < self.height

    def get_tile(self, x: int, y: int, z: int) -> Tile | None:
        """Return the Tile at (x, y, z), generating the Z-level on demand if absent."""
        if not self.in_bounds(x, y):
            return None
        if z not in self.tiles:
            self.generate_level(z)
        return self.tiles[z][x][y]

    def set_tile(self, x: int, y: int, z: int, tile: Tile) -> None:
        """Set a Tile at specified (x, y, z) coordinates."""
        if not self.in_bounds(x, y):
            return
        if z not in self.tiles:
            self.generate_level(z)
        self.tiles[z][x][y] = tile
        if z in self._transparency_cache:
            del self._transparency_cache[z]

    def get_movement_cost(self, x: int, y: int, z: int) -> int:
        """Return the movement cost of the tile at (x, y, z), defaulting to 1."""
        tile = self.get_tile(x, y, z)
        return tile.movement_cost if tile is not None else 1

    def is_hard_terrain(self, x: int, y: int, z: int) -> bool:
        """Return True if the tile at (x, y, z) is considered hard terrain."""
        tile = self.get_tile(x, y, z)
        if tile is None:
            return False
        return tile.is_hard or tile.movement_cost > 1

    def is_walkable(self, x: int, y: int, z: int) -> bool:
        """Return True if coordinates exist in-bounds and the tile is walkable."""
        if not self.in_bounds(x, y):
            return False
        tile = self.get_tile(x, y, z)
        return tile is not None and tile.walkable

    def has_canopy(self, x: int, y: int, z: int = 0, check_overhead: bool = True) -> bool:
        """Return True if there is tree canopy / leaf coverage at (x, y, z) or directly overhead."""
        if not self.in_bounds(x, y):
            return False
        # 1. Check exact Z-level
        if z in self.canopy and self.canopy[z][x, y]:
            return True
        tile = self.get_tile(x, y, z)
        if tile is not None and tile.has_canopy:
            return True
        # 2. Check upper Z-levels overhead (multi-Z tree canopies 1 or 2 levels above)
        if check_overhead:
            for up in (1, 2):
                uz = z + up
                if uz in self.canopy and self.canopy[uz][x, y]:
                    return True
                if uz in self.tiles and self.tiles[uz][x][y].has_canopy:
                    return True
        return False

    def has_canopy_at_level(self, x: int, y: int, z: int = 0) -> bool:
        """Return True only if tree canopy / leaf coverage exists strictly at (x, y, z)."""
        return self.has_canopy(x, y, z, check_overhead=False)

    def set_canopy(self, x: int, y: int, z: int = 0, value: bool = True) -> None:
        """Set whether tree canopy / leaf coverage exists at (x, y, z)."""
        if not self.in_bounds(x, y):
            return
        if z not in self.canopy:
            self.generate_level(z)
        self.canopy[z][x, y] = value
        tile = self.get_tile(x, y, z)
        if tile is not None:
            tile.has_canopy = value

    def get_canopy_array(self, z: int) -> np.ndarray:
        """Return the 2D boolean numpy array of canopy coverage for a Z-level."""
        if z not in self.canopy:
            self.generate_level(z)
        return self.canopy[z]

    def is_transparent(self, x: int, y: int, z: int) -> bool:
        """Return True if coordinates exist in-bounds and the tile is transparent."""
        if not self.in_bounds(x, y):
            return False
        tile = self.get_tile(x, y, z)
        return tile is not None and tile.transparent

    def get_transparency_array(self, z: int) -> np.ndarray:
        """Return a 2D boolean numpy array (width, height, order='F') of tile transparency for FOV."""
        if z not in self.tiles:
            self.generate_level(z)

        if z not in self._transparency_cache:
            level = self.tiles[z]
            arr = np.zeros((self.width, self.height), dtype=bool, order="F")
            for x in range(self.width):
                for y in range(self.height):
                    arr[x, y] = level[x][y].transparent
            self._transparency_cache[z] = arr

        return self._transparency_cache[z]

    def invalidate_transparency_cache(self, z: int | None = None) -> None:
        """Invalidate the cached transparency array for a level (or all levels)."""
        if z is None:
            self._transparency_cache.clear()
        elif z in self._transparency_cache:
            del self._transparency_cache[z]

    def is_explored(self, x: int, y: int, z: int) -> bool:
        """Return True if coordinates exist in-bounds and the tile has been explored."""
        if not self.in_bounds(x, y):
            return False
        if z not in self.explored:
            self.generate_level(z)
        return bool(self.explored[z][x, y])

    def set_explored(self, x: int, y: int, z: int, explored: bool = True) -> None:
        """Set the explored status for a tile at specified (x, y, z) coordinates."""
        if not self.in_bounds(x, y):
            return
        if z not in self.explored:
            self.generate_level(z)
        self.explored[z][x, y] = explored
        if z in self.tiles:
            self.tiles[z][x][y].explored = explored

    def mark_explored_batch(self, z: int, mask: np.ndarray) -> None:
        """Batch mark tiles as explored on Z-level using a 2D boolean mask."""
        if z not in self.explored:
            self.generate_level(z)
        self.explored[z] |= mask
        if z in self.tiles:
            xs, ys = np.where(mask)
            level_tiles = self.tiles[z]
            for x, y in zip(xs, ys):
                if 0 <= x < self.width and 0 <= y < self.height:
                    level_tiles[x][y].explored = True

    def get_explored_array(self, z: int) -> np.ndarray:
        """Return the 2D boolean numpy array of explored tiles for a Z-level."""
        if z not in self.explored:
            self.generate_level(z)
        return self.explored[z]

    def __getitem__(self, coords: tuple[int, int, int]) -> Tile | None:
        x, y, z = coords
        return self.get_tile(x, y, z)

    def __setitem__(self, coords: tuple[int, int, int], tile: Tile) -> None:
        x, y, z = coords
        self.set_tile(x, y, z, tile)
