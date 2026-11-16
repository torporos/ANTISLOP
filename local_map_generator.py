"""Local Map Generator module for wilderness/tactical maps.

Refined implementation following strict Game Design Document rules:
- Continuous Brooks: Carves a continuous, unbroken path from one edge to the opposite edge
  using a cubic Bezier curve with Bresenham rasterization, 2 to 3 tiles wide. Zero noise water.
- Strict Ground Tiles: Only places rocks/stones if the inherited Regional Biome is strictly
  'Mountains' or 'Badlands'. Otherwise base ground is pure soil/grass ('.' and ',') colored for biome.
  Distance > 30 dirt is removed; terrain at distance >= 11 remains sparse grass ('.').
- Moisture Bands & Vegetation:
  - Distance 1-3 (High Moisture): Dense tall grass ('"') and Reeds ('|').
  - Distance 4-10 (Medium Moisture): Thick grass (',').
  - Distance >= 11 (Low Moisture): Sparse grass ('.').
- Tree Species (Willow and Oak):
  - Willows grow near water (High to early Medium moisture).
  - Oaks grow across the landscape, even in sparse grass.
- Herb Ecological Preferences:
  - Each herb has its preferred environment: moisture range and proximity to a specific tree species.
  - Kingsfoil: High/Medium moisture, thrives near Willows.
  - Bloodweed: High moisture riverbanks, thrives beneath Willows.
  - Silverleaf: Medium/Low moisture, thrives near Oaks in grassland.
  - Earthroot: Low moisture / sparse grass, clings to soil near Oaks.
  - 10 to 15 herbs scattered across their preferred environments as ECS Item entities.
- Tree Placement: NEVER spawns tree trunk inside the brook or on top of an herb.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple
import numpy as np

try:
    from opensimplex import OpenSimplex
    _HAS_OPENSIMPLEX = True
except ImportError:
    _HAS_OPENSIMPLEX = False

try:
    import noise
    _HAS_NOISE = True
except ImportError:
    _HAS_NOISE = False

try:
    import scipy.ndimage as ndi
    _HAS_SCIPY_NDI = True
except ImportError:
    _HAS_SCIPY_NDI = False

import esper

from components import Item, Name, Position, RenderOrder, Renderable
from game_map import GameMap, Tile
from regional_map_generator import BiomeType, RegionalTile


class TreeSpecies(str, Enum):
    """Different species of trees."""

    WILLOW = "willow"
    OAK = "oak"


@dataclass
class PlacedTree:
    """Metadata for a placed tree."""

    x: int
    y: int
    base_z: int
    species: str
    height: int = 1
    canopy_radius: int = 1


@dataclass(frozen=True)
class HerbTemplate:
    """Template for interactable herb item entities with ecological habitat preferences."""

    name: str
    char: str
    color: str
    description: str
    preferred_tree_species: str  # "willow" or "oak"
    min_water_dist: int  # minimum distance from water
    max_water_dist: int  # maximum distance from water
    max_tree_dist: int = 4  # maximum Chebyshev distance from a preferred tree species
    weight: float = 0.1


HERB_POOL: list[HerbTemplate] = [
    HerbTemplate(
        name="Kingsfoil",
        char="*",
        color="bright green",
        description="A soothing medicinal herb with fragrant leaves, flourishing in damp riverbank soil near weeping willows.",
        preferred_tree_species=TreeSpecies.WILLOW.value,
        min_water_dist=1,
        max_water_dist=6,
        max_tree_dist=4,
        weight=0.1,
    ),
    HerbTemplate(
        name="Bloodweed",
        char="v",
        color="red",
        description="A crimson wild weed prized for its potent sap, thriving in waterlogged marshy soil beneath willows.",
        preferred_tree_species=TreeSpecies.WILLOW.value,
        min_water_dist=1,
        max_water_dist=4,
        max_tree_dist=3,
        weight=0.1,
    ),
    HerbTemplate(
        name="Silverleaf",
        char="v",
        color="light cyan",
        description="A delicate pale silver herb that sprouts under the sturdy shelter of oak trees in open grassland.",
        preferred_tree_species=TreeSpecies.OAK.value,
        min_water_dist=7,
        max_water_dist=30,
        max_tree_dist=4,
        weight=0.1,
    ),
    HerbTemplate(
        name="Earthroot",
        char="*",
        color="amber",
        description="A rugged root clinging to firm, dry soil among the roots of mature oaks in sparse grass.",
        preferred_tree_species=TreeSpecies.OAK.value,
        min_water_dist=11,
        max_water_dist=50,
        max_tree_dist=4,
        weight=0.2,
    ),
]


def _bresenham_line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Generate contiguous integer coordinates along a line using Bresenham's algorithm."""
    points: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    cx, cy = x0, y0
    while True:
        points.append((cx, cy))
        if cx == x1 and cy == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy
    return points


class LocalMapGenerator:
    """Generates 200x200 tactical local maps inheriting data from RegionalTile."""

    def __init__(
        self,
        width: int = 200,
        height: int = 200,
        regional_tile: RegionalTile | None = None,
        seed: int | None = None,
        elevation_scale: float = 0.035,
        moisture_scale: float = 0.035,
        elevation_threshold: float = 0.65,
        moisture_threshold: float = 0.72,
        tree_moisture_threshold: float = 0.70,
        tree_density: float = 0.08,
        canopy_radius: int = 1,
    ) -> None:
        self.width = width
        self.height = height
        self.regional_tile = regional_tile if regional_tile is not None else RegionalTile(
            biome=BiomeType.PLAINS,
            base_elevation=0,
            base_moisture=0.5,
        )
        self.base_z = int(self.regional_tile.base_elevation)
        if seed is not None:
            self.seed = seed
        elif regional_tile is not None and getattr(regional_tile, "seed", None) is not None:
            self.seed = regional_tile.seed
        else:
            self.seed = 1337
        self.elevation_scale = elevation_scale
        self.moisture_scale = moisture_scale
        self.elevation_threshold = elevation_threshold
        self.moisture_threshold = moisture_threshold
        self.tree_moisture_threshold = tree_moisture_threshold
        self.tree_density = tree_density
        self.canopy_radius = canopy_radius

        self.elevation_map: np.ndarray | None = None
        self.moisture_map: np.ndarray | None = None
        self.distance_map: np.ndarray | None = None
        self.water_tiles: set[tuple[int, int]] = set()

        self.placed_trees: list[PlacedTree] = []
        self.tree_tiles: dict[tuple[int, int], str] = {}  # maps (x, y) -> species

        self.herb_spawns: list[tuple[int, int, int, HerbTemplate]] = []
        self.herb_tiles: set[tuple[int, int]] = set()

    def _generate_raw_noise(self, seed: int, scale: float) -> np.ndarray:
        """Generate a 2D raw noise array in range [-1.0, 1.0]."""
        if _HAS_OPENSIMPLEX:
            gen = OpenSimplex(seed)
            xs = np.arange(self.width) * scale
            ys = np.arange(self.height) * scale
            return gen.noise2array(xs, ys)
        elif _HAS_NOISE:
            raw = np.zeros((self.width, self.height), dtype=float)
            for x in range(self.width):
                for y in range(self.height):
                    raw[x, y] = noise.pnoise2(
                        x * scale,
                        y * scale,
                        octaves=2,
                        base=seed % 1000,
                    )
            return raw
        else:
            xs, ys = np.meshgrid(np.arange(self.width), np.arange(self.height), indexing="ij")
            return np.sin(xs * scale + seed) * np.cos(ys * scale + seed * 0.7)

    def _generate_simplex_noise(self, seed: int, scale: float) -> np.ndarray:
        """Generate a 2D noise array normalized to [0.0, 1.0]."""
        raw = self._generate_raw_noise(seed, scale)
        min_val = float(raw.min())
        max_val = float(raw.max())
        if max_val - min_val > 1e-6:
            norm = (raw - min_val) / (max_val - min_val)
        else:
            norm = np.full((self.width, self.height), 0.5, dtype=float)
        return norm

    def carve_continuous_brook(
        self,
        game_map: GameMap,
        z: int,
        rng: np.random.Generator,
        clear_starting_area: bool = True,
    ) -> set[tuple[int, int]]:
        """Carve a continuous, unbroken brook from one edge of the map to the opposite edge.

        Uses a cubic Bezier curve with Bresenham line rasterization.
        Carves 2 to 3 tiles wide across the entire length of the map.
        NO noise is used to place water.
        """
        water_tiles: set[tuple[int, int]] = set()

        # Choose primary flow orientation: vertical (North-South) or horizontal (West-East)
        orientation = rng.choice(["vertical", "horizontal"])

        if orientation == "vertical":
            # Flow from North (y=0) to South (y=height-1)
            if clear_starting_area:
                side = rng.choice(["west", "east"])
                if side == "west":
                    start_x = float(rng.integers(15, 75))
                    end_x = float(rng.integers(15, 75))
                else:
                    start_x = float(rng.integers(125, 185))
                    end_x = float(rng.integers(125, 185))
            else:
                start_x = float(rng.integers(10, self.width - 10))
                end_x = float(rng.integers(10, self.width - 10))

            p0 = (start_x, 0.0)
            p3 = (end_x, float(self.height - 1))
            c1_x = float(np.clip(p0[0] + rng.uniform(-25, 25), 5, self.width - 6))
            c2_x = float(np.clip(p3[0] + rng.uniform(-25, 25), 5, self.width - 6))
            p1 = (c1_x, float(self.height) * 0.33)
            p2 = (c2_x, float(self.height) * 0.67)

        else:
            # Flow from West (x=0) to East (x=width-1)
            if clear_starting_area:
                side = rng.choice(["north", "south"])
                if side == "north":
                    start_y = float(rng.integers(15, 75))
                    end_y = float(rng.integers(15, 75))
                else:
                    start_y = float(rng.integers(125, 185))
                    end_y = float(rng.integers(125, 185))
            else:
                start_y = float(rng.integers(10, self.height - 10))
                end_y = float(rng.integers(10, self.height - 10))

            p0 = (0.0, start_y)
            p3 = (float(self.width - 1), end_y)
            c1_y = float(np.clip(p0[1] + rng.uniform(-25, 25), 5, self.height - 6))
            c2_y = float(np.clip(p3[1] + rng.uniform(-25, 25), 5, self.height - 6))
            p1 = (float(self.width) * 0.33, c1_y)
            p2 = (float(self.width) * 0.67, c2_y)

        # Sample Bezier curve points
        ts = np.linspace(0.0, 1.0, num=800)
        curve_pts: list[tuple[int, int]] = []
        for t in ts:
            inv_t = 1.0 - t
            bx = (
                (inv_t ** 3) * p0[0]
                + 3 * (inv_t ** 2) * t * p1[0]
                + 3 * inv_t * (t ** 2) * p2[0]
                + (t ** 3) * p3[0]
            )
            by = (
                (inv_t ** 3) * p0[1]
                + 3 * (inv_t ** 2) * t * p1[1]
                + 3 * inv_t * (t ** 2) * p2[1]
                + (t ** 3) * p3[1]
            )
            curve_pts.append((int(round(bx)), int(round(by))))

        # Connect consecutive samples with Bresenham's algorithm to ensure unbroken contiguous line
        path_tiles: list[tuple[int, int]] = []
        for i in range(len(curve_pts) - 1):
            segment = _bresenham_line(
                curve_pts[i][0],
                curve_pts[i][1],
                curve_pts[i + 1][0],
                curve_pts[i + 1][1],
            )
            if i > 0:
                segment = segment[1:]
            path_tiles.extend(segment)

        # Carve brook 2 to 3 tiles wide along the continuous path
        for cx, cy in path_tiles:
            w = int(rng.choice([2, 3]))
            if orientation == "vertical":
                offsets = [0, 1] if w == 2 else [-1, 0, 1]
                for off in offsets:
                    wx, wy = cx + off, cy
                    if 0 <= wx < self.width and 0 <= wy < self.height:
                        game_map.set_tile(wx, wy, z, Tile.water())
                        water_tiles.add((wx, wy))
            else:
                offsets = [0, 1] if w == 2 else [-1, 0, 1]
                for off in offsets:
                    wx, wy = cx, cy + off
                    if 0 <= wx < self.width and 0 <= wy < self.height:
                        game_map.set_tile(wx, wy, z, Tile.water())
                        water_tiles.add((wx, wy))

        self.water_tiles = water_tiles
        return water_tiles

    def generate_water_bodies(
        self,
        game_map: GameMap,
        z: int,
        seed: int | None = None,
        clear_starting_area: bool = True,
    ) -> set[tuple[int, int]]:
        """Generate a continuous brook on the base Z-level."""
        effective_seed = (seed if seed is not None else self.seed) + 9876
        rng = np.random.default_rng(effective_seed)
        return self.carve_continuous_brook(
            game_map=game_map,
            z=z,
            rng=rng,
            clear_starting_area=clear_starting_area,
        )

    def compute_distance_map(self, water_tiles: set[tuple[int, int]]) -> np.ndarray:
        """Compute the Chebyshev distance from each map coordinate to the nearest water tile."""
        if _HAS_SCIPY_NDI:
            grid = np.ones((self.width, self.height), dtype=bool)
            for wx, wy in water_tiles:
                if 0 <= wx < self.width and 0 <= wy < self.height:
                    grid[wx, wy] = False
            self.distance_map = ndi.distance_transform_cdt(grid, metric="chessboard")
            return self.distance_map

        # Fallback BFS for Chebyshev distance if scipy is unavailable
        dist_map = np.full((self.width, self.height), 9999, dtype=int)
        from collections import deque
        queue: deque[tuple[int, int]] = deque()
        for wx, wy in water_tiles:
            if 0 <= wx < self.width and 0 <= wy < self.height:
                dist_map[wx, wy] = 0
                queue.append((wx, wy))

        directions = [
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1),
        ]
        while queue:
            cx, cy = queue.popleft()
            cd = dist_map[cx, cy]
            for dx, dy in directions:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    if dist_map[nx, ny] > cd + 1:
                        dist_map[nx, ny] = cd + 1
                        queue.append((nx, ny))

        self.distance_map = dist_map
        return self.distance_map

    def generate_moisture_map(
        self,
        seed: int | None = None,
        water_tiles: set[tuple[int, int]] | None = None,
    ) -> np.ndarray:
        """Create a local Moisture Map derived strictly from distance to the continuous brook."""
        active_water = water_tiles if water_tiles is not None else self.water_tiles
        if self.distance_map is None:
            self.compute_distance_map(active_water)

        dist_map = self.distance_map if self.distance_map is not None else np.zeros((self.width, self.height))

        moisture = np.zeros((self.width, self.height), dtype=float)

        d0 = dist_map == 0
        d_high = (dist_map >= 1) & (dist_map <= 3)
        d_med = (dist_map >= 4) & (dist_map <= 10)
        d_low = dist_map >= 11

        moisture[d0] = 1.0
        moisture[d_high] = 0.92 - (dist_map[d_high] - 1) * 0.08
        moisture[d_med] = 0.68 - (dist_map[d_med] - 4) * 0.035
        moisture[d_low] = np.maximum(0.15, 0.44 - (dist_map[d_low] - 11) * 0.01)

        # Add a slight organic noise variation (+- 0.02)
        effective_seed = (seed if seed is not None else self.seed) + 4242
        raw_noise = self._generate_raw_noise(effective_seed, self.moisture_scale)
        moisture += raw_noise * 0.02
        moisture[d0] = 1.0

        self.moisture_map = np.clip(moisture, 0.0, 1.0)
        return self.moisture_map

    def generate_elevation_map(self, seed: int | None = None) -> np.ndarray:
        """Generate the 2D Elevation noise map."""
        effective_seed = seed if seed is not None else self.seed
        self.elevation_map = self._generate_simplex_noise(effective_seed, self.elevation_scale)
        return self.elevation_map

    def generate_noise_maps(
        self,
        seed: int | None = None,
        water_tiles: set[tuple[int, int]] | None = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generate and return both (Elevation, Moisture) maps."""
        elev = self.generate_elevation_map(seed)
        moist = self.generate_moisture_map(seed, water_tiles=water_tiles)
        return elev, moist

    def place_tree(
        self,
        game_map: GameMap,
        x: int,
        y: int,
        base_z: int = 0,
        height: int = 1,
        canopy_radius: int | None = None,
        z: int | None = None,
        tree_species: str | None = None,
    ) -> bool:
        """Place a Multi-Z tree of a specific species.

        Enforces strict placement rules:
        - NEVER spawns a tree trunk inside the brook (water tile).
        - NEVER spawns a tree trunk on top of an herb.
        Returns True if placed successfully, False otherwise.
        """
        actual_base_z = z if z is not None else base_z
        if not game_map.in_bounds(x, y):
            return False

        # 1. Map data check: NEVER inside the brook
        existing_tile = game_map.get_tile(x, y, actual_base_z)
        if existing_tile is not None and (existing_tile.char == "~" or (x, y) in self.water_tiles):
            return False

        # 2. Herb check: NEVER on top of an herb
        if (x, y) in self.herb_tiles:
            return False
        for _ent, (pos, _item) in esper.get_components(Position, Item):
            if pos.x == x and pos.y == y and pos.z == actual_base_z:
                return False

        # Determine tree species if not explicitly provided
        if tree_species is not None:
            species = tree_species
        elif self.distance_map is not None and self.distance_map[x, y] <= 6:
            species = TreeSpecies.WILLOW.value
        else:
            species = TreeSpecies.OAK.value

        radius = canopy_radius if canopy_radius is not None else self.canopy_radius
        tree_height = max(1, min(2, height))

        # Spawn tree trunk on base Z-level
        game_map.set_tile(x, y, actual_base_z, Tile.tree_trunk(tree_species=species))

        # Grow trunk UP 1 or 2 Z-levels
        for z_up in range(actual_base_z + 1, actual_base_z + tree_height + 1):
            game_map.set_tile(x, y, z_up, Tile.tree_trunk(tree_species=species))

        # Spread canopy/leaves on the upper Z-levels
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue  # Center is the trunk itself
                nx, ny = x + dx, y + dy
                if game_map.in_bounds(nx, ny):
                    for z_up in range(actual_base_z + 1, actual_base_z + tree_height + 1):
                        game_map.set_canopy(nx, ny, z_up, True)

        # Track placed tree
        placed = PlacedTree(
            x=x,
            y=y,
            base_z=actual_base_z,
            species=species,
            height=tree_height,
            canopy_radius=radius,
        )
        self.placed_trees.append(placed)
        self.tree_tiles[(x, y)] = species

        return True

    def generate_trees(
        self,
        game_map: GameMap,
        base_z: int,
        rng: np.random.Generator,
        clear_starting_area: bool = True,
    ) -> list[PlacedTree]:
        """Generate Multi-Z trees respecting species habitats:
        - Willows grow near water (distance 1 to 6).
        - Oaks grow across the landscape and sparse grass (distance >= 7).
        """
        dist_map = self.distance_map if self.distance_map is not None else np.zeros((self.width, self.height))
        elevation_map = self.elevation_map if self.elevation_map is not None else np.zeros((self.width, self.height))

        for x in range(2, self.width - 2):
            for y in range(2, self.height - 2):
                if (x, y) in self.water_tiles:
                    continue
                cur_tile = game_map.get_tile(x, y, base_z)
                if cur_tile is not None and (cur_tile.char == "~" or not cur_tile.walkable):
                    continue
                if (x, y) in self.herb_tiles:
                    continue
                if clear_starting_area and (89 <= x <= 116 and 84 <= y <= 116):
                    continue

                d = dist_map[x, y]
                elev = elevation_map[x, y]

                # Determine candidate species and spawn probability based on habitat
                if 1 <= d <= 6:
                    # Willows grow near water
                    species = TreeSpecies.WILLOW.value
                    spawn_prob = 0.08
                else:
                    # Oaks grow even in sparse grass
                    species = TreeSpecies.OAK.value
                    spawn_prob = 0.04

                # Avoid trees on steep rocky peaks
                if elev >= self.elevation_threshold:
                    continue

                if rng.random() < spawn_prob:
                    # Spacing: ensure at least 2 tiles between trunks
                    has_neighbor = any(
                        abs(x - t.x) <= 2 and abs(y - t.y) <= 2
                        for t in self.placed_trees
                    )
                    if not has_neighbor:
                        tree_height = int(rng.choice([1, 2]))
                        self.place_tree(
                            game_map=game_map,
                            x=x,
                            y=y,
                            base_z=base_z,
                            height=tree_height,
                            canopy_radius=self.canopy_radius,
                            tree_species=species,
                        )

        return self.placed_trees

    def generate_herb_spawns(
        self,
        game_map: GameMap,
        base_z: int = 0,
        seed: int | None = None,
        clear_starting_area: bool = True,
    ) -> list[tuple[int, int, int, HerbTemplate]]:
        """Scatter 10 to 15 interactable herbs across the map matching their preferred environments.

        Each herb has:
        - Moisture preference (min_water_dist to max_water_dist)
        - Proximity to a specific tree species (within max_tree_dist of that species)
        """
        if self.distance_map is None:
            self.compute_distance_map(self.water_tiles)

        dist_map = self.distance_map if self.distance_map is not None else np.zeros((self.width, self.height))
        effective_seed = (seed if seed is not None else self.seed) + 7777
        rng = np.random.default_rng(effective_seed)

        herb_spawns: list[tuple[int, int, int, HerbTemplate]] = []
        herb_tiles: set[tuple[int, int]] = set()

        target_total = int(rng.integers(10, 16))

        # Group placed trees by species
        trees_by_species: dict[str, list[PlacedTree]] = {
            TreeSpecies.WILLOW.value: [t for t in self.placed_trees if t.species == TreeSpecies.WILLOW.value],
            TreeSpecies.OAK.value: [t for t in self.placed_trees if t.species == TreeSpecies.OAK.value],
        }

        # Build candidate coordinates for each herb template according to its preferred environment
        candidates_by_herb: dict[str, list[tuple[int, int]]] = {}
        for herb in HERB_POOL:
            matching_trees = trees_by_species.get(herb.preferred_tree_species, [])
            cands: set[tuple[int, int]] = set()

            for tree in matching_trees:
                r = herb.max_tree_dist
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        hx, hy = tree.x + dx, tree.y + dy
                        if not (2 <= hx < self.width - 2 and 2 <= hy < self.height - 2):
                            continue
                        if (hx, hy) in self.water_tiles:
                            continue
                        if (hx, hy) in self.tree_tiles:
                            continue
                        if clear_starting_area and (90 <= hx <= 118 and 85 <= hy <= 118):
                            continue

                        # Check moisture / water distance preference
                        d = dist_map[hx, hy]
                        if herb.min_water_dist <= d <= herb.max_water_dist:
                            tile = game_map.get_tile(hx, hy, base_z)
                            if tile is not None and tile.walkable:
                                cands.add((hx, hy))

            candidates_by_herb[herb.name] = list(cands)

        # Distribute herbs across templates ensuring diverse preferred environment representation
        herb_order = list(HERB_POOL)
        rng.shuffle(herb_order)

        for herb in herb_order:
            cands = [c for c in candidates_by_herb.get(herb.name, []) if c not in herb_tiles]
            if not cands:
                continue

            # Pick 2-4 of this herb
            quota = min(len(cands), max(2, target_total // len(HERB_POOL)))
            chosen_indices = rng.choice(len(cands), size=quota, replace=False)
            for idx in chosen_indices:
                hx, hy = cands[idx]
                herb_spawns.append((hx, hy, base_z, herb))
                herb_tiles.add((hx, hy))
                if len(herb_spawns) >= target_total:
                    break

            if len(herb_spawns) >= target_total:
                break

        # Fill remaining slots up to target_total if needed
        attempts = 0
        while len(herb_spawns) < target_total and attempts < 50:
            attempts += 1
            herb = herb_order[attempts % len(herb_order)]
            cands = [c for c in candidates_by_herb.get(herb.name, []) if c not in herb_tiles]
            if cands:
                hx, hy = cands[int(rng.integers(0, len(cands)))]
                herb_spawns.append((hx, hy, base_z, herb))
                herb_tiles.add((hx, hy))

        self.herb_spawns = herb_spawns
        self.herb_tiles = herb_tiles
        return herb_spawns

    def spawn_herbs(self, esper_world=None) -> list[int]:
        """Spawn all scheduled herb entities into the ECS world with Item components."""
        spawned_entities: list[int] = []
        for hx, hy, hz, herb in self.herb_spawns:
            ent = esper.create_entity()
            esper.add_component(ent, Position(x=hx, y=hy, z=hz))
            esper.add_component(
                ent,
                Renderable(
                    char=herb.char,
                    color=herb.color,
                    layer=1,
                    render_order=RenderOrder.ITEM,
                ),
            )
            esper.add_component(
                ent,
                Item(
                    name=herb.name,
                    weight=herb.weight,
                    description=herb.description,
                ),
            )
            esper.add_component(ent, Name(herb.name))
            spawned_entities.append(ent)
        return spawned_entities

    def generate(
        self,
        game_map: GameMap | None = None,
        regional_tile: RegionalTile | None = None,
        z: int | None = None,
        seed: int | None = None,
        clear_starting_area: bool = True,
        spawn_herbs_in_ecs: bool = True,
    ) -> GameMap:
        """Generate the local map inheriting data from RegionalTile.

        Strict rules applied:
        1. Base layer filled with soil/grass matching biome.
        2. Continuous, unbroken brook carved edge-to-edge (2 to 3 tiles wide). Zero noise water.
        3. Moisture Bands & Vegetation:
           - Distance 1-3: Tall grass ('"') and Reeds ('|')
           - Distance 4-10: Thick grass (',')
           - Distance >= 11: Sparse grass ('.')
           - Distance > 30 dirt is completely removed.
        4. Strict ground tiles: NO random stone or rock tiles unless Biome is 'Mountains' or 'Badlands'.
        5. Tree Species: Willows grow near water, Oaks grow in sparse grass.
        6. Interactable herbs: 10 to 15 herbs placed strictly in their preferred environments.
        7. Tree Placement: NEVER spawns tree trunk inside brook or on top of an herb.
        """
        if regional_tile is not None:
            self.regional_tile = regional_tile
            self.base_z = int(regional_tile.base_elevation)
            if seed is None and getattr(regional_tile, "seed", None) is not None:
                seed = regional_tile.seed

        base_z = z if z is not None else self.base_z

        if game_map is None:
            game_map = GameMap(width=self.width, height=self.height)

        if seed is not None:
            effective_seed = seed
        elif getattr(self, "regional_tile", None) and getattr(self.regional_tile, "seed", None) is not None:
            effective_seed = self.regional_tile.seed
        else:
            effective_seed = self.seed
        rng = np.random.default_rng(effective_seed)

        # Clear previous generation state
        self.placed_trees.clear()
        self.tree_tiles.clear()
        self.herb_spawns.clear()
        self.herb_tiles.clear()

        # 1. Fill base Z-level grid
        game_map.generate_level(base_z)
        biome = self.regional_tile.biome
        biome_val = biome.value if hasattr(biome, "value") else str(biome)
        biome_lower = biome_val.lower()
        is_rocky_biome = "mountain" in biome_lower or "badland" in biome_lower
        is_desert = "desert" in biome_lower

        # Biome ground colors
        if is_desert:
            thick_grass_color = "yellow"
            sparse_grass_color = "yellow"
        elif "forest" in biome_lower:
            thick_grass_color = "green"
            sparse_grass_color = "green"
        else:
            thick_grass_color = "green"
            sparse_grass_color = "green"

        for x in range(self.width):
            for y in range(self.height):
                if x == 0 or x == self.width - 1 or y == 0 or y == self.height - 1:
                    game_map.set_tile(x, y, base_z, Tile.wall())
                else:
                    game_map.set_tile(x, y, base_z, Tile.sparse_grass(color=sparse_grass_color))

        # 2. Carve Continuous Brook FIRST (2 to 3 tiles wide, edge to edge, unbroken)
        water_tiles = self.carve_continuous_brook(
            game_map,
            z=base_z,
            rng=rng,
            clear_starting_area=clear_starting_area,
        )

        # 3. Compute Distance Map and derived Moisture Map
        self.compute_distance_map(water_tiles)
        dist_map = self.distance_map if self.distance_map is not None else np.zeros((self.width, self.height))
        self.generate_moisture_map(seed=effective_seed, water_tiles=water_tiles)
        elevation_map = self.generate_elevation_map(seed=effective_seed)

        # 4. Moisture Bands & Vegetation: flora strictly based on distance from brook
        # Distance > 30 dirt is REMOVED: distance >= 11 remains sparse grass ('.')
        for x in range(1, self.width - 1):
            for y in range(1, self.height - 1):
                if (x, y) in water_tiles:
                    continue
                if clear_starting_area and (98 <= x <= 110 and 97 <= y <= 103):
                    continue

                d = dist_map[x, y]
                elev = elevation_map[x, y]

                # Rocky terrain check: ONLY if strictly Mountains or Badlands
                if is_rocky_biome and d > 3 and elev >= self.elevation_threshold:
                    game_map.set_tile(x, y, base_z, Tile.rock())
                elif 1 <= d <= 3:
                    # High Moisture: Dense tall grass ('"') and Reeds ('|')
                    if rng.random() < 0.65:
                        game_map.set_tile(x, y, base_z, Tile.tall_grass(color="green"))
                    else:
                        game_map.set_tile(x, y, base_z, Tile.reeds(color="dark green"))
                elif 4 <= d <= 10:
                    # Medium Moisture: Thick grass (',')
                    game_map.set_tile(x, y, base_z, Tile.thick_grass(color=thick_grass_color))
                else:
                    # Low Moisture (distance >= 11): Sparse grass ('.') - dirt band removed
                    game_map.set_tile(x, y, base_z, Tile.sparse_grass(color=sparse_grass_color))

        # 5. Generate Multi-Z trees: Willows near water, Oaks in sparse grass
        self.generate_trees(
            game_map=game_map,
            base_z=base_z,
            rng=rng,
            clear_starting_area=clear_starting_area,
        )

        # 6. Scatter 10 to 15 interactable herbs matching their preferred environments
        self.generate_herb_spawns(
            game_map=game_map,
            base_z=base_z,
            seed=effective_seed,
            clear_starting_area=clear_starting_area,
        )
        if spawn_herbs_in_ecs:
            self.spawn_herbs()

        return game_map
