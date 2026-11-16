"""Unit and integration tests for BuildingGraph, Prefabs, and Stamping."""

import unittest
from bearlibterminal import terminal
import esper
import networkx as nx

from building_generator import (
    BEDROOMS_PREFAB,
    KITCHEN_PREFAB,
    MAIN_ROOM_PREFAB,
    BuildingGraph,
    create_tavern_graph,
    stamp_building_graph,
)
from components import Door, Position, Viewshed
from game_map import GameMap, Tile
import main


class TestBuildingGraph(unittest.TestCase):
    """Test suite for BuildingGraph topology and Tavern creation."""

    def test_tavern_graph_structure(self) -> None:
        """Verify the 3-node Tavern graph has expected nodes and edges."""
        bg = create_tavern_graph()
        self.assertIsInstance(bg.graph, nx.Graph)

        # 3 Nodes: A (Main Room), B (Kitchen), C (Bedrooms)
        self.assertEqual(len(bg.graph.nodes), 3)
        self.assertIn("A", bg.graph.nodes)
        self.assertIn("B", bg.graph.nodes)
        self.assertIn("C", bg.graph.nodes)

        node_a = bg.get_room("A")
        self.assertEqual(node_a["name"], "Main Room")
        self.assertEqual(node_a["z"], 0)
        self.assertEqual(node_a["room_id"], 1)

        node_b = bg.get_room("B")
        self.assertEqual(node_b["name"], "Kitchen")
        self.assertEqual(node_b["z"], 0)
        self.assertEqual(node_b["room_id"], 2)

        node_c = bg.get_room("C")
        self.assertEqual(node_c["name"], "Bedrooms")
        self.assertEqual(node_c["z"], 1)
        self.assertEqual(node_c["room_id"], 3)

        # 2 Edges: A->B (door), A->C (staircase)
        self.assertEqual(len(bg.graph.edges), 2)
        self.assertTrue(bg.graph.has_edge("A", "B"))
        self.assertEqual(bg.graph.edges["A", "B"]["connection_type"], "door")

        self.assertTrue(bg.graph.has_edge("A", "C"))
        self.assertEqual(bg.graph.edges["A", "C"]["connection_type"], "staircase")

    def test_prefabs_dimensions_and_connectors(self) -> None:
        """Verify dimensions and connector alignments of the 3 room prefabs."""
        # Main Room: 8 wide x 7 high
        self.assertEqual(MAIN_ROOM_PREFAB.width, 8)
        self.assertEqual(MAIN_ROOM_PREFAB.height, 7)
        self.assertIn("kitchen_door", MAIN_ROOM_PREFAB.connectors)
        self.assertIn("stairs_up", MAIN_ROOM_PREFAB.connectors)
        self.assertIn("exterior_door", MAIN_ROOM_PREFAB.connectors)

        # Kitchen: 6 wide x 6 high
        self.assertEqual(KITCHEN_PREFAB.width, 6)
        self.assertEqual(KITCHEN_PREFAB.height, 6)
        self.assertIn("main_room_door", KITCHEN_PREFAB.connectors)

        # Bedrooms: 8 wide x 7 high
        self.assertEqual(BEDROOMS_PREFAB.width, 8)
        self.assertEqual(BEDROOMS_PREFAB.height, 7)
        self.assertIn("stairs_down", BEDROOMS_PREFAB.connectors)

        # Stair alignment: stairs_up in Main Room aligns with stairs_down in Bedrooms
        self.assertEqual(
            MAIN_ROOM_PREFAB.connectors["stairs_up"],
            BEDROOMS_PREFAB.connectors["stairs_down"],
        )


class TestStampingAndNavigation(unittest.TestCase):
    """Test suite for stamping prefabs, room_id inheritance, and multi-level traversal."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        esper.process()

    def test_spawn_inside_main_room(self) -> None:
        """Verify player spawns inside the Main Room at (100, 100, 0) with room_id=1."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        self.assertEqual((pos.x, pos.y, pos.z), (100, 100, 0))
        self.assertEqual(viewshed.current_room_id, 1)
        self.assertTrue(viewshed.inside_structure)

        # Spawn tile has room_id=1
        spawn_tile = self.game_map.get_tile(100, 100, 0)
        self.assertEqual(spawn_tile.room_id, 1)
        self.assertEqual(spawn_tile.char, ".")

    def test_room_id_stamped_properly(self) -> None:
        """Verify stamped tiles inherit appropriate room_ids."""
        # Main Room (room_id=1)
        tile_main = self.game_map.get_tile(99, 98, 0)
        self.assertEqual(tile_main.room_id, 1)

        # Kitchen (room_id=2)
        tile_kitchen = self.game_map.get_tile(107, 98, 0)
        self.assertEqual(tile_kitchen.room_id, 2)

        # Bedrooms (room_id=3, Z=1)
        tile_bed = self.game_map.get_tile(99, 98, 1)
        self.assertEqual(tile_bed.room_id, 3)

    def test_staircase_vertical_alignment(self) -> None:
        """Verify stairs_up ('<') at Z=0 aligns with stairs_down ('>') at Z=1."""
        stairs_up_tile = self.game_map.get_tile(103, 99, 0)
        self.assertEqual(stairs_up_tile.char, "<")
        self.assertEqual(stairs_up_tile.room_id, 1)
        self.assertTrue(stairs_up_tile.walkable)

        stairs_down_tile = self.game_map.get_tile(103, 99, 1)
        self.assertEqual(stairs_down_tile.char, ">")
        self.assertEqual(stairs_down_tile.room_id, 3)
        self.assertTrue(stairs_down_tile.walkable)

    def test_walk_up_and_down_stairs(self) -> None:
        """Verify moving onto stairs and pressing '<' / '>' climbs between floors."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # 1. Walk onto stairs up at (103, 99, 0)
        pos.x = 103
        pos.y = 99
        pos.z = 0
        esper.process()
        self.assertEqual(viewshed.current_room_id, 1)

        # 2. Ascend to Z=1 via '<' key
        esper.process(key=ord("<"))
        self.assertEqual(pos.z, 1)
        self.assertEqual((pos.x, pos.y), (103, 99))
        self.assertEqual(viewshed.current_room_id, 3)

        # 3. Descend to Z=0 via '>' key
        esper.process(key=ord(">"))
        self.assertEqual(pos.z, 0)
        self.assertEqual((pos.x, pos.y), (103, 99))
        self.assertEqual(viewshed.current_room_id, 1)

    def test_move_between_main_room_and_kitchen(self) -> None:
        """Verify moving through the doorway transitions room_id between 1 and 2."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Open kitchen door at (105, 100, 0)
        door_ent = main.current_door_system.get_door_at(105, 100, 0)
        self.assertIsNotNone(door_ent)
        main.current_door_system.open_door(door_ent)

        # Step into Kitchen at (106, 100, 0)
        pos.x = 106
        pos.y = 100
        pos.z = 0
        esper.process()

        # Player is now in Kitchen (room_id=2)
        self.assertEqual(viewshed.current_room_id, 2)
        self.assertTrue(viewshed.inside_structure)

        # Step back into Main Room at (104, 100, 0)
        pos.x = 104
        pos.y = 100
        esper.process()

        # Player is back in Main Room (room_id=1)
        self.assertEqual(viewshed.current_room_id, 1)


if __name__ == "__main__":
    unittest.main()
