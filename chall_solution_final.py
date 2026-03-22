#!/usr/bin/env python3
"""
Quantum Collapse - CTF Solution (Sage不要・純粋Python+numpy)
============================================================

解法: Gray code + Meet-in-the-Middle (MITM) による全空間探索
  x を前半 x_A (13bit) と後半 x_B (13bit) に分割。
  x_B の全組み合わせ (8192通り) を Gray code で高速列挙し、
  x_A の各値について numpy で一括チェック。
  推定実行時間: ~30-60秒 (Sageなし)

Usage:
  python chall_solution_final.py <host> <port>
  python chall_solution_final.py           # ローカルJSON入力テスト
"""

import sys
import json
import hashlib
import socket
import re
import time

import numpy as np


# ─── 評価関数（検証用）──────────────────────────────────────────────────────

def eval_public(bitrows, sig):
    n = len(sig)
    out = []
    for i in range(n):
        row = bitrows[i]
        acc = 0
        idx = 0
        for j in range(n):
            sj = sig[j]
            for k in range(n):
                if row[idx] == '1' and sj and sig[k]:
                    acc ^= 1
                idx += 1
        out.append(acc)
    return out


# ─── メインソルバー ──────────────────────────────────────────────────────────

def solve(public):
    n      = public['n']
    target = public['target']
    bitrows = public['A_bitrows']
    m = n // 2  # 分割点 (26//2 = 13)

    print(f"[*] n={n}, m={m}, target_weight={sum(target)}")

    # ── 事前処理: col_packed[j][k] = A[:,j*n+k] を n-bit整数に詰める ──
    # col_packed[j,k] のビット r が立っている ⟺ A[r][j*n+k] == '1'
    print("[*] Building packed column table...")
    col_packed = np.zeros((n, n), dtype=np.int64)
    for j in range(n):
        for k in range(n):
            val = 0
            for r in range(n):
                if bitrows[r][j * n + k] == '1':
                    val |= (1 << r)
            col_packed[j, k] = val

    # target を n-bit 整数に
    target_int = 0
    for r, t in enumerate(target):
        if t:
            target_int |= (1 << r)

    # ── Step 1: 純粋B部分 (j>=m, k>=m) の Gray code テーブル構築 ──
    # pure_B[xb_gray] = XOR of col_packed[m+j, m+k] for j,k where x_B[j] and x_B[k]
    print("[*] Precomputing pure_B table (2^13 entries)...")
    t0 = time.time()
    pure_B = np.zeros(2**m, dtype=np.int64)
    prev_gray = 0
    for xb in range(1, 2**m):
        gray_xb  = xb ^ (xb >> 1)
        flipped  = gray_xb ^ prev_gray          # どのビットが反転したか
        q        = flipped.bit_length() - 1     # 反転したビット位置 (0-indexed in B)
        Q        = m + q                        # 絶対インデックス

        # bit q を x_B に追加/削除したときの純B寄与の変化:
        # Δ = col[Q,Q] XOR (XOR over k in x_B_new \ {q}: col[Q, m+k] XOR col[m+k, Q])
        contrib = int(col_packed[Q, Q])
        cur_b = gray_xb ^ (1 << q)             # q を除いた x_B
        for k in range(m):
            if (cur_b >> k) & 1:
                contrib ^= int(col_packed[Q, m+k]) ^ int(col_packed[m+k, Q])

        pure_B[gray_xb] = pure_B[prev_gray] ^ contrib
        prev_gray = gray_xb

    print(f"    done in {time.time()-t0:.2f}s")

    # ── Step 2: x_A を Gray code で列挙 ──
    print("[*] Enumerating x_A (2^13 values) with vectorized x_B check...")
    t0 = time.time()

    # x_A の Gray code 管理
    part_AA    = 0                          # 純A部分の現在値
    cross_mat  = np.zeros(m, dtype=np.int64)  # cross_mat[q] = x_B[q] の係数
    xa_gray    = 0

    total_xa = 2**m
    found = None

    for xa in range(1, total_xa + 1):
        # ── Gray code で x_A の次の値へ ──
        new_xa_gray = xa ^ (xa >> 1) if xa < total_xa else 0
        flipped_xa  = new_xa_gray ^ xa_gray
        p           = flipped_xa.bit_length() - 1  # 反転したA-bit位置

        if xa < total_xa:
            # x_A の bit p が反転 → 純A部分と cross_mat を更新
            P = p  # 絶対インデックス (A側は 0..m-1)

            # 純A部分の更新: Δ = col[P,P] XOR (XOR over j in new_xa_gray \ {p}: col[P,j] XOR col[j,P])
            delta_AA = int(col_packed[P, P])
            cur_a_without_p = new_xa_gray ^ (1 << p)
            for j in range(m):
                if (cur_a_without_p >> j) & 1:
                    delta_AA ^= int(col_packed[P, j]) ^ int(col_packed[j, P])
            part_AA ^= delta_AA

            # cross_mat の更新: bit p のx_A への追加/削除
            # cross_mat[q] ^= col[P, m+q] XOR col[m+q, P]  for all q
            for q in range(m):
                cross_mat[q] ^= int(col_packed[P, m+q]) ^ int(col_packed[m+q, P])

            xa_gray = new_xa_gray
        else:
            xa_gray = 0

        # ── x_B の全組み合わせを numpy で一括チェック ──
        # cross_contrib[xb_gray] = XOR of cross_mat[q] for q in x_B
        # これを Gray code で構築 (numpy)
        cross_contrib = np.zeros(2**m, dtype=np.int64)
        prev_gray_b = 0
        for xb in range(1, 2**m):
            gray_xb = xb ^ (xb >> 1)
            flipped_b = gray_xb ^ prev_gray_b
            q = flipped_b.bit_length() - 1
            cross_contrib[gray_xb] = cross_contrib[prev_gray_b] ^ cross_mat[q]
            prev_gray_b = gray_xb

        # f(x_A, x_B) = part_AA XOR cross_contrib[xb] XOR pure_B[xb]
        result = part_AA ^ cross_contrib ^ pure_B

        # target_int と一致する x_B を探す
        matches = np.where(result == target_int)[0]
        if len(matches) > 0:
            xb_gray = int(matches[0])
            # x_A, x_B を復元
            x = []
            for bit in range(m):
                x.append((xa_gray >> bit) & 1)
            for bit in range(m):
                x.append((xb_gray >> bit) & 1)

            # 全ゼロ除外
            if not any(x):
                continue

            # 検証
            got = eval_public(bitrows, x)
            if got == target:
                elapsed = time.time() - t0
                print(f"[*] Found solution! x_A={hex(xa_gray)}, x_B={hex(xb_gray)}")
                print(f"[*] Elapsed: {elapsed:.1f}s ({xa} / {total_xa} x_A values tried)")
                found = x
                break

        if xa % 500 == 0:
            elapsed = time.time() - t0
            rate = xa / elapsed if elapsed > 0 else 0
            eta = (total_xa - xa) / rate if rate > 0 else 0
            print(f"    Progress: {xa}/{total_xa} x_A ({100*xa/total_xa:.1f}%) "
                  f"elapsed={elapsed:.1f}s ETA={eta:.0f}s")

    if found is None:
        print("[!] No solution found in full search")
    return found


# ─── PoW ──────────────────────────────────────────────────────────────────

def solve_pow(prefix, target_hex):
    print(f"[PoW] Mining sha256('{prefix}' + nonce) starts with '{target_hex}'...")
    i = 0
    t0 = time.time()
    while True:
        nonce = str(i)
        h = hashlib.sha256((prefix + nonce).encode()).hexdigest()
        if h.startswith(target_hex):
            print(f"[PoW] Found: nonce={nonce} in {time.time()-t0:.1f}s")
            return nonce
        i += 1
        if i % 1_000_000 == 0:
            print(f"[PoW] Tried {i}...")


# ─── ネットワーク ──────────────────────────────────────────────────────────

def recvuntil(sock, delim):
    if isinstance(delim, str):
        delim = delim.encode()
    data = b""
    while not data.endswith(delim):
        c = sock.recv(1)
        if not c:
            break
        data += c
    return data.decode(errors="replace")


def interact(host, port):
    print(f"[*] Connecting to {host}:{port}")
    sock = socket.socket()
    sock.settimeout(300)
    sock.connect((host, port))

    # バナーを読む (PoW プロンプトまで)
    banner = recvuntil(sock, "pow nonce> ")
    print(banner)

    # PoW を解く
    m = re.search(r"sha256\('([^']+)' \+ nonce\) starts with (\S+)", banner)
    if m:
        prefix, target_hex = m.group(1), m.group(2)
        nonce = solve_pow(prefix, target_hex)
        sock.sendall((nonce + "\n").encode())
        resp = recvuntil(sock, "\n")
        print(resp.strip())

    # JSON公開データを受け取る
    data = recvuntil(sock, "signature> ")

    m2 = re.search(r'(\{"n":.+?\})', data, re.DOTALL)
    if not m2:
        print("[!] Could not parse JSON")
        print("Raw:", data[:300])
        return

    public = json.loads(m2.group(1))
    print(f"[*] Got instance: n={public['n']}, d={public['d']}")

    # 解く
    result = solve(public)
    if result is None:
        print("[!] No solution found")
        sock.close()
        return

    sig_json = json.dumps({"signature": result}, separators=(',', ':'))
    print(f"[*] Sending signature...")
    sock.sendall((sig_json + "\n").encode())

    response = sock.recv(4096).decode(errors="replace")
    print("[*] Server response:")
    print(response)
    sock.close()


# ─── ローカルテスト ────────────────────────────────────────────────────────

def local_test():
    print("[*] Local test mode")
    print("[*] Paste the JSON public data (one line) and press Enter:")
    try:
        line = sys.stdin.readline().strip()
        if not line:
            raise ValueError("empty")
        public = json.loads(line)
    except Exception:
        # 自作のn=6テストケース (Sageなしで検証可能)
        print("[*] No valid JSON input, using n=6 synthetic test...")
        n = 6
        import random
        random.seed(1337)
        # ランダムな二次系を作って secret_sig を作成し target を計算
        bitrows = []
        for r in range(n):
            row = ''.join(str(random.randint(0,1)) for _ in range(n*n))
            bitrows.append(row)
        secret = [random.randint(0,1) for _ in range(n)]
        if not any(secret):
            secret[0] = 1
        target = eval_public(bitrows, secret)
        public = {'n': n, 'd': 2, 'target': target, 'A_bitrows': bitrows}
        print(f"[*] Secret (answer): {secret}")
        print(f"[*] Target: {target}")

    result = solve(public)
    if result:
        got = eval_public(public['A_bitrows'], result)
        print(f"\n[*] Solution:   {result}")
        print(f"[*] Evaluation: {got}")
        print(f"[*] Target:     {public['target']}")
        print(f"[*] Correct:    {got == public['target']}")
    else:
        print("[!] No solution found")


# ─── エントリポイント ──────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) == 3:
        interact(sys.argv[1], int(sys.argv[2]))
    elif len(sys.argv) == 2:
        print("Usage: python chall_solution_final.py <host> <port>")
    else:
        local_test()