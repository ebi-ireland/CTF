#!/usr/bin/env python3
"""
CTF Solver: Endless (inspired by coolmathgames.com/0-run)
nc endless.zerodays.events 8100

Strategy:
  1. Connect and read the initial banner / game state
  2. Parse the level map to find safe tiles and the player position
  3. Send movement commands to navigate without falling off
  4. Repeat for as many levels as needed until the flag appears
"""

from pwn import *
import re
import time

HOST = "endless.zerodays.events"
PORT = 8100

# Tune these if the server is slow
RECV_TIMEOUT = 3
MOVE_DELAY   = 0.05   # seconds between moves


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def connect():
    r = remote(HOST, PORT)
    log.info("Connected")
    return r


def recv_all(r, timeout=RECV_TIMEOUT):
    """Drain everything available from the socket."""
    data = b""
    try:
        while True:
            chunk = r.recv(timeout=timeout)
            if not chunk:
                break
            data += chunk
    except EOFError:
        pass
    return data.decode(errors="replace")


# ---------------------------------------------------------------------------
# Map parsing
# ---------------------------------------------------------------------------

# Characters we consider "solid" (safe to stand on / move onto)
SAFE  = set(" .#_=[]")
VOID  = set("X ")   # holes / empty space the player falls into
PLAYER_CHARS = set("@PO>^<v")

def parse_map(text):
    """
    Return (grid, player_row, player_col) where grid is a list of strings.
    Handles ANSI escape codes by stripping them first.
    """
    ansi_escape = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07')
    clean = ansi_escape.sub('', text)

    lines = clean.splitlines()
    grid = []
    player_pos = None

    for r, line in enumerate(lines):
        grid.append(line)
        for c, ch in enumerate(line):
            if ch in PLAYER_CHARS:
                player_pos = (r, c)

    return grid, player_pos


def is_safe_tile(grid, row, col):
    """True if the tile at (row, col) is solid (not a hole)."""
    if row < 0 or row >= len(grid):
        return False
    line = grid[row]
    if col < 0 or col >= len(line):
        return False
    ch = line[col]
    return ch not in {' ', 'X', '\x00'}


def find_safe_move(grid, pr, pc):
    """
    Very simple greedy: try to move right first, then stay, then left.
    The Run game is a side-scroller so 'right' is usually forward.
    We also need to handle gravity (player must land on a tile below).
    Returns one of: 'r', 'l', 'j' (jump), 'n' (noop / wait)
    """
    # Check tile below (gravity)
    below = pr + 1

    # Right
    if is_safe_tile(grid, pr, pc + 1) or is_safe_tile(grid, below, pc + 1):
        return 'r'

    # Jump over gap to the right
    if not is_safe_tile(grid, pr, pc + 1) and is_safe_tile(grid, pr, pc + 2):
        return 'j'

    # Left as fallback
    if is_safe_tile(grid, pr, pc - 1):
        return 'l'

    # Jump
    return 'j'


# ---------------------------------------------------------------------------
# Key-mapping variants to try
# ---------------------------------------------------------------------------

MOVE_MAPS = [
    # (right, left, jump/up)
    {'r': b'r', 'l': b'l', 'j': b' ', 'n': b''},
    {'r': b'd', 'l': b'a', 'j': b'w', 'n': b''},
    {'r': b'\x1b[C', 'l': b'\x1b[D', 'j': b'\x1b[A', 'n': b''},   # arrow keys
    {'r': b'6', 'l': b'4', 'j': b'8', 'n': b'5'},                   # numpad
]

current_map = MOVE_MAPS[0]


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def solve():
    global current_map

    r = connect()

    # Read the welcome/banner
    time.sleep(0.5)
    banner = recv_all(r, timeout=2)
    log.info("Banner received (%d bytes)", len(banner))
    print(banner[:800])

    # If there's an initial prompt (name, ready?, etc.) just send Enter
    if '?' in banner or ':' in banner or '>' in banner:
        r.sendline(b'')
        time.sleep(0.3)
        banner += recv_all(r, timeout=1)

    flag_re = re.compile(r'[A-Za-z0-9_]+\{[^}]+\}')

    level = 0
    moves_this_level = 0
    MAX_MOVES = 5000   # bail out if stuck forever

    while True:
        # Read current frame
        time.sleep(MOVE_DELAY)
        frame_raw = recv_all(r, timeout=RECV_TIMEOUT)

        if not frame_raw:
            log.warning("No data received, connection may be closed")
            break

        # Check for flag
        flags = flag_re.findall(frame_raw)
        if flags:
            log.success("FLAG FOUND: %s", flags)
            print("\n" + "="*60)
            for f in flags:
                print("FLAG:", f)
            print("="*60 + "\n")
            break

        # Check for win/level-up messages
        if any(kw in frame_raw.lower() for kw in ['level', 'congratulations', 'next', 'win', 'complete']):
            log.info("Level transition detected: %s", frame_raw[:120].strip())
            level += 1
            moves_this_level = 0
            time.sleep(0.5)
            # Might need to press enter/space to continue
            r.send(b'\n')
            time.sleep(0.3)
            continue

        # Parse the map
        grid, pos = parse_map(frame_raw)

        if pos is None:
            # Can't find player — try sending a neutral key and continue
            log.warning("Player position not found in frame, sending noop")
            r.send(b'\n')
            moves_this_level += 1
        else:
            pr, pc = pos
            move = find_safe_move(grid, pr, pc)
            key = current_map[move]
            if key:
                r.send(key)
            moves_this_level += 1

        if moves_this_level > MAX_MOVES:
            log.warning("Exceeded max moves for level %d, aborting", level)
            break

    # Final drain — maybe flag appeared after loop
    time.sleep(1)
    final = recv_all(r, timeout=2)
    if final:
        flags = flag_re.findall(final)
        if flags:
            log.success("FLAG (final drain): %s", flags)
        print(final[:500])

    r.close()


if __name__ == '__main__':
    solve()