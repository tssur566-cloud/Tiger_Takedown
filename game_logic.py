"""游戏规则引擎 - 纯函数，不含网络层"""
from __future__ import annotations

from game_state import (
    CellType, GamePhase, GameState, Tiger,
    PlayerState,
    BOARD_SIZE, MAX_TIGERS_ON_FIELD, DIRECTIONS,
    in_bounds, is_initial_area, get_cell,
    player_tigers_on_field, find_tiger,
    get_player, get_opponent, opponent_id,
)

# ===================== 冷却定义 =====================
OP_COOLDOWNS = {
    "move": 0,
    "place": 3,
    "land": 1,
    "attack": 3,
    "mow": 2,
    "ear": 3,
    "seed": 3,
}
STEALTH_COOLDOWN = 3


# ===================== 主入口 =====================

def take_action(state: GameState, pid: str, action: dict) -> GameState:
    """玩家执行操作的主入口"""
    assert state.players[state.turn].pid == pid, f"不是 {pid} 的回合"

    if state.phase == GamePhase.PLACEMENT:
        return _handle_placement(state, pid, action)
    if state.phase == GamePhase.ENDED:
        return state

    # ── 回合开始处理 ──
    state = _on_turn_start(state, pid)
    if state.phase == GamePhase.ENDED:
        return state

    player = get_player(state, pid)

    # ── 执行操作 ──
    if player.actions > 0:
        state = _execute_op(state, pid, action)
        player.actions -= 1
    # else: 割草导致 actions=0，跳过操作

    # ── 回合结束：根据 turn 索引决定切换 / 进下一轮 ──
    # 先手( turn=0 )结束后 → 切换到后手
    # 后手( turn=1 )结束后 → 进下一轮，由先手开始
    if state.turn == 1:
        state = _start_new_round(state)
    else:
        state.turn = 1

    return state


def snitch(state: GameState, caller_id: str, x: int, y: int) -> GameState:
    """告密：暴露自己一只老虎的坐标，若该格有对方老虎则击杀"""
    # 呼叫者必须在该格有老虎
    if not find_tiger(state, caller_id, x, y):
        raise ValueError(f"你在 ({x},{y}) 没有老虎，告密需暴露自己的老虎")

    target_pid = opponent_id(caller_id)
    tiger = find_tiger(state, target_pid, x, y)
    if tiger:
        get_player(state, target_pid).field.remove(tiger)
        get_player(state, target_pid).total_left -= 1
        state.events.append({
            "type": "snitch_result",
            "visibility": "public",
            "x": x, "y": y,
            "success": True,
            "caller": caller_id,
        })
        _check_win(state)
    else:
        state.events.append({
            "type": "snitch_result",
            "visibility": "public",
            "x": x, "y": y,
            "success": False,
            "caller": caller_id,
        })
    return state


# ===================== 回合开始 =====================

def _on_turn_start(state: GameState, pid: str) -> GameState:
    """处理回合开始：冷却-1，空地死亡判定"""
    player = get_player(state, pid)
    player.tick_cds()

    # 空地死亡判定
    tigers_to_die = []
    for tiger in player.field:
        cell = state.board[tiger.y][tiger.x]
        if cell == CellType.EMPTY:
            if tiger.was_on_empty:
                tigers_to_die.append(tiger)
            else:
                tiger.was_on_empty = True
        else:
            tiger.was_on_empty = False

    for t in tigers_to_die:
        player.field.remove(t)
        player.total_left -= 1
        state.events.append({
            "type": "tiger_died",
            "visibility": "public",
            "reason": "空地暴露过久",
            "x": t.x, "y": t.y,
        })

    _check_win(state)
    return state


# ===================== 操作执行分发 =====================

def _execute_op(state: GameState, pid: str, action: dict) -> GameState:
    op = action["type"]
    player = get_player(state, pid)

    # 冷却检查
    cd = OP_COOLDOWNS.get(op, 0)
    if cd > 0 and not player.can_use(op):
        raise ValueError(f"操作 [{op}] 仍在冷却中 ({player.get_cd(op)} 回合)")

    # 隐匿检查
    use_stealth = action.get("use_stealth", False)
    if use_stealth and not player.can_use("stealth"):
        raise ValueError("隐匿仍在冷却中")

    # 如果场上无老虎且仍有老虎存活，强制放置
    if op != "place" and len(player.field) == 0 and player.total_left > 0:
        raise ValueError("场上无老虎，必须先使用放置操作")

    # 分发
    if op == "move":
        state = _op_move(state, pid, action, use_stealth)
    elif op == "place":
        state = _op_place(state, pid, action, use_stealth)
    elif op == "land":
        state = _op_land(state, pid, action)
    elif op == "attack":
        state = _op_attack(state, pid, action, use_stealth)
    elif op == "mow":
        state = _op_mow(state, pid, action)
    elif op == "ear":
        state = _op_ear(state, pid, action)
    elif op == "seed":
        state = _op_seed(state, pid, action)
    else:
        raise ValueError(f"未知操作: {op}")

    # 设置冷却
    if cd > 0:
        player.set_cd(op, cd)
    if use_stealth:
        player.set_cd("stealth", STEALTH_COOLDOWN)

    return state


# ===================== 各操作实现 =====================

def _op_move(state: GameState, pid: str, action: dict, stealth: bool) -> GameState:
    tid = action["tiger_id"]
    direction = action["direction"]
    dx, dy = DIRECTIONS[direction]

    tiger = _find_own_tiger(state, pid, tid)
    nx, ny = tiger.x + dx, tiger.y + dy

    # 验证目标格
    cell = get_cell(state.board, nx, ny)
    if cell not in (CellType.GRASS, CellType.EMPTY):
        raise ValueError(f"目标 ({nx},{ny}) 不可通行")
    if _own_tiger_at(state, pid, nx, ny):
        raise ValueError(f"目标 ({nx},{ny}) 已有自己的老虎")

    # 执行移动
    state.events.append({
        "type": "move",
        "visibility": "public",
        "stealthed": stealth,
        "from_x": tiger.x if not stealth else None,
        "from_y": tiger.y if not stealth else None,
        "to_x": nx, "to_y": ny,
    })
    tiger.x, tiger.y = nx, ny
    return state


def _op_place(state: GameState, pid: str, action: dict, stealth: bool) -> GameState:
    x, y = action["x"], action["y"]
    player = get_player(state, pid)

    if len(player.field) >= MAX_TIGERS_ON_FIELD:
        raise ValueError("场上老虎已达上限 (3只)")
    if player.total_left <= len(player.field):
        raise ValueError("没有剩余老虎可放置")

    cell = get_cell(state.board, x, y)
    if cell not in (CellType.GRASS, CellType.EMPTY):
        raise ValueError(f"无法在 ({x},{y}) 放置老虎：区域不可用")
    if _own_tiger_at(state, pid, x, y):
        raise ValueError(f"({x},{y}) 已有自己的老虎")

    tid = state._next_tiger_id()
    tiger = Tiger(tid=tid, pid=pid, x=x, y=y)
    player.field.append(tiger)
    state.events.append({
        "type": "place",
        "visibility": "public",
        "stealthed": stealth,
        "x": x if not stealth else None,
        "y": y if not stealth else None,
    })
    return state


def _op_land(state: GameState, pid: str, action: dict) -> GameState:
    x, y = action["x"], action["y"]
    if state.board[y][x] != CellType.VOID:
        raise ValueError(f"({x},{y}) 不是虚空")
    state.board[y][x] = CellType.GRASS
    state.events.append({
        "type": "land",
        "visibility": "public",
        "x": x, "y": y,
    })
    return state


def _op_attack(state: GameState, pid: str, action: dict, stealth: bool) -> GameState:
    tid = action["tiger_id"]
    direction = action["direction"]
    dx, dy = DIRECTIONS[direction]

    tiger = _find_own_tiger(state, pid, tid)
    tx, ty = tiger.x + dx, tiger.y + dy

    if not in_bounds(tx, ty):
        raise ValueError(f"攻击目标 ({tx},{ty}) 超出边界")

    # 记录事件（攻击来源位置）
    attacker_info = {"x": tiger.x, "y": tiger.y}
    state.events.append({
        "type": "attack",
        "visibility": "public",
        "stealthed": stealth,
        "from": None if stealth else attacker_info,
        "target_x": tx, "target_y": ty,
    })

    # 目标变为虚空
    state.board[ty][tx] = CellType.VOID

    # 检查是否有老虎在目标格
    for p in state.players:
        tiger_hit = find_tiger(state, p.pid, tx, ty)
        if tiger_hit:
            p.field.remove(tiger_hit)
            p.total_left -= 1
            state.events.append({
                "type": "tiger_died",
                "visibility": "public",
                "reason": "被攻击",
                "x": tx, "y": ty,
            })
            _check_win(state)
            break

    return state


def _op_mow(state: GameState, pid: str, action: dict) -> GameState:
    x, y = action["x"], action["y"]
    if state.board[y][x] != CellType.GRASS:
        raise ValueError(f"({x},{y}) 不是草地")
    state.board[y][x] = CellType.EMPTY

    # 检查该格是否有敌方老虎
    opp = get_opponent(state, pid)
    tiger_hit = find_tiger(state, opp.pid, x, y)
    if tiger_hit:
        _reduce_action_next_turn(state, opp.pid)

    state.events.append({
        "type": "mow",
        "visibility": "public",
        "x": x, "y": y,
    })
    return state


def _op_ear(state: GameState, pid: str, action: dict) -> GameState:
    x, y = action["x"], action["y"]
    opp = get_opponent(state, pid)
    has_tiger = find_tiger(state, opp.pid, x, y) is not None
    state.events.append({
        "type": "ear_result",
        "visibility": "private",
        "target": pid,
        "x": x, "y": y,
        "has_tiger": has_tiger,
    })
    return state


def _op_seed(state: GameState, pid: str, action: dict) -> GameState:
    x, y = action["x"], action["y"]
    if state.board[y][x] != CellType.EMPTY:
        raise ValueError(f"({x},{y}) 不是空地")
    state.board[y][x] = CellType.GRASS
    state.events.append({
        "type": "seed",
        "visibility": "public",
        "x": x, "y": y,
    })
    return state


# ===================== 辅助函数 =====================

def _find_own_tiger(state: GameState, pid: str, tid: str) -> Tiger:
    for t in player_tigers_on_field(state, pid):
        if t.tid == tid:
            return t
    raise ValueError(f"未找到老虎 {tid}")


def _any_tiger_at(state: GameState, x: int, y: int) -> bool:
    for p in state.players:
        if find_tiger(state, p.pid, x, y):
            return True
    return False


def _own_tiger_at(state: GameState, pid: str, x: int, y: int) -> bool:
    return find_tiger(state, pid, x, y) is not None


def _reduce_action_next_turn(state: GameState, pid: str):
    """对方下回合可操作次数减 1（割草效果）"""
    player = get_player(state, pid)
    player.actions = max(0, player.actions - 1)


def _check_win(state: GameState):
    for p in state.players:
        if p.total_left <= 0:
            state.phase = GamePhase.ENDED
            state.winner = opponent_id(p.pid)
            state.events.append({
                "type": "game_over",
                "visibility": "public",
                "winner": state.winner,
            })
            return


def _start_new_round(state: GameState) -> GameState:
    state.round += 1
    for p in state.players:
        p.actions = 1
    state.turn = 0
    # 先手的回合开始处理在下一次 take_action 时进行
    return state


# ===================== 放置阶段 =====================

def _handle_placement(state: GameState, pid: str, action: dict) -> GameState:
    x, y = action["x"], action["y"]

    if not is_initial_area(x, y):
        raise ValueError(f"({x},{y}) 不在初始放置区域 (2,2)-(5,5) 内")
    if state.board[y][x] != CellType.GRASS:
        raise ValueError("必须在草地上放置")

    # 检查是否有自己的老虎
    if _own_tiger_at(state, pid, x, y):
        raise ValueError(f"({x},{y}) 已有自己的老虎")

    player = get_player(state, pid)
    if len(player.field) >= MAX_TIGERS_ON_FIELD:
        raise ValueError("场上已有 3 只老虎")

    # 放置
    tid = state._next_tiger_id()
    tiger = Tiger(tid=tid, pid=pid, x=x, y=y)
    player.field.append(tiger)

    state.events.append({
        "type": "placement",
        "visibility": "private",
        "target": pid,
        "x": x, "y": y,
        "tiger_id": tid,
    })

    state.placement_step += 1
    if state.placement_step >= 2:
        # 放置阶段结束 → 进入游戏阶段
        state.phase = GamePhase.PLAYING
        state.round = 2
        state.turn = 0
        for p in state.players:
            p.actions = 1
    else:
        state.turn = 1 - state.turn

    return state


# ===================== 视图函数（用于网络层过滤信息） =====================

def get_public_board(state: GameState) -> list[list[str]]:
    """双方可见的地图（仅格子类型）"""
    return [[cell.value for cell in row] for row in state.board]


def get_player_view(state: GameState, pid: str) -> dict:
    """某玩家看到的完整视图"""
    player = get_player(state, pid)
    return {
        "board": get_public_board(state),
        "phase": state.phase.value,
        "round": state.round,
        "turn": state.turn,
        "is_my_turn": state.players[state.turn].pid == pid,
        "my_tigers": [{"id": t.tid, "x": t.x, "y": t.y} for t in player.field],
        "my_total_left": player.total_left,
        "my_cooldowns": {
            "place": player.place_cd,
            "land": player.land_cd,
            "attack": player.attack_cd,
            "mow": player.mow_cd,
            "ear": player.ear_cd,
            "seed": player.seed_cd,
            "stealth": player.stealth_cd,
        },
        "my_actions": player.actions,
    }


def get_public_events(state: GameState) -> list[dict]:
    """所有玩家可见的事件"""
    return [e for e in state.events if e.get("visibility") == "public"]


def get_private_events(state: GameState, pid: str) -> list[dict]:
    """对某玩家可见的私有事件"""
    return [
        e for e in state.events
        if e.get("visibility") == "private" and e.get("target") == pid
    ]
