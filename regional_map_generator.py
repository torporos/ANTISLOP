"""Regional Map Generator module.

Generates 2D regional maps using approximate Voronoi cells via scipy.spatial.Voronoi.
Implements Lloyd's Relaxation to smooth out harsh geometric angles and assigns basic
biomes (Plains, Forest, Mountains) per cell.
"""

from dataclasses import dataclass
from enum import Enum
import numpy as np
from scipy.spatial import Voronoi, cKDTree


class BiomeType(Enum):
    """Basic regional biome types."""

    PLAINS = "Plains"
    FOREST = "Forest"
    MOUNTAINS = "Mountains"
    DESERT = "Desert"


@dataclass(frozen=True)
class BiomeData:
    """Visual attributes and metadata for a biome."""

    name: str
    char: str
    color: str


BIOME_REGISTRY: dict[BiomeType, BiomeData] = {
    BiomeType.PLAINS: BiomeData(name="Plains", char=".", color="green"),
    BiomeType.FOREST: BiomeData(name="Forest", char="T", color="dark green"),
    BiomeType.MOUNTAINS: BiomeData(name="Mountains", char="^", color="gray"),
    BiomeType.DESERT: BiomeData(name="Desert", char="~", color="yellow"),
}


@dataclass
class RegionalTile:
    """Regional tile data object inherited by local map generation."""

    biome: BiomeType | str = BiomeType.PLAINS
    base_elevation: int = 0
    base_moisture: float = 0.5
    seed: int | None = None

    @property
    def dominant_biome(self) -> BiomeType | str:
        """Dominant biome alias."""
        return self.biome


class RegionalMap:
    """Represents a generated regional map with Voronoi cells and assigned biomes."""

    def __init__(
        self,
        width: int,
        height: int,
        grid: np.ndarray,
        cell_biomes: dict[int, BiomeType],
        voronoi: Voronoi,
        seed_points: np.ndarray,
        seed: int | None = None,
    ) -> None:
        self.width = width
        self.height = height
        # grid array shaped (width, height) storing cell ID for each (x, y)
        self.grid = grid
        self.cell_biomes = cell_biomes
        self.voronoi = voronoi
        self.seed_points = seed_points
        self.seed = seed if seed is not None else 1337
        self.tile_seeds: dict[tuple[int, int], int] = {}

    def get_local_seed(self, x: int, y: int) -> int:
        """Return a persistent deterministic seed for the local map at (x, y)."""
        if (x, y) not in self.tile_seeds:
            h = (int(self.seed) * 73856093 ^ int(x) * 19349663 ^ int(y) * 83492791) & 0x7FFFFFFF
            if h == 0:
                h = 1337
            self.tile_seeds[(x, y)] = h
        return self.tile_seeds[(x, y)]

    def get_cell_id(self, x: int, y: int) -> int:
        """Return the Voronoi cell ID at coordinates (x, y)."""
        return int(self.grid[x, y])

    def get_biome(self, x: int, y: int) -> BiomeType:
        """Return the BiomeType at coordinates (x, y)."""
        cell_id = self.get_cell_id(x, y)
        return self.cell_biomes[cell_id]

    def get_biome_data(self, x: int, y: int) -> BiomeData:
        """Return the BiomeData (char, color, name) at coordinates (x, y)."""
        biome = self.get_biome(x, y)
        return BIOME_REGISTRY[biome]

    def get_regional_tile(self, x: int, y: int) -> RegionalTile:
        """Return a RegionalTile data object for coordinates (x, y) with persistent local seed."""
        biome = self.get_biome(x, y)
        if biome == BiomeType.MOUNTAINS:
            elev = 2
            moist = 0.3
        elif biome == BiomeType.FOREST:
            elev = 0
            moist = 0.7
        elif biome == BiomeType.DESERT:
            elev = 0
            moist = 0.15
        else:  # PLAINS
            elev = 0
            moist = 0.5
        local_seed = self.get_local_seed(x, y)
        return RegionalTile(
            biome=biome,
            base_elevation=elev,
            base_moisture=moist,
            seed=local_seed,
        )


class RegionalMapGenerator:
    """Generates 2D approximate Voronoi cell maps with Lloyd's Relaxation and biome assignments."""

    def __init__(
        self,
        width: int = 80,
        height: int = 50,
        num_cells: int = 35,
        relaxation_steps: int = 3,
        seed: int | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.num_cells = num_cells
        self.relaxation_steps = relaxation_steps
        self.seed = seed

    def lloyd_relaxation(
        self,
        points: np.ndarray,
        steps: int = 3,
    ) -> np.ndarray:
        """Apply Lloyd's Relaxation algorithm to smooth seed distribution.

        Iteratively averages the centroids of each Voronoi region on the grid,
        eliminating harsh, needle-like geometric angles.
        """
        xs, ys = np.meshgrid(np.arange(self.width), np.arange(self.height), indexing="ij")
        coords = np.column_stack((xs.ravel(), ys.ravel()))

        relaxed_points = np.copy(points)
        for _ in range(steps):
            tree = cKDTree(relaxed_points)
            _, cell_ids = tree.query(coords)
            grid = cell_ids.reshape((self.width, self.height))

            new_points = np.copy(relaxed_points)
            for cid in range(len(relaxed_points)):
                mask = (grid == cid)
                if np.any(mask):
                    new_points[cid] = [float(xs[mask].mean()), float(ys[mask].mean())]
            relaxed_points = new_points

        return relaxed_points

    def generate(
        self,
        seed: int | None = None,
        relaxation_steps: int | None = None,
    ) -> RegionalMap:
        """Generate a smoothed RegionalMap using Lloyd's Relaxation and assign biomes."""
        effective_seed = seed if seed is not None else self.seed
        steps = relaxation_steps if relaxation_steps is not None else self.relaxation_steps
        rng = np.random.default_rng(effective_seed)

        # 1. Generate initial random seed points
        raw_points = rng.uniform(
            low=[0.0, 0.0],
            high=[float(self.width), float(self.height)],
            size=(self.num_cells, 2),
        )

        # 2. Smooth seed points using Lloyd's Relaxation
        if steps > 0:
            smoothed_points = self.lloyd_relaxation(raw_points, steps=steps)
        else:
            smoothed_points = raw_points

        # 3. Build Voronoi diagram from the smoothed points
        vor = Voronoi(smoothed_points)

        # 4. Map each grid coordinate to the nearest Voronoi seed
        tree = cKDTree(vor.points)
        xs, ys = np.meshgrid(np.arange(self.width), np.arange(self.height), indexing="ij")
        coords = np.column_stack((xs.ravel(), ys.ravel()))
        _, cell_ids = tree.query(coords)
        grid = cell_ids.reshape((self.width, self.height))

        # 5. Assign one of the three basic biomes to each Voronoi cell
        available_biomes = [BiomeType.PLAINS, BiomeType.FOREST, BiomeType.MOUNTAINS]
        initial = list(available_biomes) + list(
            rng.choice(available_biomes, size=max(0, self.num_cells - len(available_biomes)))
        )
        rng.shuffle(initial)
        cell_biomes: dict[int, BiomeType] = {i: initial[i] for i in range(self.num_cells)}

        map_seed = effective_seed if effective_seed is not None else int(rng.integers(1, 1000000))
        return RegionalMap(
            width=self.width,
            height=self.height,
            grid=grid,
            cell_biomes=cell_biomes,
            voronoi=vor,
            seed_points=smoothed_points,
            seed=map_seed,
        )
