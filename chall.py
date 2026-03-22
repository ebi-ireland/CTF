#!/usr/bin/env python3
import hashlib
import json
import secrets
import sys
import time

from sage.all import (
    GF,
    ZZ,
    PolynomialRing,
    block_matrix,
    companion_matrix,
    matrix,
    random_matrix,
    vector,
)

with open("flag.txt", "r", encoding="utf-8") as f:
    FLAG = f.read().strip()

POW_HEX = 5
POW_TIMEOUT = 90
N_PARAM = 26
D_PARAM = 10
POW_READ_MAX = 512
SIG_READ_MAX = 4096

def rand_inv_mat(F2, n):
    while True:
        m = random_matrix(F2, n, n)
        if m.is_invertible():
            return m


def linpoly_to_matrix(F2, Fext, n, coeffs):
    basis = [Fext.gen() ** i for i in range(n)]
    cols = []
    for b in basis:
        y = Fext.zero()
        for i, c in enumerate(coeffs):
            y += c * (b ** (2 ** i))
        cols.append(vector(F2, y._vector_()))
    return matrix(F2, n, n, lambda r, c: cols[c][r])


def build_public_matrix(n, d):
    F2 = GF(2)
    Rz = PolynomialRing(F2, "z")
    f = Rz.irreducible_element(n)
    Fext = GF(2 ** n, name="a", modulus=f)

    S_mat = rand_inv_mat(F2, n)
    T_mat = rand_inv_mat(F2, n)
    L1 = rand_inv_mat(F2, n)

    while True:
        coeffs = [Fext.random_element() for _ in range(d)] + [Fext.one()]
        L2 = linpoly_to_matrix(F2, Fext, n, coeffs)
        if L2.is_invertible():
            break

    comp = companion_matrix(f).transpose()
    M = block_matrix(F2, 1, n, [comp ** i for i in range(n)])
    return T_mat * M * L1.tensor_product(L2 * L1) * S_mat.tensor_product(S_mat)


def matrix_to_bitrows(A):
    return ["".join(str(int(v)) for v in A.row(i)) for i in range(A.nrows())]


def eval_public_from_A(A, x_bits):
    n = A.nrows()
    out = []
    for i in range(n):
        row = A.row(i)
        v = 0
        idx = 0
        for j in range(n):
            for k in range(n):
                if int(row[idx]) & int(x_bits[j]) & int(x_bits[k]):
                    v = 1 - v
                idx += 1
        out.append(v)
    return out


def generate_instance(n, d):
    A = build_public_matrix(n=n, d=d)

    while True:
        secret_sig = [int(ZZ.random_element(2)) for _ in range(n)]
        if not any(secret_sig):
            continue
        target = [int(v) for v in eval_public_from_A(A, secret_sig)]
        if any(target):
            break

    return {
        "n": int(n),
        "d": int(d),
        "target": target,
        "A_bitrows": matrix_to_bitrows(A),
    }


def do_pow():
    if POW_HEX <= 0:
        return True

    prefix = secrets.token_hex(8)
    target = "0" * POW_HEX
    print("== Proof of Work ==")
    print("(Mine BTC for me pls)")
    print(f"Find nonce so sha256('{prefix}' + nonce) starts with {target}")
    print(f"Time limit: {POW_TIMEOUT}s")
    print("pow nonce> ", end="", flush=True)

    started = time.time()
    try:
        nonce = read_limited_line(POW_READ_MAX).strip()
    except ValueError:
        print("pow input too long")
        return False
    except EOFError:
        return False

    if time.time() - started > POW_TIMEOUT:
        print("pow timeout")
        return False
    if len(nonce) > 256:
        print("pow nonce too long")
        return False

    digest = hashlib.sha256((prefix + nonce).encode()).hexdigest()
    if not digest.startswith(target):
        print("bad pow")
        return False

    print("pow ok")
    return True


def read_limited_line(max_bytes):
    raw = sys.stdin.buffer.readline(max_bytes + 2)
    if raw == b"":
        raise EOFError
    if not raw.endswith(b"\n") and len(raw) > max_bytes:
        while raw and not raw.endswith(b"\n"):
            raw = sys.stdin.buffer.readline(4096)
        raise ValueError("input too long")
    line = raw.rstrip(b"\r\n")
    if len(line) > max_bytes:
        raise ValueError("input too long")
    return line.decode("utf-8", "strict")


def parse_signature(line, n):
    s = line.strip()
    if not s:
        raise ValueError("empty input")

    try:
        obj = json.loads(s)
    except json.JSONDecodeError as exc:
        raise ValueError(f"bad format: {exc.msg}") from exc

    if not isinstance(obj, dict) or "signature" not in obj:
        raise ValueError('signature must be JSON object: {"signature":[...]}')

    sig = obj.get("signature")
    if not isinstance(sig, list):
        raise ValueError('field "signature" must be a JSON list')
    if len(sig) != n:
        raise ValueError(f"expected {n} bits")

    out = []
    for v in sig:
        iv = int(v)
        if iv not in (0, 1):
            raise ValueError("bits must be 0/1")
        out.append(iv)
    return out


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
                if row[idx] == "1" and sj and sig[k]:
                    acc ^= 1
                idx += 1
        out.append(acc)
    return out


def main():
    print("Quantum Collapse")
    print()

    if not do_pow():
        return

    try:
        public = generate_instance(N_PARAM, D_PARAM)
    except Exception:
        print("internal error")
        return

    n = int(public["n"])
    target = [int(x) & 1 for x in public["target"]]
    bitrows = public["A_bitrows"]

    print()
    print(json.dumps(public, separators=(",", ":")))
    print(f"Send {n} bits as one line.")
    print('Format: {"signature":[...]}')
    print("signature> ", end="", flush=True)

    try:
        line = read_limited_line(SIG_READ_MAX)
        sig = parse_signature(line, n)
    except EOFError:
        return
    except ValueError as exc:
        print(f"invalid input: {exc}")
        return

    got = eval_public(bitrows, sig)
    if got == target:
        print("valid signature")
        print(FLAG)
    else:
        print("invalid signature")


if __name__ == "__main__":
    main()
py


# & C:/Users/user/AppData/Local/Python/pythoncore-3.14-64/python.exe C:/Users/user/OneDrive/Desktop/CTF/chall.py