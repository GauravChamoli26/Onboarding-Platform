"""
Shared column types and identifier generation.

WHAT THIS MODULE DOES
    Provides `uuid7()`, the primary key generator used by every entity.

WHY UUID VERSION 7 AND NOT VERSION 4
    UUIDv4 is random, so consecutive inserts land in random positions in the
    primary key B-tree. That fragments the index and hurts write throughput as
    tables grow.

    UUIDv7 puts a millisecond timestamp in the leading 48 bits, so newly
    generated IDs sort after older ones. Inserts append to the right-hand edge
    of the index, which is the same access pattern as a sequential integer,
    while keeping the non-guessability that matters for IDs appearing in URLs
    (SDD §1.4, threat #1 — an enumerable identifier makes IDOR trivial).

    It also makes `ORDER BY id` a rough creation-time ordering, which is
    genuinely useful in audit and event tables.

WHY IMPLEMENTED HERE RATHER THAN IMPORTED
    UUIDv7 reached the Python standard library after 3.12, and the third-party
    packages that provide it are thin wrappers around this same ~15 lines.
    Implementing it directly avoids a dependency whose only job is a function we
    can read in full. Layout follows RFC 9562 §5.7.
"""

import os
import time
from uuid import UUID


def uuid7() -> UUID:
    """
    Generate a time-ordered UUID version 7.

    Bit layout (128 bits total, per RFC 9562):
        48 bits  Unix timestamp in milliseconds
         4 bits  version marker, always 0b0111 (7)
        12 bits  random
         2 bits  variant marker, always 0b10
        62 bits  random

    The 74 random bits make collisions within the same millisecond
    negligible, and make IDs unguessable from an adjacent one.

    Returns:
        UUID: a version 7 UUID, sortable by creation time.
    """
    # --- 48-bit millisecond timestamp ---------------------------------------
    timestamp_ms = int(time.time() * 1000)

    # --- 74 bits of randomness, taken as 10 bytes then trimmed --------------
    # os.urandom draws from the OS CSPRNG.
    random_bytes = os.urandom(10)
    random_int = int.from_bytes(random_bytes, byteorder="big")

    # --- Assemble ------------------------------------------------------------
    # Shift the timestamp into the top 48 bits, then layer in the version
    # marker, the variant marker, and the random material.
    value = timestamp_ms << 80  # timestamp occupies bits 127..80
    value |= 0x7 << 76  # version 7 in bits 79..76
    value |= (random_int >> 62) & 0xFFF  # 12 random bits, 75..64
    value |= 0b10 << 62  # variant marker, bits 63..62
    value |= random_int & 0x3FFFFFFFFFFFFFFF  # 62 random bits, 61..0

    return UUID(int=value)
