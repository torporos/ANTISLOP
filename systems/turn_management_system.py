"""Turn Management and Combat System for turn ticks, energy pools, and skills.

Implements the WoW/Rogue hybrid combat mechanics:
- Energy-based action economy (entities gain Energy each tick, actions consume Energy).
- SkillBar execution (e.g. Cleave targeting adjacent tiles).
- CombatLog for recording combat events and printing to terminal.
"""

import esper

from components import Energy, Fighter, Name, Player, Position, Skill, SkillBar
from message_log import MessageLog, global_message_log


class CombatLog(MessageLog):
    """Manages combat and system messages displayed in the UI and printed to terminal."""

    def __init__(self, max_messages: int = 100) -> None:
        super().__init__(max_messages=max_messages)

    def add(self, message: str) -> None:
        """Add a combat message to the log and print it to the terminal."""
        self.messages.append(message)
        if len(self.messages) > self.max_messages:
            self.messages.pop(0)
        print(f"[Combat] {message}")


class TurnManagementSystem(esper.Processor):
    """Gives entities Energy each tick and resolves turn-based actions and skills."""

    def __init__(self, combat_log: CombatLog | None = None) -> None:
        super().__init__()
        self.combat_log = combat_log if combat_log is not None else CombatLog()
        self.turn_count: int = 0

    def process(self, *args, **kwargs) -> None:
        """Process turn updates or scheduled ticks if requested, and clean up defeated enemies."""
        if kwargs.get("tick", False):
            self.tick()
        self.cleanup_defeated_entities()

    def tick(self, skip_regen_entities: set[int] | None = None) -> None:
        """Advance the world by one tick, replenishing Energy for entities that didn't consume energy."""
        self.turn_count += 1
        skip_set = skip_regen_entities or set()

        for ent, energy in esper.get_component(Energy):
            if ent in skip_set:
                energy.consumed_this_tick = False
                continue
            energy.regenerate()

        # Decrement cooldowns on SkillBars
        for _ent, sbar in esper.get_component(SkillBar):
            for skill in sbar.skills:
                if skill.current_cooldown > 0:
                    skill.current_cooldown -= 1

    def delete_defeated_entity(self, ent: int) -> bool:
        """Delete a defeated entity from the world (never delete Player)."""
        if esper.has_component(ent, Player):
            return False
        if esper.entity_exists(ent):
            esper.delete_entity(ent, immediate=True)
            return True
        return False

    def cleanup_defeated_entities(self) -> list[int]:
        """Sweep and delete any non-player entities whose Fighter component has hp <= 0 / is not alive."""
        defeated: list[int] = []
        for ent, fighter in list(esper.get_component(Fighter)):
            if not esper.has_component(ent, Player) and not fighter.is_alive:
                defeated.append(ent)
        for ent in defeated:
            self.delete_defeated_entity(ent)
        return defeated

    def pass_turn(self, user_ent: int) -> None:
        """Pass a turn for an entity, regenerating energy and advancing the world."""
        user_name = "Player" if esper.has_component(user_ent, Player) else f"Entity {user_ent}"
        if esper.has_component(user_ent, Name):
            user_name = esper.component_for_entity(user_ent, Name).name

        self.combat_log.add(f"{user_name} waits a turn.")
        self.tick()

    def can_entity_act(self, ent: int, cost: int | None = None) -> bool:
        """Check whether an entity has enough Energy to perform an action."""
        if not esper.has_component(ent, Energy):
            return True
        energy = esper.component_for_entity(ent, Energy)
        return energy.can_act(cost)

    def consume_action(self, ent: int, cost: int | None = None) -> bool:
        """Consume Energy for an action and advance the turn tick if successful."""
        if not esper.has_component(ent, Energy):
            self.tick()
            return True
        energy = esper.component_for_entity(ent, Energy)
        if energy.consume(cost):
            self.tick()
            return True
        return False

    def execute_cleave(self, user_ent: int, skill: Skill | None = None) -> bool:
        """Execute the Cleave skill targeting all 8 adjacent tiles on the active Z-level."""
        # 1. Resolve Skill object from SkillBar or fallback
        if skill is None:
            if esper.has_component(user_ent, SkillBar):
                sbar = esper.component_for_entity(user_ent, SkillBar)
                for s in sbar.skills:
                    if s.name.lower() == "cleave":
                        skill = s
                        break
                if skill is None:
                    skill = sbar.get_skill(0)
            if skill is None:
                skill = Skill(name="Cleave", energy_cost=20, damage=15, description="Strikes all adjacent enemies")

        # 2. Check if user has enough Energy
        if esper.has_component(user_ent, Energy):
            energy = esper.component_for_entity(user_ent, Energy)
            if not energy.can_act(skill.energy_cost):
                msg = f"Not enough Energy to use {skill.name}! (Need {skill.energy_cost}, have {energy.current})"
                self.combat_log.add(msg)
                return False

        # 3. Determine user identity and position
        user_name = "Player" if esper.has_component(user_ent, Player) else f"Entity {user_ent}"
        if esper.has_component(user_ent, Name):
            user_name = esper.component_for_entity(user_ent, Name).name

        user_pos = esper.component_for_entity(user_ent, Position)

        # 4. Consume Energy
        if esper.has_component(user_ent, Energy):
            energy = esper.component_for_entity(user_ent, Energy)
            energy.consume(skill.energy_cost)

        # 5. Target all adjacent tiles (Chebyshev distance == 1 on same Z-level)
        hits: list[tuple[int, str, int, int, int]] = []
        defeated_entities: list[int] = []
        for target_ent, (t_pos, t_fighter) in list(esper.get_components(Position, Fighter)):
            if target_ent == user_ent:
                continue
            if t_pos.z == user_pos.z:
                dx = abs(t_pos.x - user_pos.x)
                dy = abs(t_pos.y - user_pos.y)
                if max(dx, dy) == 1 and t_fighter.is_alive:
                    actual_dmg = t_fighter.take_damage(skill.damage)
                    t_name = f"Target {target_ent}"
                    if esper.has_component(target_ent, Name):
                        t_name = esper.component_for_entity(target_ent, Name).name
                    hits.append((target_ent, t_name, actual_dmg, t_fighter.hp, t_fighter.max_hp))
                    if not t_fighter.is_alive:
                        defeated_entities.append(target_ent)

        # 6. Log results
        if hits:
            for _t_ent, t_name, dmg, rem_hp, max_hp in hits:
                status = f"({rem_hp}/{max_hp} HP)" if rem_hp > 0 else "(Defeated!)"
                self.combat_log.add(
                    f"{user_name} used {skill.name}! Hit {t_name} for {dmg} damage! {status}"
                )
        else:
            self.combat_log.add(f"{user_name} used {skill.name}, but hit nothing.")

        # 7. Delete defeated enemies from the world
        for d_ent in defeated_entities:
            self.delete_defeated_entity(d_ent)

        # 8. Advance turn tick
        self.tick()
        return True

    def execute_fireball(
        self,
        user_ent: int,
        target_x: int,
        target_y: int,
        target_z: int | None = None,
        skill: Skill | None = None,
    ) -> bool:
        """Execute the Fireball skill at target (x, y, z) location."""
        # 1. Resolve Skill object from SkillBar or fallback
        if skill is None:
            if esper.has_component(user_ent, SkillBar):
                sbar = esper.component_for_entity(user_ent, SkillBar)
                for s in sbar.skills:
                    if s.name.lower() == "fireball":
                        skill = s
                        break
                if skill is None and len(sbar.skills) > 1:
                    skill = sbar.skills[1]
            if skill is None:
                skill = Skill(
                    name="Fireball",
                    energy_cost=20,
                    damage=25,
                    range=5,
                    description="Ranged fire projectile (Range: 5)",
                )

        # 2. Check if user has enough Energy
        if esper.has_component(user_ent, Energy):
            energy = esper.component_for_entity(user_ent, Energy)
            if not energy.can_act(skill.energy_cost):
                msg = f"Not enough Energy to use {skill.name}! (Need {skill.energy_cost}, have {energy.current})"
                self.combat_log.add(msg)
                return False

        # 3. Determine user identity and position
        user_name = "Player" if esper.has_component(user_ent, Player) else f"Entity {user_ent}"
        if esper.has_component(user_ent, Name):
            user_name = esper.component_for_entity(user_ent, Name).name

        user_pos = esper.component_for_entity(user_ent, Position) if esper.has_component(user_ent, Position) else None
        if target_z is None:
            target_z = user_pos.z if user_pos else 0

        # 4. Consume Energy
        if esper.has_component(user_ent, Energy):
            energy = esper.component_for_entity(user_ent, Energy)
            energy.consume(skill.energy_cost)

        # 5. Deal damage to any entity with a Fighter component on that tile
        hits: list[tuple[int, str, int, int, int]] = []
        defeated_entities: list[int] = []
        for target_ent, (t_pos, t_fighter) in list(esper.get_components(Position, Fighter)):
            if target_ent == user_ent:
                continue
            if t_pos.z == target_z and t_pos.x == target_x and t_pos.y == target_y and t_fighter.is_alive:
                actual_dmg = t_fighter.take_damage(skill.damage)
                t_name = f"Target {target_ent}"
                if esper.has_component(target_ent, Name):
                    t_name = esper.component_for_entity(target_ent, Name).name
                hits.append((target_ent, t_name, actual_dmg, t_fighter.hp, t_fighter.max_hp))
                if not t_fighter.is_alive:
                    defeated_entities.append(target_ent)

        # 6. Log results
        if hits:
            for _t_ent, t_name, dmg, rem_hp, max_hp in hits:
                status = f"({rem_hp}/{max_hp} HP)" if rem_hp > 0 else "(Defeated!)"
                self.combat_log.add(
                    f"{user_name} used {skill.name}! Hit {t_name} for {dmg} damage! {status}"
                )
        else:
            self.combat_log.add(f"{user_name} used {skill.name}, but hit nothing.")

        # 7. Delete defeated enemies from the world
        for d_ent in defeated_entities:
            self.delete_defeated_entity(d_ent)

        # 8. Advance turn tick
        self.tick()
        return True
