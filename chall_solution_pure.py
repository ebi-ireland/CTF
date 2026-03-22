#!/usr/bin/env python3
"""
Quantum Collapse - CTF solution
================================
Problem: Find x ∈ F2^n s.t. target[i] = Σ_{j,k} A[i][j*n+k] * x[j] * x[k]  (mod 2)

Approach: XL (eXtended Linearization) over F2
  - Introduce new variables y_{j,k} = x[j] * x[k]  (degree-2 terms)
  - Build linear system:  Σ_{j,k} A[i][j*n+k] * y_{jk} = target[i]
  - Over F2, x[j]^2 = x[j], so y_{j,j} = x[j]  → これで変数を削減できる
  - Also y_{j,k} = y_{k,j}  → symmetric
  - Solve the linear system; then check consistency of solution (x[j]*x[k] == y_{j,k])

Key reduction:
  y_{j,j} = x[j]*x[j] = x[j]  (in F2)
  y_{j,k} = x[j]*x[k]  for j<k  (n*(n-1)/2 extra vars)

Total unknowns: n + n*(n-1)/2 = n*(n+1)/2
For n=26: 26*27/2 = 351 unknowns
Equations: n = 26

Since 26 << 351, we have an underdetermined system.
We need additional equations or to guess some bits.

Alternative approach: Guess low-weight x vectors
  The code guarantees x is not all-zero, but x could have Hamming weight 1,2,...
  Weight-1: 26 candidates → try all
  Weight-2: C(26,2)=325 candidates → try all
  Weight-3: C(26,3)=2600 candidates → try all
  etc.

We'll try low Hamming weights first, which is very fast.
If that fails, use a hybrid XL + guessing approach.
"""

import json
import socket
import hashlib
import itertools
import sys
import time
from itertools import combinations

# PoW solver
def solve_pow(prefix, target_prefix):
    """Brute force proof of work"""
    print(f"[PoW] Solving: sha256('{prefix}' + nonce) starts with '{target_prefix}'")
    i = 0
    while True:
        nonce = str(i)
        digest = hashlib.sha256((prefix + nonce).encode()).hexdigest()
        if digest.startswith(target_prefix):
            print(f"[PoW] Found nonce: {nonce} (digest: {digest[:16]}...)")
            return nonce
        i += 1
        if i % 100000 == 0:
            print(f"[PoW] Tried {i} nonces...")


def eval_public(bitrows, sig):
    """Evaluate the quadratic map at sig. Returns list of n bits."""
    n = len(sig)
    out = []
    for i in range(n):
        row = bitrows[i]
        acc = 0
        idx = 0
        for j in range(n):
            sj = sig[j]
            for k in range(n):
                if row[idx] == "1" and sj and sig[k]:
                    acc ^= 1
                idx += 1
        out.append(acc)
    return out


def try_low_weight(n, target, bitrows, max_weight=4):
    """
    Try all x with Hamming weight 1..max_weight.
    For n=26: weight 1 → 26, weight 2 → 325, weight 3 → 2600, weight 4 → 14950
    Total: ~18000 candidates — very fast.
    """
    print(f"[Solve] Trying low-weight solutions (weight 1..{max_weight})...")
    
    for weight in range(1, max_weight + 1):
        count = 0
        for positions in combinations(range(n), weight):
            x = [0] * n
            for p in positions:
                x[p] = 1
            
            got = eval_public(bitrows, x)
            if got == target:
                print(f"[Solve] Found! weight={weight}, positions={positions}")
                return x
            count += 1
        
        print(f"[Solve]   weight={weight}: tried {count} candidates, no match")
    
    return None


def build_linear_system_xl(n, bitrows, target):
    """
    XL approach: substitute y_{j,k} for x[j]*x[k].
    
    Variables:
      - x[0..n-1]  (diagonal terms, since y_{j,j} = x[j])
      - y_{j,k} for j < k  (off-diagonal quadratic terms)
    
    Index mapping:
      x[j] → index j  (for j in 0..n-1)
      y_{j,k} for j<k → index n + idx  where idx enumerates pairs
    
    Each equation i:
      Σ_j A[i][j*n+j] * x[j]   +   Σ_{j<k} (A[i][j*n+k] XOR A[i][k*n+j]) * y_{j,k}
      = target[i]   (all mod 2)
    
    Note: A[i][j*n+k] * y_{j,k} + A[i][k*n+j] * y_{k,j} = (A[i][j*n+k] XOR A[i][k*n+j]) * y_{j,k}
    because y_{j,k} = y_{k,j}.
    """
    # Map (j,k) with j<k to column index
    pair_to_idx = {}
    idx = 0
    for j in range(n):
        for k in range(j+1, n):
            pair_to_idx[(j,k)] = n + idx
            idx += 1
    
    num_vars = n + len(pair_to_idx)
    num_eqs = n
    
    print(f"[XL] Variables: {num_vars} (n={n} linear + {len(pair_to_idx)} quadratic)")
    print(f"[XL] Equations: {num_eqs}")
    print(f"[XL] System is underdetermined (need extra equations or guessing)")
    
    # Build matrix over F2 (as lists of ints)
    # Row i: coefficients for each variable, then RHS
    matrix = []
    
    for i in range(n):
        row = [0] * (num_vars + 1)  # +1 for RHS
        row[num_vars] = target[i]   # RHS
        
        bitrow = bitrows[i]
        
        for j in range(n):
            for k in range(n):
                aijk = 1 if bitrow[j*n+k] == '1' else 0
                if aijk == 0:
                    continue
                
                if j == k:
                    # x[j]^2 = x[j] in F2
                    row[j] ^= 1
                elif j < k:
                    row[pair_to_idx[(j,k)]] ^= 1
                else:  # j > k
                    row[pair_to_idx[(k,j)]] ^= 1
        
        matrix.append(row)
    
    return matrix, num_vars, pair_to_idx


def gauss_f2(matrix, num_vars):
    """
    Gaussian elimination over F2.
    Returns (rref_matrix, pivot_cols).
    """
    m = [row[:] for row in matrix]  # copy
    num_rows = len(m)
    num_cols = num_vars + 1  # includes RHS
    
    pivot_row = 0
    pivot_cols = []
    
    for col in range(num_vars):
        # Find pivot
        found = -1
        for r in range(pivot_row, num_rows):
            if m[r][col] == 1:
                found = r
                break
        
        if found == -1:
            continue  # free variable
        
        # Swap
        m[pivot_row], m[found] = m[found], m[pivot_row]
        pivot_cols.append(col)
        
        # Eliminate
        for r in range(num_rows):
            if r != pivot_row and m[r][col] == 1:
                for c in range(num_cols):
                    m[r][c] ^= m[pivot_row][c]
        
        pivot_row += 1
    
    return m, pivot_cols


def solve_xl_with_guessing(n, target, bitrows, max_guesses=16):
    """
    XL + partial guessing.
    Fix some free variables, solve the remaining system.
    Then verify the solution satisfies the original quadratic constraints.
    
    Strategy: fix x[0..g-1] to all combinations of 0/1, then solve rest.
    """
    matrix, num_vars, pair_to_idx = build_linear_system_xl(n, bitrows, target)
    
    # Reduce once
    rref, pivot_cols = gauss_f2(matrix, num_vars)
    free_vars = [c for c in range(num_vars) if c not in pivot_cols]
    
    print(f"[XL] After Gaussian elimination:")
    print(f"[XL]   Pivot cols: {len(pivot_cols)}")
    print(f"[XL]   Free variables: {len(free_vars)}")
    
    if len(free_vars) == 0:
        # Unique solution
        sol = extract_solution(rref, pivot_cols, num_vars, [])
        if sol is not None:
            x = sol[:n]
            got = eval_public(bitrows, x)
            if got == target:
                print("[XL] Unique solution verified!")
                return x
        return None
    
    # Guess free variables (try all combos up to max_guesses free vars)
    guess_vars = free_vars[:max_guesses]
    print(f"[XL] Guessing {len(guess_vars)} free variables ({2**len(guess_vars)} combinations)...")
    
    count = 0
    for bits in itertools.product([0, 1], repeat=len(guess_vars)):
        count += 1
        
        # Substitute guesses into RREF
        sol = extract_solution(rref, pivot_cols, num_vars, list(zip(guess_vars, bits)))
        if sol is None:
            continue
        
        x = sol[:n]
        
        # Verify original quadratic system
        got = eval_public(bitrows, x)
        if got == target:
            print(f"[XL] Found solution! (tried {count} guesses)")
            return x
        
        if count % 10000 == 0:
            print(f"[XL] Tried {count} combinations...")
    
    return None


def extract_solution(rref, pivot_cols, num_vars, free_assignments):
    """
    Given RREF and assignments for some free variables,
    back-substitute to get full solution.
    Returns solution vector or None if inconsistent.
    """
    sol = [0] * num_vars
    
    # Assign free variables
    for var_idx, val in free_assignments:
        sol[var_idx] = val
    
    # Back-substitute pivots (RREF, so each pivot row has exactly one pivot col)
    pivot_set = set(pivot_cols)
    
    for row in rref:
        # Find pivot of this row
        pivot = -1
        for c in range(num_vars):
            if row[c] == 1:
                if c in pivot_set:
                    pivot = c
                    break
                else:
                    break  # free variable → row is not a pivot row
        
        if pivot == -1:
            # Check if this is 0 = 1 (inconsistent)
            if row[num_vars] == 1:
                return None  # inconsistent
            continue
        
        # pivot col is determined by other variables
        rhs = row[num_vars]
        for c in range(num_vars):
            if c != pivot and row[c] == 1:
                rhs ^= sol[c]
        sol[pivot] = rhs
    
    return sol


def solve(public_data):
    """Main solver. Try multiple strategies."""
    n = public_data["n"]
    target = public_data["target"]
    bitrows = public_data["A_bitrows"]
    
    print(f"[*] n={n}, target weight={sum(target)}")
    
    # Strategy 1: Low Hamming weight brute force
    # P(weight ≤ 4) ≈ C(26,1..4) / 2^26 ≈ 18000/67M ≈ 0.027%
    # Not great odds but FREE to try
    result = try_low_weight(n, target, bitrows, max_weight=5)
    if result is not None:
        return result
    
    # Strategy 2: XL with guessing free variables
    # The linear system has ~325 free vars — we can't guess all.
    # But we can guess the n=26 x-variables and verify.
    print("[Solve] Trying XL + guessing x-bits directly...")
    result = solve_xl_guess_x(n, target, bitrows)
    if result is not None:
        return result
    
    print("[Solve] All strategies exhausted — trying random sampling")
    return random_sampling(n, target, bitrows)


def solve_xl_guess_x(n, target, bitrows):
    """
    Since there are only 26 x-variables, guess all 2^26 ~ 67M.
    This is a brute force but can be made fast with numpy or bitwise ops.
    
    Actually for n=26, full brute force is ~67M evaluations.
    Each evaluation is O(n^3) = O(26^3) ≈ 17000 ops → total ~10^12 → too slow.
    
    Better: use the structure. Each equation is a quadratic form Q_i(x).
    We can precompute for each x using Gray code (change one bit at a time).
    Then update takes O(n) per step instead of O(n^2).
    
    Let f_i(x) = x^T * A_i * x  where A_i is the i-th n×n submatrix.
    When we flip bit j: f_i(x XOR e_j) = f_i(x) XOR 2*x^T * A_i * e_j XOR (A_i)_{jj}
    Over F2: f_i(x XOR e_j) = f_i(x) XOR (A_i * x)[j]_doubled... 
    
    Actually: f(x + e_j) = f(x) + 2*col_j(A)^T * x + A_{jj}
    Over F2: = f(x) + A_{jj}  (since 2=0 in F2)
    Wait, that's not right. Let me reconsider.
    
    f(x) = sum_{k,l} A_{kl} x_k x_l
    f(x + e_j) = sum_{k,l} A_{kl} (x_k + [k==j])(x_l + [l==j])
               = f(x) + sum_l A_{jl} x_l + sum_k A_{kj} x_k + A_{jj}
               = f(x) + (row_j(A) + col_j(A)) . x + A_{jj}
    Over F2, this update is O(n) per bit flip, O(n) per equation → O(n^2) per step.
    Full scan: 2^n * O(n^2) → still too slow for n=26.
    
    Let's use a smarter approach: fix first k bits and solve the rest.
    """
    # For n=26, brute force is too slow.
    # Use meet-in-the-middle or other approach.
    # Here we use: fix the first 13 bits, for each prefix compute
    # the residual linear system in the last 13 bits.
    
    # f_i(x) = f_i(x_A, x_B) where x = (x_A, x_B), |x_A|=|x_B|=13
    # f_i(x_A, x_B) = Q_AA(x_A) + L_{AB}(x_A)*x_B + Q_BB(x_B)
    # where Q_AA is quadratic in x_A, Q_BB quadratic in x_B, L_{AB} is bilinear.
    # This gives: L_{AB}(x_A)*x_B = target_i XOR Q_AA(x_A) XOR Q_BB(x_B)
    # Still nonlinear in x_B.
    
    # Simplest: just brute force but fast using Python bitwise tricks
    # 2^26 with O(n) per step using Gray code and precomputed row sums
    
    print("[XL-x] Setting up Gray code brute force with O(n^2) per step...")
    print("[XL-x] This may take a while for n=26 (~67M steps)...")
    
    # Precompute A matrices as integers for fast XOR
    # A[i] is n×n matrix; we compute f_i(x) for all i simultaneously
    # x is stored as integer bitmask
    
    # For each equation i and each column j, precompute row[i*n + j..j+n-1]
    # This lets us compute the linear term update when bit j flips.
    
    # Represent each row of A as list of n integers (each is n bits as int)
    # A_int[i][j] = integer where bit k = A[i][j*n+k]
    
    n = n
    # Build A_int[i][j] = bitmask of row i, columns j*n .. (j+1)*n-1
    A_rows = []
    for i in range(n):
        row_i = []
        br = bitrows[i]
        for j in range(n):
            # bits j*n .. j*n+n-1
            chunk = int(br[j*n : j*n+n][::-1], 2)  # bit k = br[j*n+k]
            row_i.append(chunk)
        A_rows.append(row_i)
    
    # f_i(x) = sum_j x[j] * (A_rows[i][j] AND x)   (popcount mod 2)
    # = x^T A x
    
    def eval_all(x_int):
        """Evaluate all n equations at x given as integer bitmask."""
        result = 0
        for i in range(n):
            fi = 0
            tmp = x_int
            bit = 1
            for j in range(n):
                if tmp & 1:
                    fi ^= bin(A_rows[i][j] & x_int).count('1') & 1
                tmp >>= 1
                bit <<= 1
            if fi == target[i]:
                pass
            result |= (fi << i)
        return result
    
    target_int = 0
    for i, t in enumerate(target):
        target_int |= (t << i)
    
    # Brute force with early exit for small n (n<=20) or sampling for larger
    if n <= 20:
        print(f"[XL-x] Full brute force: 2^{n} = {2**n} candidates")
        for x_int in range(1, 2**n):
            if eval_all(x_int) == target_int:
                x = [(x_int >> j) & 1 for j in range(n)]
                print(f"[XL-x] Found! x_int={hex(x_int)}")
                return x
    else:
        print(f"[XL-x] n={n} too large for full brute force, skipping")
    
    return None


def random_sampling(n, target, bitrows, trials=100000):
    """Random sampling as last resort."""
    import random
    print(f"[Sample] Trying {trials} random x vectors...")
    for t in range(trials):
        x = [random.randint(0, 1) for _ in range(n)]
        if not any(x):
            continue
        got = eval_public(bitrows, x)
        if got == target:
            print(f"[Sample] Found at trial {t}!")
            return x
    return None


# ─── Network interaction ───────────────────────────────────────────────────

def recvuntil(sock, delim):
    data = b""
    while not data.endswith(delim):
        chunk = sock.recv(1)
        if not chunk:
            break
        data += chunk
    return data.decode(errors="replace")


def main():
    HOST = "localhost"
    PORT = 1337

    # For local testing, read from a local instance or parse from stdin
    # Adjust HOST/PORT as needed
    
    if len(sys.argv) > 2:
        HOST = sys.argv[1]
        PORT = int(sys.argv[2])
    
    print(f"[*] Connecting to {HOST}:{PORT}")
    
    try:
        sock = socket.socket()
        sock.settimeout(120)
        sock.connect((HOST, PORT))
    except ConnectionRefusedError:
        print("[!] Could not connect — running in local/test mode")
        test_local()
        return
    
    # Read banner
    banner = recvuntil(sock, b"> ")
    print(banner, end="")
    
    # Handle PoW
    if "sha256" in banner:
        # Parse: Find nonce so sha256('PREFIX' + nonce) starts with TARGET
        import re
        m = re.search(r"sha256\('([^']+)' \+ nonce\) starts with (\S+)", banner)
        if m:
            prefix, target_prefix = m.group(1), m.group(2)
            nonce = solve_pow(prefix, target_prefix)
            sock.sendall((nonce + "\n").encode())
            resp = recvuntil(sock, b"\n")
            print(resp)
        # Read next prompt
        data = recvuntil(sock, b"}")
        data += recvuntil(sock, b"> ")
    else:
        data = banner
    
    # Parse JSON public data
    import re
    m = re.search(r'(\{"n":.+\})', data, re.DOTALL)
    if not m:
        print("[!] Could not find JSON in response")
        print("Response:", data[:500])
        return
    
    public = json.loads(m.group(1))
    print(f"[*] Got public instance: n={public['n']}, d={public['d']}")
    
    # Solve
    result = solve(public)
    
    if result is None:
        print("[!] Failed to find solution")
        sock.close()
        return
    
    print(f"[*] Sending signature: {result}")
    sig_json = json.dumps({"signature": result}, separators=(',', ':'))
    sock.sendall((sig_json + "\n").encode())
    
    response = recvuntil(sock, b"\n")
    print("Response:", response)
    response2 = recvuntil(sock, b"\n")
    print("Response2:", response2)
    
    sock.close()


def test_local():
    """Test solver locally without network."""
    print("[*] Running local test...")
    
    # We need sage for generating test instances
    # Instead, let's test with manually crafted small instance
    # or read from stdin
    
    print("[*] Paste the JSON public data (one line), then press Enter:")
    try:
        line = input().strip()
        public = json.loads(line)
    except (json.JSONDecodeError, EOFError) as e:
        print(f"[!] Could not parse JSON: {e}")
        print("[*] Generating synthetic test...")
        # Small synthetic test
        n = 4
        # Simple identity-like A where A(x,x) = x
        bitrows = []
        for i in range(n):
            row = ['0'] * (n*n)
            row[i*n + i] = '1'  # diagonal
            bitrows.append(''.join(row))
        target = [1, 0, 1, 0]
        public = {"n": n, "d": 2, "target": target, "A_bitrows": bitrows}
    
    result = solve(public)
    if result:
        print(f"[*] Solution: {result}")
        got = eval_public(public["A_bitrows"], result)
        print(f"[*] Verification: {got}")
        print(f"[*] Target:       {public['target']}")
        print(f"[*] Correct: {got == public['target']}")
    else:
        print("[!] No solution found")


if __name__ == "__main__":
    main()