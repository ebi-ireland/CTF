#!/usr/bin/env python3
"""
Solver: Endless CTF
nc endless.zerodays.events 8100

仕組み:
  1. データをbase64デコード → 0x00/0x01 のビット列
  2. 160ビットになるよう先頭に0パディング
  3. 8ビットずつ → 20バイトのトークン
  4. トークンを送信 → 次のラウンドへ
  ※ ヒントで基数が変わることがある (base2, base4, base8 等) ので対応
"""

import socket
import base64
import re
import time

HOST = "endless.zerodays.events"
PORT = 8100
TIMEOUT = 10


def recv_until_token_prompt(sock):
    """'Token: ' が来るまで受信し続ける"""
    buf = b""
    while b"Token:" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("サーバー切断")
        buf += chunk
        time.sleep(0.05)
    return buf.decode(errors="replace")


def decode_base2(data_str):
    """
    base2 (A=0, B=1) エンコード:
      データ → base64デコード → 0x00/0x01のビット列
      → 160ビットにパディング → 20バイトのトークン
    """
    padded = data_str + '=' * (4 - len(data_str) % 4)
    raw = base64.b64decode(padded)

    bits = list(raw)
    target = 20 * 8  # 160 bits

    # 先頭にゼロパディング
    while len(bits) < target:
        bits = [0] + bits
    # 多い場合は末尾を切る
    bits = bits[-target:]

    result = bytearray()
    for i in range(0, target, 8):
        byte_val = 0
        for j in range(8):
            byte_val = (byte_val << 1) | bits[i + j]
        result.append(byte_val)
    return result.decode(errors="replace")


def decode_base4(data_str):
    """
    base4 (A=00, B=01, E=10, Q=11):
      各文字 → 2ビット → バイト列 → base64デコード → トークン
    """
    mapping = {'A': '00', 'B': '01', 'E': '10', 'Q': '11'}
    binary = ''.join(mapping.get(c, '00') for c in data_str)

    raw = bytearray()
    for i in range(0, len(binary) - len(binary) % 8, 8):
        raw.append(int(binary[i:i+8], 2))

    try:
        decoded = base64.b64decode(bytes(raw) + b'=' * (4 - len(raw) % 4))
        if len(decoded) == 20:
            return decoded.decode(errors="replace")
    except Exception:
        pass
    return None


def decode_base8(data_str):
    """
    base8 (A=000, B=001, C=010, D=011, E=100, F=101, G=110, H=111):
      各文字 → 3ビット → バイト列 → base64デコード → トークン
    """
    # よくある 8文字のマッピング
    chars = list(set(data_str))
    chars.sort()
    mapping = {c: format(i, '03b') for i, c in enumerate(chars[:8])}

    binary = ''.join(mapping.get(c, '000') for c in data_str)
    raw = bytearray()
    for i in range(0, len(binary) - len(binary) % 8, 8):
        raw.append(int(binary[i:i+8], 2))

    try:
        decoded = base64.b64decode(bytes(raw) + b'=' * (4 - len(raw) % 4))
        if len(decoded) == 20:
            return decoded.decode(errors="replace")
    except Exception:
        pass
    return None


def solve_round(hint, data_str):
    """ヒントに応じたデコードを試みる"""
    base_num = int(re.search(r'base\s*(\d+)', hint, re.I).group(1)) if re.search(r'base\s*(\d+)', hint, re.I) else 2

    print(f"  Hint: {hint.strip()}")
    print(f"  Base: {base_num}, Data length: {len(data_str)}")

    token = None

    if base_num == 2:
        token = decode_base2(data_str)
    elif base_num == 4:
        token = decode_base4(data_str)
    elif base_num == 8:
        token = decode_base8(data_str)
    else:
        # 汎用: 文字数=基数、各文字をビットに変換してbase64デコード
        unique_chars = sorted(set(data_str))
        bits_per_char = base_num.bit_length() - 1
        mapping = {c: format(i, f'0{bits_per_char}b') for i, c in enumerate(unique_chars)}
        binary = ''.join(mapping.get(c, '0' * bits_per_char) for c in data_str)
        raw = bytearray()
        for i in range(0, len(binary) - len(binary) % 8, 8):
            raw.append(int(binary[i:i+8], 2))
        try:
            decoded = base64.b64decode(bytes(raw) + b'=' * (4 - len(raw) % 4))
            if len(decoded) == 20:
                token = decoded.decode(errors="replace")
        except Exception:
            pass

    if token and len(token) == 20:
        return token

    # フォールバック: base2 を常に試す
    fallback = decode_base2(data_str)
    if fallback and len(fallback) == 20:
        return fallback

    raise ValueError(f"トークンをデコードできませんでした (base={base_num})")


def main():
    print(f"接続中: {HOST}:{PORT}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    sock.connect((HOST, PORT))
    print("接続成功！\n")

    flag_re = re.compile(r'[A-Za-z0-9_]+\{[^}]+\}')
    round_num = 0

    try:
        while True:
            buf = recv_until_token_prompt(sock)
            print(buf.rstrip())

            # フラグチェック
            flags = flag_re.findall(buf)
            if flags:
                print("\n" + "=" * 50)
                for f in flags:
                    print(f"FLAG: {f}")
                print("=" * 50)
                break

            # ラウンド情報をパース
            hint_match = re.search(r'Hint:\s*(.+)', buf)
            data_match = re.search(r'Data:\s*(\S+)', buf)

            if not hint_match or not data_match:
                print("[!] パースできませんでした:")
                print(buf)
                break

            hint = hint_match.group(1)
            data_str = data_match.group(1)
            round_num += 1
            print(f"\n[Round {round_num}]")

            try:
                token = solve_round(hint, data_str)
                print(f"  Token: {token}")
                sock.sendall((token + '\n').encode())
                time.sleep(0.3)
            except ValueError as e:
                print(f"[!] エラー: {e}")
                break

    except ConnectionError as e:
        print(f"[!] 接続エラー: {e}")
    except KeyboardInterrupt:
        print("\n中断")
    finally:
        # 残りのデータを受信してフラグを探す
        try:
            sock.settimeout(3)
            remaining = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                remaining += chunk
            if remaining:
                text = remaining.decode(errors="replace")
                print(text)
                flags = flag_re.findall(text)
                for f in flags:
                    print(f"\nFLAG: {f}")
        except Exception:
            pass
        sock.close()


if __name__ == '__main__':
    main()