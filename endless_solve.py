#!/usr/bin/env python3
import socket, base64, hashlib, re, time

HOST = "endless.zerodays.events"
PORT = 8100

def recv_until(sock, marker, timeout=30):
    buf = b""
    sock.settimeout(timeout)
    while marker.encode() not in buf:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("サーバー切断")
            buf += chunk
        except TimeoutError:
            if buf: break
            raise
        time.sleep(0.02)
    return buf.decode(errors="replace")

def recv_with_timeout(sock, timeout=5):
    """タイムアウトまで受信"""
    buf = b""
    sock.settimeout(timeout)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
            buf += chunk
    except TimeoutError:
        pass
    return buf.decode(errors="replace")

def find_base_auto(raw):
    min_base = max(max(raw) + 1, 2)
    for base in range(min_base, min_base + 500):
        if any(d >= base for d in raw): continue
        n = 0
        for d in raw: n = n * base + d
        try:
            token = n.to_bytes(20, byteorder='big')
            if all(32 <= b < 127 for b in token):
                return base, token.decode()
        except (OverflowError, ValueError): pass
    return None, None

def decode_normal(data_str, base_num):
    pad = (4 - len(data_str) % 4) % 4
    raw = base64.b64decode(data_str + '=' * pad)
    if base_num:
        n = 0
        for d in raw: n = n * base_num + d
        return n.to_bytes(20, byteorder='big').decode()
    else:
        found_base, token = find_base_auto(raw)
        if token:
            print(f"  (base={found_base} 自動検出)")
            return token
        raise ValueError("baseを自動検出できませんでした")

def send_and_wait(sock, token, timeout=8):
    """1つ送信して返答を待つ"""
    sock.sendall((token + '\n').encode())
    time.sleep(0.2)
    resp = recv_with_timeout(sock, timeout)
    return resp

def main():
    print(f"接続中: {HOST}:{PORT}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((HOST, PORT))
    print("接続成功！\n")

    flag_re = re.compile(r'ZeroDays\{[^}]+\}')
    round_num = 0
    hex_mode = False

    try:
        while True:
            buf = recv_until(sock, "Token")
            print(buf.rstrip())

            flags = flag_re.findall(buf)
            if flags:
                print("\n" + "=" * 50)
                for f in flags: print(f"FLAG: {f}")
                print("=" * 50)
                break

            if "raw bytes" in buf or "lowercase hex" in buf:
                hex_mode = True

            hint_match = re.search(r'Hint:\s*(.+)', buf)
            data_match = re.search(r'Data:\s*(\S+)', buf)
            if not data_match:
                print("[!] Dataなし\n", buf); break

            hint = hint_match.group(1) if hint_match else None
            data_str = data_match.group(1)
            hint_hash_m = re.search(r'md5\s+([0-9a-f]{32})', hint or '', re.I)
            hint_hash = hint_hash_m.group(1) if hint_hash_m else None
            round_num += 1
            print(f"\n[Round {round_num}]")

            if hex_mode:
                pad = (4 - len(data_str) % 4) % 4
                raw = base64.b64decode(data_str + '=' * pad)
                print(f"  raw: {raw.hex()}, len={len(raw)}, max={max(raw)}")
                print(f"  md5ヒント: {hint_hash}")

                # 送る候補: まずrawそのまま
                resp = send_and_wait(sock, raw.hex())
                print(f"  [raw] 返答: {repr(resp[:200])}")

                if flag_re.search(resp):
                    for f in flag_re.findall(resp): print(f"FLAG: {f}")
                    break
                if "complete" in resp.lower() or "round" in resp.lower():
                    print("  → 正解!")
                    continue
                # WrongまたはTokenプロンプトが来たら次の候補
                if "wrong" in resp.lower() or "Token" in resp:
                    print("  → 不正解、baseNデコードを試す")
                    # baseNデコードで試す
                    min_base = max(raw) + 1
                    found = False
                    for base in range(min_base, min_base + 2000):
                        if any(d >= base for d in raw): continue
                        n = 0
                        for d in raw: n = n * base + d
                        nb = (n.bit_length() + 7) // 8
                        for b in range(nb, nb+3):
                            try:
                                tok = n.to_bytes(b, 'big')
                                if hint_hash and hashlib.md5(tok).hexdigest() == hint_hash:
                                    print(f"  MD5一致! base={base} bytes={b}: {tok.hex()}")
                                    resp2 = send_and_wait(sock, tok.hex())
                                    print(f"  返答: {repr(resp2[:200])}")
                                    found = True
                                    break
                            except: pass
                        if found: break
                    if not found:
                        print("  [!] 全候補失敗 - rawを再送して続行")
                elif not resp:
                    print("  → 返答なし (正解の可能性あり、続行)")

            else:
                base_m = re.search(r'base\s*(\d+)', hint or '', re.I)
                base_num_val = int(base_m.group(1)) if base_m else 0
                print(f"  Base: {base_num_val or 'auto'}")
                token = decode_normal(data_str, base_num_val)
                print(f"  → 送信: {token}")
                sock.sendall((token + '\n').encode())
                time.sleep(0.3)

    except (ConnectionError, KeyboardInterrupt) as e:
        print(f"\n{e}")
    finally:
        try:
            sock.settimeout(5)
            remaining = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk: break
                remaining += chunk
            if remaining:
                text = remaining.decode(errors="replace")
                print(text)
                for f in flag_re.findall(text): print(f"\nFLAG: {f}")
        except: pass
        sock.close()

if __name__ == '__main__':
    main()