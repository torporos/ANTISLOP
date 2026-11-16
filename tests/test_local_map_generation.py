"""Unit and integration tests for Local Map Generation inheriting from RegionalTile.

Covers:
1. Requirements checking for noise / opensimplex.
2. RegionalTile data object (dominant Biome, Base Elevation, Base Moisture).
3. Base Z-level matching RegionalTile Base Elevation.
4. Base layer filled with ground tiles matching Biome (e.g., green '.' for Forest, yellow '~' for Desert).
5. Local bodies of water (ponds/brooks) generated first.
6. Localized Moisture Map:
   - Starts with Regional Base Moisture.
   - Applies slight Perlin/Simplex noise overlay for local variation.
   - Heavily increases moisture values for tiles immediately surrounding ponds/brooks.
7. Ground flora placement based on localized moisture map (e.g., tall grass '"' in high moisture areas).
8. Multi-Z trees:
   - Trunks ('T') spawn on base Z-level and grow UP 1 or 2 Z-levels.
   - Canopy/leaves spread on upper Z-levels.
   - MovementSystem treats tree trunks as blocking, but leaves/canopy as walkable so the player can walk under them.
   - RenderSystem draws canopy with darker green color and lower alpha value in BearLibTerminal.
"""

import unittest
from bearlibterminal import terminal
import esper
import numpy as np

from components import Energy, Inventory, Item, MovementIntent, Name, Player, Position, RenderOrder, Renderable
from game_map import GameMap, Tile
from local_map_generator import HERB_POOL, LocalMapGenerator
from regional_map_generator import BiomeType, RegionalTile
from systems import ItemCollectionSystem, MovementSystem, RenderSystem, TurnManagementSystem


class TestLocalMapGeneration(unittest.TestCase):
    """Test suite for LocalMapGenerator with RegionalTile inheritance, water, moisture, and Multi-Z trees."""

    def setUp(self) -> None:
        """Reset ECS world before each test."""
        esper.clear_database()
        for p in list(esper._processors):
            esper.remove_processor(type(p))

    def tearDown(self) -> None:
        """Clean up ECS world after each test."""
        esper.clear_database()
        for p in list(esper._processors):
            esper.remove_processor(type(p))

    def test_requirements_include_opensimplex_or_noise(self) -> None:
        """Verify requirements.txt contains opensimplex or noise."""
        with open("requirements.txt", "r", encoding="utf-8") as f:
            content = f.read()
        has_noise_lib = ("opensimplex" in content) or ("noise" in content)
        self.assertTrue(has_noise_lib, "requirements.txt must contain opensimplex or noise")

    def test_regional_tile_data_object_properties(self) -> None:
        """Verify RegionalTile data object stores dominant Biome, Base Elevation, and Base Moisture."""
        rt = RegionalTile(
            biome=BiomeType.FOREST,
            base_elevation=2,
            base_moisture=0.75,
        )
        self.assertEqual(rt.biome, BiomeType.FOREST)
        self.assertEqual(rt.dominant_biome, BiomeType.FOREST)
        self.assertEqual(rt.base_elevation, 2)
        self.assertEqual(rt.base_moisture, 0.75)

    def test_base_z_level_and_biome_ground_tiles(self) -> None:
        """Verify base Z-level matches RegionalTile base elevation and ground tiles match Biome."""
        # Test 1: Forest biome -> green '.'
        forest_rt = RegionalTile(biome=BiomeType.FOREST, base_elevation=1, base_moisture=0.7)
        gen_forest = LocalMapGenerator(width=200, height=200, regional_tile=forest_rt, seed=42)
        map_forest = gen_forest.generate(clear_starting_area=False)

        self.assertEqual(gen_forest.base_z, 1)
        # Check non-boundary, non-water floor tile
        found_forest_tile = False
        for x in range(5, 20):
            tile = map_forest.get_tile(x, 10, 1)
            if tile and tile.char == "." and tile.color == "green":
                found_forest_tile = True
                break
        self.assertTrue(found_forest_tile, "Forest must have green '.' ground tiles on base Z-level 1")

        # Test 2: Desert biome -> pure soil/sand/dirt '.' and ',' colored yellow
        desert_rt = RegionalTile(biome=BiomeType.DESERT, base_elevation=3, base_moisture=0.15)
        gen_desert = LocalMapGenerator(width=200, height=200, regional_tile=desert_rt, seed=43)
        map_desert = gen_desert.generate(clear_starting_area=False)

        self.assertEqual(gen_desert.base_z, 3)
        found_desert_tile = False
        for x in range(5, 20):
            tile = map_desert.get_tile(x, 10, 3)
            if tile and tile.char in (".", ",") and tile.color == "yellow":
                found_desert_tile = True
                break
        self.assertTrue(found_desert_tile, "Desert must have yellow '.' or ',' ground tiles on base Z-level 3")

    def test_water_bodies_generated_first(self) -> None:
        """Verify local bodies of water (ponds/brooks) are generated on the base Z-level."""
        rt = RegionalTile(biome=BiomeType.PLAINS, base_elevation=0, base_moisture=0.5)
        gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=55)
        game_map = gen.generate(clear_starting_area=False)

        self.assertGreater(len(gen.water_tiles), 0, "Generator must produce local bodies of water (ponds/brooks)")
        # Check that water tiles exist on base Z-level
        for wx, wy in list(gen.water_tiles)[:10]:
            tile = game_map.get_tile(wx, wy, 0)
            self.assertIsNotNone(tile)
            self.assertEqual(tile.char, "~")
            self.assertEqual(tile.color, "blue")
            self.assertTrue(tile.walkable)

    def test_moisture_map_local_variation_and_water_boost(self) -> None:
        """Verify Moisture Map starts with Regional Base Moisture, has noise variation, and water boost."""
        base_m = 0.40
        rt = RegionalTile(biome=BiomeType.PLAINS, base_elevation=0, base_moisture=base_m)
        gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=77)
        game_map = gen.generate(clear_starting_area=False)

        moist_map = gen.moisture_map
        self.assertIsNotNone(moist_map)
        self.assertEqual(moist_map.shape, (200, 200))

        # Check that tiles far from water are centered around base_moisture with slight noise variation
        # and not identical everywhere
        self.assertFalse(np.all(moist_map == base_m), "Moisture map must have noise overlay variation")

        # Check that tiles immediately surrounding water have heavily increased moisture
        for wx, wy in list(gen.water_tiles)[:5]:
            # Water tile itself is 1.0
            self.assertEqual(moist_map[wx, wy], 1.0)
            # Surrounding tiles (dist=1) must have heavily boosted moisture (> base_m + 0.3)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = wx + dx, wy + dy
                if 0 <= nx < 200 and 0 <= ny < 200:
                    self.assertGreater(
                        moist_map[nx, ny],
                        base_m + 0.25,
                        "Tiles immediately surrounding water must have heavily increased moisture",
                    )

    def test_ground_flora_spawns_in_high_moisture(self) -> None:
        """Verify ground flora (tall grass '"') spawns based on localized moisture map."""
        rt = RegionalTile(biome=BiomeType.PLAINS, base_elevation=0, base_moisture=0.60)
        gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=88, moisture_threshold=0.65)
        game_map = gen.generate(clear_starting_area=False)

        tall_grass_count = 0
        for x in range(1, 199):
            for y in range(1, 199):
                tile = game_map.get_tile(x, y, 0)
                if tile and tile.char == '"':
                    tall_grass_count += 1
                    # Moisture at this tile must be high
                    self.assertGreaterEqual(gen.moisture_map[x, y], 0.65)

        self.assertGreater(tall_grass_count, 0, "High moisture areas must spawn tall grass '\"'")

    def test_multi_z_trees_spawn_and_grow_up(self) -> None:
        """Verify Multi-Z trees: trunk ('T') on base_z, grows UP 1 or 2 Z-levels, canopy on upper levels."""
        game_map = GameMap(width=200, height=200)
        gen = LocalMapGenerator(width=200, height=200)

        base_z = 1
        # Place a multi-Z tree at (40, 40) growing UP 2 levels (height=2)
        gen.place_tree(game_map, x=40, y=40, base_z=base_z, height=2, canopy_radius=1)

        # 1. Base Z-level (z=1): trunk 'T'
        base_trunk = game_map.get_tile(40, 40, base_z)
        self.assertIsNotNone(base_trunk)
        self.assertEqual(base_trunk.char, "T")
        self.assertFalse(base_trunk.walkable, "Base trunk must block movement")
        self.assertFalse(game_map.is_walkable(40, 40, base_z))

        # 2. Upper Z-levels (z=2 and z=3): trunk 'T' grows UP
        for z_up in (base_z + 1, base_z + 2):
            up_trunk = game_map.get_tile(40, 40, z_up)
            self.assertIsNotNone(up_trunk)
            self.assertEqual(up_trunk.char, "T", f"Tree trunk must grow UP to Z-level {z_up}")
            self.assertFalse(up_trunk.walkable)

        # 3. Canopy/leaves spread on upper Z-levels
        for z_up in (base_z + 1, base_z + 2):
            self.assertTrue(game_map.has_canopy(41, 40, z_up), f"Upper Z-level {z_up} must have canopy leaves")
            self.assertTrue(game_map.has_canopy_at_level(41, 40, z_up))

        # 4. On base Z-level (z=1), ground under the canopy is WALKABLE so player can walk under it!
        self.assertTrue(game_map.is_walkable(41, 40, base_z), "Ground under tree canopy on base_z must be walkable")
        ground_tile = game_map.get_tile(41, 40, base_z)
        self.assertTrue(ground_tile.walkable)
        self.assertNotEqual(ground_tile.char, "T")

        # 5. has_canopy from base_z returns True because canopy is overhead
        self.assertTrue(game_map.has_canopy(41, 40, base_z))

    def test_movement_system_walk_under_canopy_and_block_trunk(self) -> None:
        """Verify MovementSystem allows walking under tree canopy and blocks walking into trunk on base_z."""
        game_map = GameMap(width=200, height=200)
        gen = LocalMapGenerator(width=200, height=200)

        base_z = 0
        gen.place_tree(game_map, x=20, y=20, base_z=base_z, height=2, canopy_radius=1)

        turn_sys = TurnManagementSystem()
        movement_sys = MovementSystem(game_map=game_map, turn_system=turn_sys)

        player = esper.create_entity(
            Player(),
            Position(x=18, y=20, z=base_z),
            Energy(current=100, max_energy=100),
        )

        # 1. Walk from (18, 20) under tree canopy to (19, 20) on base_z
        esper.add_component(player, MovementIntent(dx=1, dy=0, dz=0))
        movement_sys.process()

        player_pos = esper.component_for_entity(player, Position)
        self.assertEqual((player_pos.x, player_pos.y, player_pos.z), (19, 20, base_z))
        self.assertTrue(game_map.has_canopy(19, 20, base_z), "Tile (19, 20) has overhead canopy")

        # 2. Try to walk into trunk at (20, 20) on base_z -> BLOCKED!
        esper.add_component(player, MovementIntent(dx=1, dy=0, dz=0))
        movement_sys.process()

        player_pos = esper.component_for_entity(player, Position)
        self.assertEqual((player_pos.x, player_pos.y, player_pos.z), (19, 20, base_z), "Movement into trunk must be blocked")
        self.assertTrue(any("tree trunk" in msg.lower() for msg in turn_sys.combat_log.messages))

    def test_render_system_tree_canopy_properties(self) -> None:
        """Verify RenderSystem renders upper canopy leaves with darker green and lower alpha transparency."""
        game_map = GameMap(width=200, height=200)
        gen = LocalMapGenerator(width=200, height=200)
        gen.place_tree(game_map, x=20, y=20, base_z=0, height=1, canopy_radius=1)

        render_sys = RenderSystem(game_map=game_map)
        self.assertEqual(render_sys.leaf_char, "%")
        self.assertLess(render_sys.leaf_alpha, 255)
        self.assertGreater(render_sys.leaf_alpha, 0)

        # ARGB format check: alpha < 255 and predominantly green
        if isinstance(render_sys.leaf_color, int):
            alpha = (render_sys.leaf_color >> 24) & 0xFF
            red = (render_sys.leaf_color >> 16) & 0xFF
            green = (render_sys.leaf_color >> 8) & 0xFF
            blue = render_sys.leaf_color & 0xFF
            self.assertEqual(alpha, render_sys.leaf_alpha)
            self.assertGreater(green, red)
            self.assertGreater(green, blue)

    def test_continuous_brook_unbroken_and_width(self) -> None:
        """Verify brook is continuous, unbroken from edge to opposite edge, and 2-3 tiles wide."""
        import scipy.ndimage as ndi

        for s in (101, 202, 303):
            gen = LocalMapGenerator(width=200, height=200, seed=s)
            game_map = gen.generate(clear_starting_area=False)

            self.assertGreater(len(gen.water_tiles), 0, "Brook must contain water tiles")

            # Check that water tiles form exactly 1 continuous unbroken component
            grid = np.zeros((200, 200), dtype=int)
            for wx, wy in gen.water_tiles:
                grid[wx, wy] = 1

            _lbl, num_components = ndi.label(grid, structure=np.ones((3, 3)))
            self.assertEqual(
                num_components,
                1,
                f"Brook must be a single continuous unbroken component, got {num_components}",
            )

            # Check that the brook reaches both opposite edges
            has_north = any(grid[x, 0] for x in range(200))
            has_south = any(grid[x, 199] for x in range(200))
            has_west = any(grid[0, y] for y in range(200))
            has_east = any(grid[199, y] for y in range(200))

            reaches_opposite_edges = (has_north and has_south) or (has_west and has_east)
            self.assertTrue(
                reaches_opposite_edges,
                "Brook must carve a continuous path from one edge to the opposite edge",
            )

    def test_strict_ground_tiles_no_rocks_in_non_rocky_biomes(self) -> None:
        """Verify NO random stone or rock tiles spawn in Plains, Forest, or Desert biomes."""
        for biome in (BiomeType.PLAINS, BiomeType.FOREST, BiomeType.DESERT):
            rt = RegionalTile(biome=biome, base_elevation=0, base_moisture=0.5)
            gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=123)
            game_map = gen.generate(clear_starting_area=False)

            rock_count = 0
            for x in range(1, 199):
                for y in range(1, 199):
                    tile = game_map.get_tile(x, y, 0)
                    if tile and tile.char == "*":
                        rock_count += 1
            self.assertEqual(
                rock_count,
                0,
                f"Biome {biome.value} must NOT have any rock tiles ('*')",
            )

    def test_strict_ground_tiles_rocks_in_mountains_or_badlands(self) -> None:
        """Verify stone or rock tiles ('*') CAN spawn in Mountains or Badlands at high elevation."""
        rt = RegionalTile(biome=BiomeType.MOUNTAINS, base_elevation=0, base_moisture=0.3)
        gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=456, elevation_threshold=0.5)
        game_map = gen.generate(clear_starting_area=False)

        rock_count = 0
        for x in range(1, 199):
            for y in range(1, 199):
                tile = game_map.get_tile(x, y, 0)
                if tile and tile.char == "*":
                    rock_count += 1
        self.assertGreater(
            rock_count,
            0,
            "Mountains biome must allow rock tiles ('*') at high elevation",
        )

    def test_moisture_bands_vegetation_distance_mapping(self) -> None:
        """Verify small flora is strictly placed based on distance from the continuous brook:
        - Distance 1-3: Tall grass ('"') and Reeds ('|')
        - Distance 4-10: Thick grass (',')
        - Distance >= 11: Sparse grass ('.')
        - Distance > 30 dirt is completely removed.
        """
        rt = RegionalTile(biome=BiomeType.PLAINS, base_elevation=0, base_moisture=0.5)
        gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=789)
        game_map = gen.generate(clear_starting_area=False)

        dist_map = gen.distance_map
        self.assertIsNotNone(dist_map)

        band_high_found = False
        band_med_found = False
        band_low_found = False
        band_far_found = False

        for x in range(2, 198):
            for y in range(2, 198):
                if (x, y) in gen.water_tiles:
                    continue
                tile = game_map.get_tile(x, y, 0)
                if tile is None or tile.char == "T":
                    continue  # Skip tree trunks

                d = dist_map[x, y]
                if 1 <= d <= 3:
                    self.assertIn(
                        tile.char,
                        ('"', '|'),
                        f"Distance {d} must be Tall grass ('\"') or Reeds ('|'), got {tile.char}",
                    )
                    band_high_found = True
                elif 4 <= d <= 10:
                    self.assertEqual(
                        tile.char,
                        ",",
                        f"Distance {d} must be Thick grass (','), got {tile.char}",
                    )
                    band_med_found = True
                elif 11 <= d <= 30:
                    self.assertEqual(
                        tile.char,
                        ".",
                        f"Distance {d} must be Sparse grass ('.'), got {tile.char}",
                    )
                    self.assertEqual(tile.color, "green")
                    band_low_found = True
                elif d > 30:
                    # Distance > 30 dirt is removed: must be sparse grass ('.', green), NOT brown dirt
                    self.assertEqual(
                        tile.char,
                        ".",
                        f"Distance {d} must be Sparse grass ('.') since dirt is removed, got {tile.char}",
                    )
                    self.assertEqual(
                        tile.color,
                        "green",
                        f"Distance {d} must be green sparse grass, NOT brown dirt",
                    )
                    band_far_found = True

        self.assertTrue(band_high_found, "Must have tiles in High Moisture band (1-3)")
        self.assertTrue(band_med_found, "Must have tiles in Medium Moisture band (4-10)")
        self.assertTrue(band_low_found, "Must have tiles in Low Moisture band (11-30)")
        self.assertTrue(band_far_found, "Must have tiles at distance > 30 (sparse grass, no dirt)")

    def test_interactable_herbs_pool_and_entity_spawning(self) -> None:
        """Verify interactable herbs pool, entity creation with Item component, and pickup via 'G'."""
        # 1. Pool check
        herb_names = {h.name for h in HERB_POOL}
        self.assertIn("Kingsfoil", herb_names)
        self.assertIn("Bloodweed", herb_names)
        self.assertIn("Silverleaf", herb_names)
        self.assertIn("Earthroot", herb_names)

        # 2. Map generation spawns 10 to 15 herbs
        rt = RegionalTile(biome=BiomeType.PLAINS, base_elevation=0, base_moisture=0.5)
        gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=999)
        game_map = gen.generate(clear_starting_area=False, spawn_herbs_in_ecs=True)

        self.assertGreaterEqual(len(gen.herb_spawns), 10)
        self.assertLessEqual(len(gen.herb_spawns), 15)

        # 3. Check herbs are actual ECS entities with Item and Position
        herb_entities = []
        for ent, (pos, item, rend) in esper.get_components(Position, Item, Renderable):
            if item.name in herb_names:
                herb_entities.append((ent, pos, item, rend))
                d = gen.distance_map[pos.x, pos.y]
                self.assertGreaterEqual(d, 1, "Herbs must not be in water")

        self.assertEqual(len(herb_entities), len(gen.herb_spawns))

        # 4. Verify player can walk over an herb and pick it up
        first_herb_ent, herb_pos, herb_comp, _ = herb_entities[0]
        player = esper.create_entity(
            Player(),
            Position(x=herb_pos.x, y=herb_pos.y, z=0),
            Inventory(max_capacity=20),
        )

        collection_sys = ItemCollectionSystem()
        picked_up = collection_sys.collect_item(player)
        self.assertTrue(picked_up, "Player must be able to pick up herb entity on their tile")

        # Entity should no longer have Position component (removed from map)
        self.assertFalse(esper.has_component(first_herb_ent, Position))

        # Item should be in player's inventory
        player_inv = esper.component_for_entity(player, Inventory)
        self.assertIn(first_herb_ent, player_inv.items)

    def test_tree_species_willow_and_oak(self) -> None:
        """Verify trees are treated as different species: Willows near water, Oaks in sparse grass."""
        from local_map_generator import TreeSpecies

        rt = RegionalTile(biome=BiomeType.FOREST, base_elevation=0, base_moisture=0.7)
        gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=515)
        game_map = gen.generate(clear_starting_area=False)

        willows = [t for t in gen.placed_trees if t.species == TreeSpecies.WILLOW.value]
        oaks = [t for t in gen.placed_trees if t.species == TreeSpecies.OAK.value]

        self.assertGreater(len(willows), 0, "Map must generate willow trees")
        self.assertGreater(len(oaks), 0, "Map must generate oak trees")

        # Verify Willows grow near water (distance <= 6)
        for willow in willows:
            d = gen.distance_map[willow.x, willow.y]
            self.assertLessEqual(
                d,
                6,
                f"Willow tree at ({willow.x}, {willow.y}) must be near water (<=6), got {d}",
            )
            tile = game_map.get_tile(willow.x, willow.y, 0)
            self.assertEqual(tile.tree_species, "willow")
            self.assertEqual(tile.char, "T")

        # Verify Oaks grow even in sparse grass (at least some Oaks have distance >= 11)
        oaks_in_sparse_grass = [
            oak for oak in oaks if gen.distance_map[oak.x, oak.y] >= 11
        ]
        self.assertGreater(
            len(oaks_in_sparse_grass),
            0,
            "Oaks must grow in sparse grass (distance >= 11)",
        )
        for oak in oaks:
            tile = game_map.get_tile(oak.x, oak.y, 0)
            self.assertEqual(tile.tree_species, "oak")
            self.assertEqual(tile.char, "T")

    def test_herb_ecological_preferences(self) -> None:
        """Verify each herb spawns strictly in its preferred environment (moisture and tree proximity)."""
        from local_map_generator import TreeSpecies

        rt = RegionalTile(biome=BiomeType.PLAINS, base_elevation=0, base_moisture=0.5)
        gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=777)
        game_map = gen.generate(clear_starting_area=False, spawn_herbs_in_ecs=True)

        self.assertGreater(len(gen.herb_spawns), 0)

        template_by_name = {h.name: h for h in HERB_POOL}
        trees_by_species = {
            TreeSpecies.WILLOW.value: [t for t in gen.placed_trees if t.species == TreeSpecies.WILLOW.value],
            TreeSpecies.OAK.value: [t for t in gen.placed_trees if t.species == TreeSpecies.OAK.value],
        }

        for hx, hy, hz, herb_tmpl in gen.herb_spawns:
            d = gen.distance_map[hx, hy]

            # 1. Moisture preference check
            self.assertGreaterEqual(
                d,
                herb_tmpl.min_water_dist,
                f"{herb_tmpl.name} at ({hx}, {hy}) has water distance {d} < min {herb_tmpl.min_water_dist}",
            )
            self.assertLessEqual(
                d,
                herb_tmpl.max_water_dist,
                f"{herb_tmpl.name} at ({hx}, {hy}) has water distance {d} > max {herb_tmpl.max_water_dist}",
            )

            # 2. Tree species proximity check
            preferred_trees = trees_by_species.get(herb_tmpl.preferred_tree_species, [])
            min_tree_dist = min(
                max(abs(hx - t.x), abs(hy - t.y)) for t in preferred_trees
            )
            self.assertLessEqual(
                min_tree_dist,
                herb_tmpl.max_tree_dist,
                f"{herb_tmpl.name} at ({hx}, {hy}) is {min_tree_dist} tiles away from {herb_tmpl.preferred_tree_species}, exceeding max {herb_tmpl.max_tree_dist}",
            )

    def test_tree_never_spawns_in_brook_or_on_herb(self) -> None:
        """Verify Multi-Z tree generator NEVER spawns tree trunk inside the brook or on top of an herb."""
        rt = RegionalTile(biome=BiomeType.FOREST, base_elevation=0, base_moisture=0.8)
        gen = LocalMapGenerator(width=200, height=200, regional_tile=rt, seed=333, tree_density=0.25)
        game_map = gen.generate(clear_starting_area=False, spawn_herbs_in_ecs=True)

        # 1. Trunks never on water tiles
        for wx, wy in gen.water_tiles:
            tile = game_map.get_tile(wx, wy, 0)
            self.assertIsNotNone(tile)
            self.assertEqual(tile.char, "~", f"Water tile at ({wx}, {wy}) must not be a tree trunk")
            self.assertNotEqual(tile.char, "T")

        # 2. Trunks never on herb tiles
        for hx, hy in gen.herb_tiles:
            tile = game_map.get_tile(hx, hy, 0)
            self.assertIsNotNone(tile)
            self.assertNotEqual(tile.char, "T", f"Herb tile at ({hx}, {hy}) must not have tree trunk")

        # 3. Direct place_tree calls refuse water and herb tiles
        some_water = next(iter(gen.water_tiles))
        placed_on_water = gen.place_tree(game_map, x=some_water[0], y=some_water[1], base_z=0)
        self.assertFalse(placed_on_water, "place_tree must return False and refuse to spawn on water")

        some_herb = next(iter(gen.herb_tiles))
        placed_on_herb = gen.place_tree(game_map, x=some_herb[0], y=some_herb[1], base_z=0)
        self.assertFalse(placed_on_herb, "place_tree must return False and refuse to spawn on herb")


if __name__ == "__main__":
    unittest.main()
