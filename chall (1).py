password = input("Please enter the password: ")

def r(c, n):
    t = ord(c)
    if not (97 <= t <= 122 or 65 <= t <= 90): return c
    a = 65 if c.isupper() else 97
    return chr(((t - a + n) % 26) + a)

length = len(password)
rot1 = "".join([r(char, 6) for char in password[:length // 2]])
rot2 = "".join([r(char, -6) for char in password[length // 2:]])

print(rot1 + rot2)

if rot1 + rot2 != "FkxuJgey{mm_eio_wl4we3x_1n}":
    print("NOPE!")
    quit()

print("Access granted...")