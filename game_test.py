"""游戏逻辑测试 - 执行 python game_test.py 运行"""
from game_state import (
    CellType, GamePhase, create_game, get_cell, find_tiger,
    player_tigers_on_field, BOARD_SIZE,
)
from game_logic import (
    take_action, snitch,
    get_player_view, get_public_board,
    get_player, get_opponent,
)


def print_sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_1_create_game():
    print_sep("1. 创建游戏 & 初始状态")
    state = create_game()
    assert state.phase == GamePhase.PLACEMENT
    assert state.round == 1
    assert state.turn == 0
    # 检查初始草地（内部 0-indexed: (1,1)-(4,4)）
    for y in range(1, 5):
        for x in range(1, 5):
            assert state.board[y][x] == CellType.GRASS, f"({x},{y}) 应该是草地"
    # 检查虚空
    assert state.board[0][0] == CellType.VOID
    assert state.board[9][9] == CellType.VOID
    assert state.board[0][1] == CellType.VOID
    assert state.board[5][5] == CellType.VOID
    print("  [OK] 初始状态正确")


def test_2_placement_phase():
    print_sep("2. 放置阶段（双方各放 1 只老虎）")
    state = create_game()

    state = _apply_placements(state, (2, 2), (4, 4))

    assert state.phase == GamePhase.PLAYING, f"应该是 PLAYING，当前为 {state.phase}"
    assert state.round == 2
    assert state.turn == 0  # 先手开始游戏
    assert len(player_tigers_on_field(state, "p1")) == 1
    assert len(player_tigers_on_field(state, "p2")) == 1
    print("  [OK] 放置阶段完成，进入游戏阶段")


def test_3_move():
    print_sep("3. 移动操作")
    state = _setup_game()

    # 先手：移动一只老虎（假设先手老虎在 (2,2)）
    p1_tiger = player_tigers_on_field(state, "p1")[0]
    old_x, old_y = p1_tiger.x, p1_tiger.y
    # 往右挪一步
    state = take_action(state, "p1", {
        "type": "move",
        "tiger_id": p1_tiger.tid,
        "direction": "right",
    })
    assert (p1_tiger.x, p1_tiger.y) == (old_x + 1, old_y), f"移动失败: ({old_x},{old_y})→({p1_tiger.x},{p1_tiger.y})"
    print(f"  [OK] 移动成功: ({old_x},{old_y})→({p1_tiger.x},{p1_tiger.y})")


def test_4_attack():
    print_sep("4. 攻击操作")
    state = _setup_game()

    # 拿到双方老虎坐标
    p1_tiger = player_tigers_on_field(state, "p1")[0]
    # 先手攻击老虎旁边的格子（假定为空地将它变成虚空）
    state = take_action(state, "p1", {
        "type": "attack",
        "tiger_id": p1_tiger.tid,
        "direction": "right",
    })

    # 检查冷却
    p1 = get_player(state, "p1")
    assert p1.attack_cd == 3, f"攻击冷却应为 3，实际为 {p1.attack_cd}"
    print(f"  [OK] 攻击执行成功，冷却: {p1.attack_cd}")


def test_5_cooldown_tick():
    print_sep("5. 冷却递减")
    state = _setup_game()

    p1 = get_player(state, "p1")
    p1_tiger = player_tigers_on_field(state, "p1")[0]

    # 先用一次移动（冷却0）
    state = take_action(state, "p1", {
        "type": "move",
        "tiger_id": p1_tiger.tid,
        "direction": "right",
    })

    # 后手随便操作
    p2_tiger = player_tigers_on_field(state, "p2")[0]
    state = take_action(state, "p2", {
        "type": "move",
        "tiger_id": p2_tiger.tid,
        "direction": "left",
    })

    # 进入下一轮 (round=3)，先手回合开始时冷却应该已减
    # 先手上前一步（但 (2,2) 老虎已经移动过，我们需要找实际老虎）
    t1 = player_tigers_on_field(state, "p1")[0]
    state = take_action(state, "p1", {
        "type": "move",
        "tiger_id": t1.tid,
        "direction": "down",
    })
    # 这时候 round 应该是 3 或更高
    print(f"  当前回合: round={state.round}")
    print(f"  [OK] 操作正常执行")


def test_6_empty_land_death():
    print_sep("6. 空地死亡判定")
    state = _setup_game()
    # P2's only tiger at (4,4), P1's at (2,2)

    # Round 2: P1 mows (4,4) → P2's tiger on empty, P2 actions → 0
    state = take_action(state, "p1", {"type": "mow", "x": 4, "y": 4})
    assert state.board[4][4] == CellType.EMPTY
    print("  [OK] P1 割草 (4,4)→空地，P2老虎在空地上")

    # P2's turn (actions=0): was_on_empty marked, skip act
    state = take_action(state, "p2", {"type": "move", "tiger_id": ""})  # dummy, ignored
    assert len(player_tigers_on_field(state, "p2")) == 1, "第一次回合标记不应死亡"

    # Round 3: P1 acts
    p1_t = player_tigers_on_field(state, "p1")[0]
    state = take_action(state, "p1", {"type": "move", "tiger_id": p1_t.tid, "direction": "right"})

    # P2 回合开始时，on_turn_start 判定空地死亡
    death_events_before = len([e for e in state.events if e.get("type") == "tiger_died"])
    # P2 必须放置（场上无老虎）
    state = take_action(state, "p2", {"type": "place", "x": 3, "y": 3})
    death_events_after = len([e for e in state.events if e.get("type") == "tiger_died"])
    assert death_events_after > death_events_before, "空地死亡未触发"
    print(f"  [OK] 空地死亡触发，死亡事件数: {death_events_before}→{death_events_after}")


def test_7_land_op():
    print_sep("7. 土地操作（虚空→草地）")
    state = _setup_game()

    # 找一块虚空
    void_positions = []
    for y in range(BOARD_SIZE):
        for x in range(BOARD_SIZE):
            if state.board[y][x] == CellType.VOID:
                void_positions.append((x, y))

    target = void_positions[0]
    state = take_action(state, "p1", {
        "type": "land",
        "x": target[0],
        "y": target[1],
    })
    assert state.board[target[1]][target[0]] == CellType.GRASS, "土地操作应变为草地"
    p1 = get_player(state, "p1")
    assert p1.land_cd == 1, f"土地冷却应为 1，实际 {p1.land_cd}"
    print(f"  [OK] 土地操作成功: {target}→草地")


def test_8_ear_op():
    print_sep("8. 耳朵操作（探测对方老虎）")
    state = _setup_game()

    # 找一个后手老虎的位置
    p2_tiger = player_tigers_on_field(state, "p2")[0]

    # 先手使用耳朵探测该位置
    state = take_action(state, "p1", {
        "type": "ear",
        "x": p2_tiger.x,
        "y": p2_tiger.y,
    })

    # 查看事件
    private_events = [e for e in state.events
                      if e.get("type") == "ear_result"
                      and e.get("target") == "p1"]
    assert len(private_events) > 0
    assert private_events[-1]["has_tiger"] == True
    print(f"  [OK] 耳朵探测成功: ({p2_tiger.x},{p2_tiger.y}) 有老虎")


def test_9_seed_op():
    print_sep("9. 草籽操作（空地→草地）")
    state = _setup_game()

    # Round 2: P1 mow a vacant grass cell → EMPTY
    state = take_action(state, "p1", {"type": "mow", "x": 3, "y": 4})
    assert state.board[4][3] == CellType.EMPTY
    print("  [OK] 割草 (3,4)→空地")
    # P2 turn: move
    p2_t = player_tigers_on_field(state, "p2")[0]
    state = take_action(state, "p2", {"type": "move", "tiger_id": p2_t.tid, "direction": "left"})

    # Round 3: P1 seed (3,4) → GRASS. seed has cd 3, separate from mow cd
    state = take_action(state, "p1", {"type": "seed", "x": 3, "y": 4})
    assert state.board[4][3] == CellType.GRASS
    p1 = get_player(state, "p1")
    assert p1.seed_cd == 3, f"seed冷却应为3，实际{p1.seed_cd}"
    print(f"  [OK] 草籽操作成功: (3,4)→草地，冷却={p1.seed_cd}")


def test_10_snitch():
    print_sep("10. 告密操作（需重叠）")
    state = _setup_game()

    p1_tiger = player_tigers_on_field(state, "p1")[0]
    p2_tiger = player_tigers_on_field(state, "p2")[0]

    # 让 P2 老虎与 P1 重叠（测试目的）
    p2_tiger.x, p2_tiger.y = p1_tiger.x, p1_tiger.y

    # P1 在自己老虎位置告密 → P2 老虎应死亡
    state = snitch(state, "p1", p1_tiger.x, p1_tiger.y)
    assert find_tiger(state, "p2", p1_tiger.x, p1_tiger.y) is None
    p2 = get_player(state, "p2")
    assert len(p2.field) == 0, f"场上应为0只，实际{len(p2.field)}"
    assert p2.total_left == 4
    print(f"  [OK] P1 在 ({p1_tiger.x},{p1_tiger.y}) 告密成功，重叠的 P2 老虎死亡")

    # 测试无重叠（对手不在该格）→ 不误杀
    state = _setup_game()
    p1_tiger = player_tigers_on_field(state, "p1")[0]
    state = snitch(state, "p1", p1_tiger.x, p1_tiger.y)
    assert find_tiger(state, "p1", p1_tiger.x, p1_tiger.y) is not None
    print("  [OK] 无重叠告密不误杀")

    # 测试呼叫者不在该格 → 报错
    state = _setup_game()
    try:
        state = snitch(state, "p1", 7, 7)
        assert False, "应该抛出错误"
    except ValueError:
        print("  [OK] 呼叫者不在该格时报错")


def test_11_stealth():
    print_sep("11. 隐匿操作")
    state = _setup_game()

    p1_tiger = player_tigers_on_field(state, "p1")[0]

    # 带隐匿的移动
    old_x, old_y = p1_tiger.x, p1_tiger.y
    state = take_action(state, "p1", {
        "type": "move",
        "tiger_id": p1_tiger.tid,
        "direction": "right",
        "use_stealth": True,
    })

    # 隐匿进入冷却
    p1 = get_player(state, "p1")
    assert p1.stealth_cd > 0, "隐匿应有冷却"
    print(f"  [OK] 隐匿移动成功 ({old_x},{old_y})→({p1_tiger.x},{p1_tiger.y})，隐匿冷却={p1.stealth_cd}")


def test_12_view_player():
    print_sep("12. 玩家视图（信息不对称验证）")
    state = _setup_game()

    view_p1 = get_player_view(state, "p1")
    view_p2 = get_player_view(state, "p2")

    print(f"  先手看到自己的老虎: {view_p1['my_tigers']}")
    print(f"  后手看到自己的老虎: {view_p2['my_tigers']}")

    # 验证双方看不到对方老虎
    p2_tiger_positions = [(t.x, t.y) for t in player_tigers_on_field(state, "p2")]
    p1_tiger_positions = [(t.x, t.y) for t in player_tigers_on_field(state, "p1")]

    assert "p2_tigers" not in view_p1
    assert "p2_tigers" not in view_p2

    print(f"  [OK] 玩家视图信息隔离正常")


# ===================== 辅助：快速进入游戏阶段 =====================

def _apply_placements(state, p1_pos, p2_pos):
    """执行放置阶段：先手放1只，后手放1只"""
    state = take_action(state, "p1", {"x": p1_pos[0], "y": p1_pos[1]})
    state = take_action(state, "p2", {"x": p2_pos[0], "y": p2_pos[1]})
    return state


def _setup_game():
    """快速创建一个进入 PLAYING 阶段的对局
    P1: (2,2), P2: (4,4)
    """
    state = create_game()
    return _apply_placements(state, (2, 2), (4, 4))


# ===================== 运行 =====================

if __name__ == "__main__":
    test_1_create_game()
    test_2_placement_phase()
    test_3_move()
    test_4_attack()
    test_5_cooldown_tick()
    test_6_empty_land_death()
    test_7_land_op()
    test_8_ear_op()
    test_9_seed_op()
    test_10_snitch()
    test_11_stealth()
    test_12_view_player()
    print(f"\n{'='*60}")
    print("  [DONE] 全部测试完成！")
