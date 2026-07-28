"""Depth-limited introsort matching the exact tie-breaking behaviour used
by the reference mania beatmap loader for its hitobject ordering step.

This is deliberately an *unstable* sort (median-of-3 quicksort, falling
back to heapsort past a recursion-depth limit) rather than Python's
built-in stable sort. For hitobjects that compare equal under the sort
key (e.g. two notes in different columns landing on the same rounded
millisecond -- a chord), which algorithm you use changes their relative
order, and that order feeds into per-column history construction
downstream. A stable sort silently produces a different-but-plausible
chord ordering, which is exactly the kind of divergence that's invisible
until compared bit-for-bit against a known-correct reference.

Same algorithm shape as the well-known "introsort" (median-of-3 quicksort
capped by a depth limit, falling back to heapsort) that has shipped in
several mainstream standard libraries -- written from scratch here, not
adapted from any specific implementation.
"""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")

_DEPTH_LIMIT = 32


def unstable_sort(items: list[T], compare: Callable[[T, T], int]) -> None:
    """In-place unstable sort, matching the reference client's tie-breaking."""
    n = len(items)
    if n == 0:
        return
    _quicksort(items, 0, n - 1, compare, _DEPTH_LIMIT)


def _swap(items: list[T], i: int, j: int) -> None:
    if i != j:
        items[i], items[j] = items[j], items[i]


def _swap_if_greater(items: list[T], compare: Callable[[T, T], int], a: int, b: int) -> None:
    if a != b and compare(items[a], items[b]) > 0:
        _swap(items, a, b)


def _quicksort(items: list[T], left: int, right: int, compare: Callable[[T, T], int], depth_limit: int) -> None:
    while left < right:
        if depth_limit == 0:
            _heapsort(items, left, right, compare)
            return

        i, j = left, right
        middle = i + ((j - i) >> 1)

        # Median-of-three pivot selection, sorting low/mid/high in place.
        _swap_if_greater(items, compare, i, middle)
        _swap_if_greater(items, compare, i, j)
        _swap_if_greater(items, compare, middle, j)

        pivot = items[middle]

        while True:
            while compare(items[i], pivot) < 0:
                i += 1
            while compare(pivot, items[j]) < 0:
                j -= 1
            if i > j:
                break
            if i < j:
                _swap(items, i, j)
            i += 1
            j -= 1
            if i > j:
                break

        depth_limit -= 1

        if j - left <= right - i:
            if left < j:
                _quicksort(items, left, j, compare, depth_limit)
            left = i
        else:
            if i < right:
                _quicksort(items, i, right, compare, depth_limit)
            right = j


def _heapsort(items: list[T], lo: int, hi: int, compare: Callable[[T, T], int]) -> None:
    n = hi - lo + 1

    for i in range(n // 2, 0, -1):
        _down_heap(items, i, n, lo, compare)

    for i in range(n, 1, -1):
        _swap(items, lo, lo + i - 1)
        _down_heap(items, 1, i - 1, lo, compare)


def _down_heap(items: list[T], i: int, n: int, lo: int, compare: Callable[[T, T], int]) -> None:
    d = items[lo + i - 1]

    while i <= n // 2:
        child = 2 * i
        if child < n and compare(items[lo + child - 1], items[lo + child]) < 0:
            child += 1
        if not (compare(d, items[lo + child - 1]) < 0):
            break
        items[lo + i - 1] = items[lo + child - 1]
        i = child

    items[lo + i - 1] = d
