"""Put the identity the phone tells its own key hardware into the boot image.

The keymaster trusted application derives the key it wraps key blobs with
from what it is told about the phone at boot. A recovery is booted with a
much shorter list of those facts than the installed system is, so this
writes the facts the system has and the recovery lacks into the call line
the kernel hands the recovery's init, then re-seals the image the way the
phone checks it.

Usage: python3 patch_cmdline.py [--revert]
"""

import hashlib
import sys

IMG = "skyward-lmi-0.2.0-fixed.img"
OUT = "skyward-lmi-0.2.0-cmdline.img"
BACKUP = "skyward-lmi-0.2.0-before-cmdline.img"

CMDLINE_AT = 64
CMDLINE_BYTES = 512

# What the installed system tells its key hardware, in order of what it is
# most likely to matter for unwrapping a key: the phone's own identity, then
# whether the key hardware is in use at all.
WANTED = [
    "androidboot.keymaster=1",
    "androidboot.serialno=3c64ac03",
    "androidboot.hwversion=3.9.0",
    "androidboot.cpuid=0xdf955842",
    "androidboot.cert=M2001J11C",
]

# Said twice and never agreed on, so neither is worth the room.
DROP = {"buildvariant=user", "buildvariant=eng"}


def seal(image: bytearray, expect_as_it_stands: bool) -> None:
    """Recompute the hash the phone checks the image against.

    The hash of the signed part sits in the metadata a fixed way in, after
    the header, the descriptor header and the partition name. Before the
    image is changed the hash there has to agree with the image, or what is
    being changed is not the image this was measured against.
    """
    footer = image[-64:]
    assert footer[:4] == b"AVBf", "the image does not end with the expected footer"
    signed = int.from_bytes(footer[12:20], "big")
    vbmeta_at = int.from_bytes(footer[20:28], "big")
    digest_at = vbmeta_at + 396
    computed = hashlib.sha256(bytes(image[:signed])).digest()
    if expect_as_it_stands:
        assert bytes(image[digest_at : digest_at + 32]) == computed, "the image does not check out as it stands"
    else:
        image[digest_at : digest_at + 32] = computed


def main() -> int:
    image = bytearray(open(IMG, "rb").read())
    raw = bytes(image[CMDLINE_AT : CMDLINE_AT + CMDLINE_BYTES]).split(b"\x00")[0].decode()
    print(f"before ({len(raw)}): {raw}")

    kept = [a for a in raw.split() if a not in DROP]
    said = " ".join(kept)
    added = [a for a in WANTED if a.split("=")[0] not in {k.split("=")[0] for k in kept}]
    after = " ".join(kept + added)
    if len(after) >= CMDLINE_BYTES:
        print(f"too long: {len(after)} bytes do not fit in {CMDLINE_BYTES - 1}")
        return 1
    print(f"adding ({len(' '.join(added))}): {' '.join(added)}")
    print(f"after ({len(after)}): {after}")

    open(BACKUP, "wb").write(bytes(image))
    seal(image, expect_as_it_stands=True)
    image[CMDLINE_AT : CMDLINE_AT + CMDLINE_BYTES] = after.encode() + b"\x00" * (CMDLINE_BYTES - len(after))
    seal(image, expect_as_it_stands=False)
    open(OUT, "wb").write(bytes(image))

    check = bytearray(open(OUT, "rb").read())
    sealed = hashlib.sha256(bytes(check[: int.from_bytes(check[-64:][12:20], "big")])).digest()
    footer = check[-64:]
    at = int.from_bytes(footer[20:28], "big") + 396
    print(f"wrote {OUT} {len(check)} bytes; hash agrees: {sealed == bytes(check[at:at + 32])}")
    print(f"kept a copy of the image as it was in {BACKUP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
