"""Drop the eXIf chunk from PNGs so viewers show the pixels as they are (XCUITest tags its shots orientation 8)."""
import struct
import sys

for path in sys.argv[1:]:
    data = open(path, "rb").read()
    out, pos = bytearray(data[:8]), 8
    while pos < len(data):
        n, = struct.unpack(">I", data[pos:pos + 4])
        if data[pos + 4:pos + 8] != b"eXIf":
            out += data[pos:pos + 12 + n]
        pos += 12 + n
    open(path, "wb").write(out)
