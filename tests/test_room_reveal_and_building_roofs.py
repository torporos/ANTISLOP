"""Unit and integration tests for:
1. Seeing into a room reveals the entire room in FOV.
2. Inside a building, never rendering the roof of that building's other rooms.
3. Separate buildings outside continue to render roofs when viewed from inside or outside.
"""

import unittest
from bearlibterminal import terminal
import esper

from building_generator import create_tavern_graph, stamp_building_graph
from components import Door, Position, Renderable, StructureFootprint, Viewshed
from game_map import GameMap, Tile
from systems import DoorSystem, InputSystem, MovementSystem, RenderSystem, VisibilitySystem
import main


class TestRoomRevealMechanic(unittest.TestCase):
    """Test suite for 'if you can see into a room, you see the entire room'."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        self.door_system = main.current_door_system
        esper.process()

    def test_closed_door_does_not_reveal_room(self) -> None:
        """When door is closed, line of sight cannot enter, so room interior is not revealed."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Stand outside south of Tavern door at (101, 104)
        pos.x = 101
        pos.y = 104
        esper.process()

        # Closed door at (101, 103) is visible
        self.assertTrue(viewshed.is_visible(101, 103))

        # Interior floor tiles of Tavern (100, 100) must NOT be visible
        self.assertFalse(viewshed.is_visible(100, 100))
        self.assertFalse(viewshed.is_visible(99, 100))

    def test_open_door_reveals_entire_room(self) -> None:
        """Opening the door allows line of sight into the room, revealing the ENTIRE room."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Stand outside south of Tavern door at (101, 104)
        pos.x = 101
        pos.y = 104
        esper.process()

        # Open door at (101, 103)
        door_ent = self.door_system.get_door_at(101, 103, 0)
        self.assertIsNotNone(door_ent)
        self.door_system.open_door(door_ent)
        esper.process()

        # Now FOV reaches into the room -> ENTIRE Tavern Main Room is revealed!
        for rx in range(98, 105):
            for ry in range(97, 104):
                self.assertTrue(
                    viewshed.is_visible(rx, ry),
                    f"Tile at ({rx}, {ry}) in Tavern Main Room should be visible once room is seen into",
                )
                self.assertTrue(
                    self.game_map.is_explored(rx, ry, 0),
                    f"Tile at ({rx}, {ry}) should be explored once revealed",
                )

    def test_see_into_tavern_kitchen_reveals_entire_kitchen(self) -> None:
        """From Tavern Main Room, opening door to Kitchen reveals the entire Kitchen."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)

        # Player is inside Main Room at (104, 100, 0), right next to Kitchen door at (105, 100, 0)
        pos.x = 104
        pos.y = 100
        esper.process()

        # Kitchen is (105..110, 97..102)
        # While door is closed, Kitchen interior is not visible
        self.assertFalse(viewshed.is_visible(107, 100))
        self.assertFalse(viewshed.is_visible(109, 98))

        # Spawn a goblin chef NPC in the far corner of Kitchen at (109, 98)
        goblin = esper.create_entity()
        esper.add_component(goblin, Position(x=109, y=98, z=0))
        esper.add_component(goblin, Renderable(char="g", color="green", layer=1))

        # Goblin is initially hidden in fog of war
        render_system = esper.get_processor(RenderSystem)
        self.assertFalse(
            render_system.is_entity_rendered(Position(109, 98, 0), active_viewshed=viewshed)
        )

        # Open door at (105, 100, 0)
        door_ent = self.door_system.get_door_at(105, 100, 0)
        self.assertIsNotNone(door_ent)
        self.door_system.open_door(door_ent)
        esper.process()

        # Entire Kitchen is now in FOV!
        for kx in range(105, 111):
            for ky in range(97, 103):
                self.assertTrue(
                    viewshed.is_visible(kx, ky),
                    f"Kitchen tile at ({kx}, {ky}) should be visible once door is open",
                )

        # The goblin chef in the far corner is now rendered!
        self.assertTrue(
            render_system.is_entity_rendered(Position(109, 98, 0), active_viewshed=viewshed)
        )


class TestBuildingRoofsInsideAndOutside(unittest.TestCase):
    """Test suite for 'if you are inside a building, never render roof of that buildings other rooms'."""

    def setUp(self) -> None:
        self.game_map = GameMap(width=200, height=200)
        self.player = main.init_ecs(game_map=self.game_map)
        self.door_system = main.current_door_system
        esper.process()

    def test_inside_building_never_renders_roof_of_other_rooms_of_same_building(self) -> None:
        """When player is in Main Room, Kitchen must NOT render as roof even if outside FOV."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)
        render_system = esper.get_processor(RenderSystem)

        # Mark Kitchen tiles as explored
        for kx in range(105, 111):
            for ky in range(97, 103):
                self.game_map.set_explored(kx, ky, 0, True)

        # Player is inside Tavern Main Room at (100, 100, 0)
        pos.x = 100
        pos.y = 100
        esper.process()

        self.assertEqual(viewshed.current_room_id, 1)
        self.assertEqual(viewshed.active_building_id, "Tavern")

        # Door to Kitchen at (105, 100, 0) is closed, so Kitchen is NOT in active FOV
        self.assertFalse(viewshed.is_visible(107, 100))

        # Check tile rendering for Kitchen floor at (107, 100, 0)
        # Because player is inside Tavern, Kitchen must NEVER render as roof ('^', 'brown')!
        info = render_system.get_tile_render_info(107, 100, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info)
        char, color = info
        self.assertNotEqual(
            char, "^", "Should NOT render Roof '^' over Kitchen when player is inside the same building"
        )
        self.assertEqual(char, ".", "Should render normal floor '.' instead of roof")
        self.assertEqual(color, "dark gray", "Should render with dark/muted color")

    def test_inside_building_renders_roof_for_different_building_outside(self) -> None:
        """When player is in Tavern, another building outside DOES render with roof."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)
        render_system = esper.get_processor(RenderSystem)

        # Create a separate Storehouse building at (50, 50)
        self.game_map.create_structure(
            x=50,
            y=50,
            width=5,
            height=5,
            name="Storehouse",
            building_id="Storehouse",
            room_id=10,
        )

        # Mark Storehouse tiles (50..54, 50..54) as explored
        for bx in range(50, 55):
            for by in range(50, 55):
                self.game_map.set_explored(bx, by, 0, True)

        # Player is inside Tavern Main Room at (100, 100, 0)
        pos.x = 100
        pos.y = 100
        esper.process()

        # Storehouse at (52, 52) is outside FOV and belongs to a different building ("Storehouse")
        self.assertFalse(viewshed.is_visible(52, 52))
        info = render_system.get_tile_render_info(52, 52, 0, active_viewshed=viewshed)
        self.assertIsNotNone(info)
        char, color = info
        self.assertEqual(
            char, "^", "Different building outside should render roof '^' even when player is in Tavern"
        )
        self.assertEqual(color, "brown")

    def test_outside_building_renders_roof_for_all_buildings(self) -> None:
        """When player steps outside into the wilderness, both Tavern and Storehouse render roofs."""
        pos = esper.component_for_entity(self.player, Position)
        viewshed = esper.component_for_entity(self.player, Viewshed)
        render_system = esper.get_processor(RenderSystem)

        # Create Storehouse building at (50, 50)
        self.game_map.create_structure(
            x=50,
            y=50,
            width=5,
            height=5,
            name="Storehouse",
            building_id="Storehouse",
            room_id=10,
        )

        # Mark both Tavern and Storehouse as explored
        for tx in range(98, 111):
            for ty in range(97, 104):
                self.game_map.set_explored(tx, ty, 0, True)
        for bx in range(50, 55):
            for by in range(50, 55):
                self.game_map.set_explored(bx, by, 0, True)

        # Step outside to wilderness at (100, 120, 0) - far from both buildings
        pos.x = 100
        pos.y = 120
        esper.process()

        self.assertIsNone(viewshed.current_room_id)
        self.assertFalse(viewshed.inside_structure)
        self.assertIsNone(viewshed.active_building_id)

        # Both Tavern and Storehouse must render roofs
        tavern_info = render_system.get_tile_render_info(100, 100, 0, active_viewshed=viewshed)
        self.assertIsNotNone(tavern_info)
        self.assertEqual(tavern_info[0], "^")
        self.assertEqual(tavern_info[1], "brown")

        storehouse_info = render_system.get_tile_render_info(52, 52, 0, active_viewshed=viewshed)
        self.assertIsNotNone(storehouse_info)
        self.assertEqual(storehouse_info[0], "^")
        self.assertEqual(storehouse_info[1], "brown")


if __name__ == "__main__":
    unittest.main()
