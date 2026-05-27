"""Flask-SocketIO 服务器：局域网对战"""
import os
import random
from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit
from game_state import create_game, GamePhase
from game_logic import take_action, snitch, get_player_view

app = Flask(__name__, static_url_path='', static_folder='static')
app.config['SECRET_KEY'] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*")

# ===================== 服务端状态 =====================
lobby = []          # [{sid, id, nickname}]
counter = 0
games = {}          # game_id -> GameInfo

class GameInfo:
    def __init__(self, state, p1_sid, p2_sid, p1_nick, p2_nick):
        self.state = state
        self.p1 = p1_sid
        self.p2 = p2_sid
        self.p1_nick = p1_nick
        self.p2_nick = p2_nick
        self.p1_event_idx = 0
        self.p2_event_idx = 0

def new_id():
    global counter; counter += 1; return f"p{counter}"

# ===================== 路由 =====================
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# ===================== Socket.IO 事件 =====================

@socketio.on('join')
def on_join(data):
    sid = request.sid
    nick = data.get('nickname', '匿名')

    # 重复加入则更新昵称
    for p in lobby:
        if p['sid'] == sid:
            p['nickname'] = nick
            emit('joined', {'id': p['id']})
            _broadcast_lobby(); return

    pid = new_id()
    lobby.append({'sid': sid, 'id': pid, 'nickname': nick})
    emit('joined', {'id': pid})
    _broadcast_lobby()


@socketio.on('start_game')
def on_start():
    global lobby
    if len(lobby) < 2:
        emit('error', {'msg': '至少需要2名玩家'})
        return

    # 随机分配先后手
    p1, p2 = random.sample(lobby, 2)

    state = create_game()
    gid = str(id(state))
    games[gid] = GameInfo(state, p1['sid'], p2['sid'], p1['nickname'], p2['nickname'])

    # 从大厅移除
    lobby = [p for p in lobby if p['sid'] not in (p1['sid'], p2['sid'])]
    _broadcast_lobby()

    # 通知双方
    emit('game_start', {
        'game_id': gid, 'your_pid': 'p1',
        'opponent': p2['nickname'], 'player_order': ['p1', 'p2'],
    }, to=p1['sid'])
    emit('game_start', {
        'game_id': gid, 'your_pid': 'p2',
        'opponent': p1['nickname'], 'player_order': ['p1', 'p2'],
    }, to=p2['sid'])
    _send_game_update(gid)


@socketio.on('action')
def on_action(data):
    sid = request.sid
    gid = data.get('game_id')
    if gid not in games:
        emit('error', {'msg': '游戏不存在'}); return

    g = games[gid]
    if sid == g.p1: pid = 'p1'
    elif sid == g.p2: pid = 'p2'
    else: emit('error', {'msg': '不在游戏中'}); return

    try:
        g.state = take_action(g.state, pid, data['action'])
        _send_game_update(gid)
        if g.state.phase == GamePhase.ENDED:
            emit('game_over', {'winner': g.state.winner}, to=g.p1)
            emit('game_over', {'winner': g.state.winner}, to=g.p2)
    except ValueError as e:
        emit('error', {'msg': str(e)})


@socketio.on('snitch')
def on_snitch(data):
    sid = request.sid; gid = data.get('game_id')
    if gid not in games: return
    g = games[gid]
    pid = 'p1' if sid == g.p1 else ('p2' if sid == g.p2 else None)
    if not pid: return
    try:
        g.state = snitch(g.state, pid, data['x'], data['y'])
        _send_game_update(gid)
        if g.state.phase == GamePhase.ENDED:
            emit('game_over', {'winner': g.state.winner}, to=g.p1)
            emit('game_over', {'winner': g.state.winner}, to=g.p2)
    except ValueError as e:
        emit('error', {'msg': str(e)})


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    # 从大厅移除
    global lobby
    lobby = [p for p in lobby if p['sid'] != sid]
    _broadcast_lobby()

    # 处理游戏中断线
    for gid, g in list(games.items()):
        other = None
        if sid == g.p1: other = g.p2; nick = g.p1_nick
        elif sid == g.p2: other = g.p1; nick = g.p2_nick
        if other:
            emit('opponent_left', {'nick': nick}, to=other)
            del games[gid]; break


# ===================== 广播函数 =====================

def _broadcast_lobby():
    emit('lobby_update', {
        'players': [{'id': p['id'], 'nickname': p['nickname']} for p in lobby]
    }, broadcast=True)


def _send_game_update(gid):
    g = games[gid]
    s = g.state
    for sid, pid, idx_attr in [(g.p1, 'p1', 'p1_event_idx'), (g.p2, 'p2', 'p2_event_idx')]:
        view = get_player_view(s, pid)
        idx = getattr(g, idx_attr)
        events = [e for e in s.events[idx:]
                  if e.get('visibility') == 'public'
                  or (e.get('visibility') == 'private' and e.get('target') == pid)]
        setattr(g, idx_attr, len(s.events))
        emit('game_update', {
            'phase': s.phase.value,
            'round': s.round,
            'is_my_turn': s.players[s.turn].pid == pid,
            'board': view['board'],
            'my_tigers': view['my_tigers'],
            'my_total_left': view['my_total_left'],
            'my_cooldowns': view['my_cooldowns'],
            'my_actions': view['my_actions'],
            'events': events,
        }, to=sid)


# ===================== 启动 =====================
if __name__ == '__main__':
    print("=" * 50)
    print("  老虎棋 服务器启动")
    print("  本机地址: http://localhost:5000")
    print("  局域网地址: http://<本机IP>:5000")
    print("=" * 50)
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
