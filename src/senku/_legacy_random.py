"""Bit-exact reimplementation of the reference client's legacy xorshift RNG
(`LegacyRandom`), used by osu!catch's HR position-jitter algorithm. Not a
general-purpose PRNG -- this exists purely to reproduce a specific legacy
algorithm's exact output sequence, seed-for-seed and draw-for-draw.
"""

from __future__ import annotations

_MASK32 = 0xFFFFFFFF


class LegacyRandom:
    def __init__(self, seed: int):
        self.x = seed & _MASK32
        self.y = 842502087
        self.z = 3579807591
        self.w = 273326509
        self._bit_buffer = 0
        self._bit_index = 32

    def next_uint(self) -> int:
        t = (self.x ^ ((self.x << 11) & _MASK32)) & _MASK32
        self.x = self.y
        self.y = self.z
        self.z = self.w
        self.w = (self.w ^ (self.w >> 19) ^ t ^ (t >> 8)) & _MASK32
        return self.w

    def next(self) -> int:
        return 0x7FFFFFFF & self.next_uint()

    def next_double(self) -> float:
        return 4.656612873077393e-10 * self.next()

    def next_range(self, lower: float, upper: float) -> int:
        """Matches both the `Next(int,int)` and `Next(double,double)` overloads --
        same formula, both return `int` (truncated toward zero, like C#'s cast)."""
        value = lower + self.next_double() * (upper - lower)
        return int(value)

    def next_bool(self) -> bool:
        if self._bit_index == 32:
            self._bit_buffer = self.next_uint()
            self._bit_index = 1
            return (self._bit_buffer & 1) == 1
        self._bit_index += 1
        self._bit_buffer >>= 1
        return (self._bit_buffer & 1) == 1
