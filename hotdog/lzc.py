"""A compressor for the ramdisk layout the phone's own images ship in.

The old LZ4 frame is what a phone's kernel unpacks its ramdisk from, and
what its bootloader may look at. Every eight megabytes of the input goes
out as one block: the matches found in it are written as back references,
and what no match covers is written as it is. Whether the round trip
returns what went in is checked against the reader the images are parsed
with, before anything is booted with it.
"""

import struct
import sys

MAGIC = b"\x02\x21\x4c\x18"
BLOCK = 8 << 20


def compress_block(block):
    """One LZ4 block of matches and literals, greedily: a four-byte
    sequence seen before within reach stands for what followed it, and the
    last few bytes are always written as they are, as the format asks."""
    n = len(block)
    out = bytearray()
    seen = {}
    lit_start = 0
    i = 0
    # A match may not end in the last five bytes, and a match of these
    # lengths is worth more than the two bytes it costs to say.
    while i < n:
        best_at, best_len = -1, 0
        if i + 4 <= n - 5:
            seq = block[i : i + 4]
            cand = seen.get(seq)
            if cand is not None and i - cand <= 65535:
                length = 4
                limit = n - 5 - i
                while length < limit and block[cand + length] == block[i + length]:
                    length += 1
                if length >= 4:
                    best_at, best_len = i - cand, length
        if best_len:
            lit = i - lit_start
            ml = best_len - 4
            out.append((min(lit, 15) << 4) | min(ml, 15))
            if lit >= 15:
                rest = lit - 15
                while rest >= 255:
                    out.append(255)
                    rest -= 255
                out.append(rest)
            out.extend(block[lit_start:i])
            out.append(best_at & 0xFF)
            out.append((best_at >> 8) & 0xFF)
            if ml >= 15:
                rest = ml - 15
                while rest >= 255:
                    out.append(255)
                    rest -= 255
                out.append(rest)
            for k in range(i, i + best_len):
                if k + 4 <= n:
                    seen[block[k : k + 4]] = k
            i += best_len
            lit_start = i
        else:
            if i + 4 <= n:
                seen[block[i : i + 4]] = i
            i += 1
    lit = n - lit_start
    out.append((min(lit, 15) << 4) | 0)
    if lit >= 15:
        rest = lit - 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    out.extend(block[lit_start:n])
    return bytes(out)


def compress(data):
    """The whole ramdisk as the old frame: the mark, then a word saying how
    long each block came out, then the block. A block that found no matches
    is marked as written as it is."""
    out = bytearray(MAGIC)
    for at in range(0, len(data), BLOCK):
        chunk = data[at : at + BLOCK]
        packed = compress_block(chunk)
        if len(packed) < len(chunk):
            out.extend(struct.pack("<I", len(packed)))
            out.extend(packed)
        else:
            out.extend(struct.pack("<I", len(chunk) | 0x80000000))
            out.extend(chunk)
    return bytes(out)


def decompress_legacy(blob):
    """The reader the ramdisks are parsed with, which this compressor's
    output has to satisfy."""
    out = bytearray()
    pos = 4
    n = len(blob)
    while pos + 4 <= n:
        size = struct.unpack_from("<I", blob, pos)[0]
        pos += 4
        stored = size & 0x80000000
        size &= 0x7FFFFFFF
        if size == 0:
            break
        block = blob[pos : pos + size]
        pos += size
        if stored:
            out.extend(block)
            continue
        p, m = 0, len(block)
        while p < m:
            token = block[p]
            p += 1
            lit = token >> 4
            if lit == 15:
                while True:
                    b = block[p]
                    p += 1
                    lit += b
                    if b != 0xFF:
                        break
            out.extend(block[p : p + lit])
            p += lit
            if p >= m:
                break
            offset = block[p] | (block[p + 1] << 8)
            p += 2
            ml = (token & 0x0F) + 4
            if token & 0x0F == 15:
                while True:
                    b = block[p]
                    p += 1
                    ml += b
                    if b != 0xFF:
                        break
            start = len(out) - offset
            for k in range(ml):
                out.append(out[start + k])
    return bytes(out)


def selftest(data):
    packed = compress(data)
    back = decompress_legacy(packed)
    assert back == data, f"round trip failed: {len(data)} -> {len(packed)} -> {len(back)}"
    return len(packed)


if __name__ == "__main__":
    path = sys.argv[1]
    data = open(path, "rb").read()
    size = selftest(data)
    print(f"{path}: {len(data)} bytes -> {size} compressed ({size * 100 // max(len(data), 1)}%), round trip agrees")
