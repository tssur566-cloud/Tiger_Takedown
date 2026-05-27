"""游戏核心数据结构 - 纯数据，无逻辑"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

# ===================== 常量 =====================
BOARD_SIZE = 10
INITIAL_X1, INITIAL_Y1 = 1, 1
INITIAL_X2, INITIAL_Y2 = 4, 4
TIGERS_PER_PLAYER = 5
MAX_TIGERS_ON_FIELD = 3

DIRECTIONS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


class CellType(str, Enum):
    VOID = "void"
    EMPTY = "empty"
    GRASS = "grass"


class GamePhase(str, Enum):
    PLACEMENT = "placement"
    PLAYING = "playing"
    ENDED = "ended"


# ===================== 数据类 =====================
@dataclass
class Tiger:
    tid: str
    pid: str
    x: int
    y: int
    was_on_empty: bool = False  # 上个回合开始时是否在空地


@dataclass
class PlayerState:
    pid: str
    total_left: int = TIGERS_PER_PLAYER     # 剩余老虎总数（含场上）
    field: list[Tiger] = field(default_factory=list)  # 场上的老虎

    # 冷却（每个自己回合开始时 -1，到 0 可用）
    place_cd: int = 0
    land_cd: int = 0
    attack_cd: int = 0
    mow_cd: int = 0
    ear_cd: int = 0
    seed_cd: int = 0
    stealth_cd: int = 0

    # 本回合可操作次数
    actions: int = 1

    def get_cd(self, op: str) -> int:
        return getattr(self, f"{op}_cd", 0)

    def set_cd(self, op: str, val: int):
        setattr(self, f"{op}_cd", val)

    def tick_cds(self):
        """自己回合开始时：所有冷却 -1"""
        for op in ("place", "land", "attack", "mow", "ear", "seed", "stealth"):
            cd = self.get_cd(op)
            if cd > 0:
                self.set_cd(op, cd - 1)

    def can_use(self, op: str) -> bool:
        return self.get_cd(op) == 0


@dataclass
class GameState:
    board: list[list[CellType]]          # board[y][x]
    players: list[PlayerState]           # [0]=先手, [1]=后手
    phase: GamePhase = GamePhase.PLACEMENT
    round: int = 1                       # 第几回合（1=放置回合）
    turn: int = 0                        # 0=先手行动, 1=后手行动
    placement_step: int = 0              # 放置阶段计数 0~5
    _tiger_counter: int = 0
    winner: Optional[str] = None
    events: list[dict] = field(default_factory=list)  # 本回合事件日志

    def _next_tiger_id(self) -> str:
        self._tiger_counter += 1
        return f"t{self._tiger_counter}"


# ===================== 工厂函数 =====================

def create_game() -> GameState:
    """创建初始游戏状态"""
    board = [[CellType.VOID] * BOARD_SIZE for _ in range(BOARD_SIZE)]

    # 初始化 (2,2)-(5,5) 草地
    for y in range(INITIAL_Y1, INITIAL_Y2 + 1):
        for x in range(INITIAL_X1, INITIAL_X2 + 1):
            board[y][x] = CellType.GRASS

    p1 = PlayerState(pid="p1")
    p2 = PlayerState(pid="p2")

    return GameState(board=board, players=[p1, p2], phase=GamePhase.PLACEMENT)


# ===================== 坐标/状态 查询 =====================

def in_bounds(x: int, y: int) -> bool:
    return 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE


def is_initial_area(x: int, y: int) -> bool:
    return INITIAL_X1 <= x <= INITIAL_X2 and INITIAL_Y1 <= y <= INITIAL_Y2


def get_cell(board: list[list[CellType]], x: int, y: int) -> Optional[CellType]:
    if not in_bounds(x, y):
        return None
    return board[y][x]


def player_tigers_on_field(state: GameState, pid: str) -> list[Tiger]:
    for p in state.players:
        if p.pid == pid:
            return p.field
    return []


def find_tiger(state: GameState, pid: str, x: int, y: int) -> Optional[Tiger]:
    """在指定坐标找某玩家的老虎"""
    for t in player_tigers_on_field(state, pid):
        if t.x == x and t.y == y:
            return t
    return None


def opponent_id(pid: str) -> str:
    return "p2" if pid == "p1" else "p1"


def get_player(state: GameState, pid: str) -> Optional[PlayerState]:
    for p in state.players:
        if p.pid == pid:
            return p
    return None


def get_opponent(state: GameState, pid: str) -> Optional[PlayerState]:
    return get_player(state, opponent_id(pid))
