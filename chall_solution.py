#!/usr/bin/env sage
"""
Quantum Collapse - CTF Solution (Sage script)
=============================================

Problem:
  公開行列 A (n×n²) と target ∈ F2^n が与えられる。
  target[i] = Σ_{j,k} A[i][j*n+k] * x[j] * x[k]  (mod 2) となる x ∈ F2^n を求める。

数学的構造:
  A = T * M * (L1 ⊗ L2·L1) * (S ⊗ S)   (HFE 系の多変数二次暗号)
  これは n=26 変数、次数2 の MQ (Multivariate Quadratic) 問題。

解法: Gröbner 基底 (F4/F5 アルゴリズム)
  Sage の built-in F4/F5 実装を使う。
  HFE(d=10, n=26) の degree of regularity ≈ 5-6 なので実用的に解ける。

Usage:
  sage chall_solution_sage.py [host port]
  sage chall_solution_sage.py          # stdin から JSON を読む (ローカルテスト用)
"""

import sys
import json
import hashlib
import socket
import re
import time

from sage.all import (
    GF, PolynomialRing, vector, ZZ
)


# ─── 評価関数 ─────────────────────────────────────────────────────────────

def eval_public(bitrows, sig):
    """公開写像を sig で評価。sig はビットのリスト (0/1)。"""
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


# ─── ソルバー ──────────────────────────────────────────────────────────────

def solve_groebner(public):
    """
    Gröbner 基底を使って MQ 系を解く。
    
    手順:
    1. F2 上の多変数多項式環 R = F2[x0, ..., x_{n-1}] を作る
    2. 各 target[i] に対して二次多項式 f_i(x) - target[i] を作る
    3. フィールド方程式 x_i^2 - x_i = 0 を追加 (F2 上なので x_i ∈ {0,1})
    4. イデアル I を Gröbner 基底で解く
    5. I.variety() で解を列挙
    """
    n = public['n']
    target = public['target']
    bitrows = public['A_bitrows']
    
    print(f"[Groebner] n={n}, setting up polynomial ring over F2...")
    
    F2 = GF(2)
    var_names = ['x%d' % i for i in range(n)]
    
    # graded reverse lex order が F4/F5 に最適
    R = PolynomialRing(F2, var_names, order='degrevlex')
    xs = R.gens()
    
    print(f"[Groebner] Building {n} quadratic equations...")
    
    polys = []
    
    # target[i] = Σ_{j,k} A[i][j*n+k] * x[j] * x[k]
    for i in range(n):
        bitrow = bitrows[i]
        fi = R.zero()
        idx = 0
        for j in range(n):
            for k in range(n):
                if bitrow[idx] == '1':
                    fi += xs[j] * xs[k]
                idx += 1
        # fi(x) = target[i]  →  fi(x) + target[i] = 0  (over F2, + = -)
        polys.append(fi + F2(target[i]))
    
    # フィールド方程式: x_i^2 + x_i = 0  (x_i ∈ {0,1})
    for x in xs:
        polys.append(x**2 + x)
    
    print(f"[Groebner] Total polynomials: {len(polys)} ({n} quadratic + {n} field eqs)")
    print(f"[Groebner] Computing Groebner basis (this may take a while)...")
    
    t0 = time.time()
    I = R.ideal(polys)
    
    # Sage は内部的に Singular の F4/F5 を使う
    # libsingular が利用可能なら高速
    try:
        # まず軽い方法を試す
        gb = I.groebner_basis('libsingular:slimgb')
        print(f"[Groebner] Basis computed with slimgb in {time.time()-t0:.1f}s, size={len(gb)}")
    except Exception as e:
        print(f"[Groebner] slimgb failed ({e}), trying default...")
        gb = I.groebner_basis()
        print(f"[Groebner] Basis computed in {time.time()-t0:.1f}s, size={len(gb)}")
    
    # 解の列挙
    print(f"[Groebner] Enumerating solutions...")
    t1 = time.time()
    
    try:
        varieties = I.variety()
        print(f"[Groebner] Found {len(varieties)} solutions in {time.time()-t1:.1f}s")
        
        for sol_dict in varieties:
            x = [int(sol_dict[xi]) for xi in xs]
            if not any(x):
                continue  # 全ゼロは除外
            
            # 検証
            got = eval_public(bitrows, x)
            if got == target:
                print(f"[Groebner] Verified solution found!")
                return x
            else:
                print(f"[Groebner] Warning: solution doesn't verify! (Groebner bug?)")
        
        print(f"[Groebner] No valid solution found in variety")
        return None
        
    except Exception as e:
        print(f"[Groebner] variety() failed: {e}")
        print(f"[Groebner] Trying manual back-substitution from GB...")
        return solve_from_gb(gb, xs, n, target, bitrows)


def solve_from_gb(gb, xs, n, target, bitrows):
    """
    Gröbner 基底から手動で解を構築する。
    GB が三角形式なら後退代入で解ける。
    """
    print(f"[GB-back] Groebner basis has {len(gb)} elements")
    
    # GB が univariate 多項式を含むか確認
    univariate = []
    for poly in gb:
        vars_used = poly.variables()
        if len(vars_used) == 1:
            univariate.append((vars_used[0], poly))
    
    print(f"[GB-back] Univariate polys in GB: {len(univariate)}")
    
    if not univariate:
        print(f"[GB-back] No univariate polys -- system may have no solution or GB is not triangular")
        return None
    
    # 各 univariate 多項式の根を求める
    F2 = GF(2)
    partial_sols = [{}]
    
    for var, poly in univariate:
        new_sols = []
        for partial in partial_sols:
            # この変数に値を代入して試す
            for val in [F2(0), F2(1)]:
                test_poly = poly.subs({var: val})
                if test_poly == 0:
                    new_partial = dict(partial)
                    new_partial[var] = int(val)
                    new_sols.append(new_partial)
        partial_sols = new_sols
        if not partial_sols:
            break
    
    print(f"[GB-back] Partial solutions after univariate: {len(partial_sols)}")
    
    for partial in partial_sols:
        if len(partial) == n:
            x = [partial.get(xi, 0) for xi in xs]
            got = eval_public(bitrows, x)
            if got == target:
                return x
    
    return None


def solve_xl(public, max_degree=5):
    """
    XL (eXtended Linearization) アルゴリズム。
    degree D まで単項式を掛けて線形系を作り、Gauss 消去で解く。
    
    Gröbner より軽量だが、D を上げるとメモリ使用量が爆発する。
    n=26 なら D=5 で eqs/vars ≈ 0.92 (まだ不足)、D=6 で 1.48 (過決定)。
    D=6 は変数 313K × 方程式 465K -- メモリ的に厳しい。
    
    実用的には D=5 で試して、解が見つからなければ Gröbner に頼る。
    """
    n = public['n']
    target = public['target']
    bitrows = public['A_bitrows']
    
    print(f"[XL] Starting XL at max_degree={max_degree}")
    
    from itertools import combinations
    from math import comb
    
    # 次数 <= max_degree の多重線形単項式を列挙
    # F2 上なので x_i^2 = x_i (multilinear のみ)
    def all_monomials(n, max_deg):
        """全ての部分集合 S ⊆ {0..n-1}, |S| <= max_deg を列挙。x_S = prod_{i∈S} x_i"""
        for d in range(max_deg + 1):
            for subset in combinations(range(n), d):
                yield subset  # () は定数項 1
    
    # 次数 <= D-2 の単項式で掛ける（元の方程式が次数2なので）
    mult_monomials = list(all_monomials(n, max_degree - 2))
    source_monomials = list(all_monomials(n, max_degree))
    
    num_vars = len(source_monomials)
    num_eqs_raw = n * len(mult_monomials)
    
    print(f"[XL] Degree {max_degree}: {num_vars} vars, {num_eqs_raw} equations (before dedup)")
    
    # 単項式インデックス
    mono_to_idx = {m: i for i, m in enumerate(source_monomials)}
    
    # 行列を構築 (各行は num_vars+1 bits)
    # メモリ効率のため dict of set を使う
    print(f"[XL] Building equation matrix...")
    
    # 各方程式 i を mult_mono で掛けて展開
    # 元の方程式: Σ_{j,k} A[i][j*n+k] * x[j]*x[k] + target[i] = 0
    # × x_S (mult_mono S): Σ_{j,k} A[i][j*n+k] * x_S * x[j]*x[k] + target[i]*x_S = 0
    # x_S * x[j] * x[k] = x_{S ∪ {j,k}}  (set union, multilinear)
    
    # 行列は (num_eqs × (num_vars+1)) over F2
    # Python の int をビットマスクとして使う（列ベクトル）
    # cols[col_idx] = int bitmask over equations
    
    # 実は行ベクトル方式の方が Gauss 消去しやすい
    rows = []
    
    eq_count = 0
    for mult_mono in mult_monomials:
        mult_set = set(mult_mono)
        
        for i in range(n):
            bitrow = bitrows[i]
            row = [0] * (num_vars + 1)  # +1 for RHS
            
            # 定数項 target[i] * x_{mult_mono}
            rhs_mono = tuple(sorted(mult_set))
            if rhs_mono in mono_to_idx:
                row[num_vars] ^= target[i]  # RHS
                # Actually: target[i] * x_S contributes to row[mono_to_idx[rhs_mono]]
                # Wait -- let me reconsider the setup.
                # We're linearizing: treat each monomial as a NEW variable y_S.
                # Equation: Σ_{S} coeff_S * y_S = 0
                # RHS is implicit (moved to left side as 0)
                # The constant term (empty mono) is the RHS.
                pass
            
            # 二次項の処理
            idx = 0
            for j in range(n):
                for k in range(n):
                    if bitrow[idx] == '1':
                        # Monomial: x_{mult_mono ∪ {j} ∪ {k}}
                        new_set = mult_set | {j, k}
                        new_mono = tuple(sorted(new_set))
                        if len(new_mono) <= max_degree and new_mono in mono_to_idx:
                            row[mono_to_idx[new_mono]] ^= 1
                    idx += 1
            
            # 定数項 (RHS)
            # target[i] × x_mult_mono
            # When mult_mono is the empty set (degree 0), this is just target[i]
            # This goes to the constant monomial () = index 0
            rhs_contribution = tuple(sorted(mult_set))
            if rhs_contribution in mono_to_idx:
                # This monomial times target[i] -- moves to other side
                # Actually: fi * x_S = target[i] * x_S
                # So: fi * x_S - target[i] * x_S = 0
                # The constant in fi * x_S - target[i] * x_S is -target[i]*x_S
                # But target[i] is known -- it's in the RHS of the linear system
                # If we let Y_S = y_S, the system is:
                # Σ_S coeff * Y_S = Σ_S (target[i]*x_S_coeff) * Y_S   (for empty subset mult)
                # This is getting complicated. Let me simplify.
                
                # Simpler: move target[i] * x_S to RHS
                # LHS: Σ_{deg-2 terms} coeff * Y_S
                # RHS: target[i] * x_S = target[i] * Y_{mult_mono}
                row[mono_to_idx[rhs_contribution]] ^= target[i]
            
            rows.append(row)
            eq_count += 1
    
    print(f"[XL] Matrix: {len(rows)} × {num_vars+1}")
    print(f"[XL] Running Gaussian elimination over F2...")
    
    # Gaussian elimination
    t0 = time.time()
    pivot_row = 0
    pivot_cols = []
    m = rows
    num_rows = len(m)
    
    for col in range(num_vars):
        # Find pivot
        found = -1
        for r in range(pivot_row, num_rows):
            if m[r][col]:
                found = r
                break
        
        if found == -1:
            continue
        
        m[pivot_row], m[found] = m[found], m[pivot_row]
        pivot_cols.append(col)
        
        # Eliminate
        for r in range(num_rows):
            if r != pivot_row and m[r][col]:
                for c in range(num_vars + 1):
                    m[r][c] ^= m[pivot_row][c]
        
        pivot_row += 1
        
        if pivot_row % 100 == 0:
            print(f"[XL]   pivots found: {pivot_row}/{num_vars} (col={col})")
    
    print(f"[XL] Gauss done in {time.time()-t0:.1f}s. Rank={len(pivot_cols)}")
    
    # Check for inconsistency
    for row in m:
        if all(row[c] == 0 for c in range(num_vars)) and row[num_vars] == 1:
            print("[XL] System is inconsistent!")
            return None
    
    free_vars = [c for c in range(num_vars) if c not in set(pivot_cols)]
    print(f"[XL] Free variables: {len(free_vars)}")
    
    # Try to extract x[0..n-1] from the solution
    x_indices = [mono_to_idx.get((i,), -1) for i in range(n)]
    
    # Enumerate free variables (only the x[i] ones)
    # Find which x[i] are free vs pivoted
    from itertools import product as iproduct
    
    free_x = [(i, x_indices[i]) for i in range(n) if x_indices[i] in free_vars]
    pivoted_x = [(i, x_indices[i]) for i in range(n) if x_indices[i] in set(pivot_cols)]
    other_free = [c for c in free_vars if c not in set(xi for _, xi in free_x)]
    
    print(f"[XL] x-variables: {len(free_x)} free, {len(pivoted_x)} pivoted")
    print(f"[XL] Trying {2**len(free_x)} combinations for free x-bits...")
    
    for bits in iproduct([0, 1], repeat=len(free_x)):
        # Assign free x-vars
        sol = [0] * (num_vars + 1)
        for (i, idx), val in zip(free_x, bits):
            sol[idx] = val
        # Assign other free vars to 0
        
        # Back-substitute pivots
        consistent = True
        for row in reversed(m):
            pidx = -1
            for c in range(num_vars):
                if row[c]:
                    if c in set(pivot_cols):
                        pidx = c
                        break
                    break
            if pidx == -1:
                if row[num_vars]:
                    consistent = False
                    break
                continue
            
            # Compute sol[pidx]
            val = row[num_vars]
            for c in range(num_vars):
                if c != pidx and row[c]:
                    val ^= sol[c]
            sol[pidx] = val
        
        if not consistent:
            continue
        
        x = [sol[x_indices[i]] if x_indices[i] >= 0 else 0 for i in range(n)]
        
        if not any(x):
            continue
        
        got = eval_public(bitrows, x)
        if got == target:
            print(f"[XL] Found solution!")
            return x
    
    print("[XL] No solution found")
    return None


def solve_bruteforce_lowweight(public, max_weight=7):
    """低ハミング重み の x を総当たり（確率は低いが無コスト）。"""
    from itertools import combinations
    
    n = public['n']
    target = public['target']
    bitrows = public['A_bitrows']
    
    print(f"[BF] Low-weight brute force (weight 1..{max_weight})...")
    
    for weight in range(1, max_weight + 1):
        count = 0
        for positions in combinations(range(n), weight):
            x = [0] * n
            for p in positions:
                x[p] = 1
            got = eval_public(bitrows, x)
            if got == target:
                print(f"[BF] Found! weight={weight}, x={x}")
                return x
            count += 1
        print(f"[BF]   weight={weight}: {count} tried, no match")
    
    return None


def solve(public):
    """メインソルバー。複数の戦略を試す。"""
    n = public['n']
    target = public['target']
    
    print(f"[*] Solving MQ instance: n={n}, target_weight={sum(target)}")
    
    # 戦略1: 低重み総当たり（高速、成功率低い）
    result = solve_bruteforce_lowweight(public, max_weight=6)
    if result:
        return result
    
    # 戦略2: Gröbner 基底（主力手法）
    print("[*] Trying Groebner basis...")
    result = solve_groebner(public)
    if result:
        return result
    
    # 戦略3: XL（フォールバック）
    print("[*] Trying XL algorithm...")
    result = solve_xl(public, max_degree=5)
    if result:
        return result
    
    print("[!] All strategies failed")
    return None


# ─── PoW ──────────────────────────────────────────────────────────────────

def solve_pow(prefix, target_hex):
    """SHA256 PoW を総当たりで解く。"""
    print(f"[PoW] Mining: sha256('{prefix}' + nonce) starts with '{target_hex}'")
    i = 0
    while True:
        nonce = str(i)
        h = hashlib.sha256((prefix + nonce).encode()).hexdigest()
        if h.startswith(target_hex):
            print(f"[PoW] Found: nonce={nonce}")
            return nonce
        i += 1
        if i % 500000 == 0:
            print(f"[PoW] Tried {i}...")


# ─── ネットワーク ──────────────────────────────────────────────────────────

def recvuntil(sock, delim):
    data = b""
    while not data.endswith(delim if isinstance(delim, bytes) else delim.encode()):
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
    
    # Read until prompt
    banner = recvuntil(sock, "pow nonce> ")
    print(banner)
    
    # Solve PoW
    m = re.search(r"sha256\('([^']+)' \+ nonce\) starts with (\S+)", banner)
    if m:
        prefix, target_hex = m.group(1), m.group(2)
        nonce = solve_pow(prefix, target_hex)
        sock.sendall((nonce + "\n").encode())
        resp = recvuntil(sock, "\n")
        print(resp)
    
    # Read public instance
    data = recvuntil(sock, "signature> ")
    print(data[:200], "...")
    
    m = re.search(r'(\{"n":.+\})', data, re.DOTALL)
    if not m:
        print("[!] Could not parse public instance")
        return
    
    public = json.loads(m.group(1))
    print(f"[*] Got instance: n={public['n']}")
    
    # Solve
    result = solve(public)
    
    if result is None:
        print("[!] No solution found")
        sock.close()
        return
    
    sig_json = json.dumps({"signature": result}, separators=(',', ':'))
    print(f"[*] Sending: {sig_json[:80]}...")
    sock.sendall((sig_json + "\n").encode())
    
    response = sock.recv(4096).decode(errors="replace")
    print("[*] Response:", response)
    sock.close()


def local_test():
    """ローカルテスト: JSON を stdin から読む。"""
    print("[*] Local test mode -- paste public JSON:")
    line = sys.stdin.readline().strip()
    
    if not line:
        # サンプルデータで動作テスト
        print("[*] No input, generating tiny n=4 test case...")
        n = 4
        # f_i(x) = x[i]  (対角のみ)
        bitrows = []
        for i in range(n):
            row = ['0'] * (n * n)
            row[i * n + i] = '1'
            bitrows.append(''.join(row))
        target = [1, 1, 0, 1]
        public = {"n": n, "d": 2, "target": target, "A_bitrows": bitrows}
    else:
        public = json.loads(line)
    
    result = solve(public)
    
    if result:
        got = eval_public(public['A_bitrows'], result)
        print(f"[*] Solution: {result}")
        print(f"[*] Verify:   got={got}")
        print(f"[*]         target={public['target']}")
        print(f"[*] Correct: {got == public['target']}")
    else:
        print("[!] No solution found")


# ─── エントリポイント ──────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) == 3:
        interact(sys.argv[1], int(sys.argv[2]))
    else:
        local_test()