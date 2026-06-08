"""Tests del iterador de bloques TLE."""

from __future__ import annotations

import pytest

from orbital_sentinel.catalog.normalizers import iter_tle_blocks
from orbital_sentinel.core.errors import NormalizationError

L1_ISS = "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927"
L2_ISS = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"
NAME_ISS = "ISS (ZARYA)"

L1_TEST = "1 99999U 24001A   24001.00000000  .00000000  00000-0  00000-0 0  9999"
L2_TEST = "2 99999   0.0000   0.0000 0000000   0.0000   0.0000  1.00000000    19"
NAME_TEST = "TEST-99999"


def _blocks(text: str) -> list[tuple[int, str]]:
    return list(iter_tle_blocks(text))


def test_single_two_line_block() -> None:
    blocks = _blocks(f"{L1_ISS}\n{L2_ISS}\n")
    assert len(blocks) == 1
    idx, block = blocks[0]
    assert idx == 0
    assert block == f"{L1_ISS}\n{L2_ISS}"


def test_single_three_line_block() -> None:
    blocks = _blocks(f"{NAME_ISS}\n{L1_ISS}\n{L2_ISS}\n")
    assert len(blocks) == 1
    idx, block = blocks[0]
    assert idx == 0
    assert block == f"{NAME_ISS}\n{L1_ISS}\n{L2_ISS}"


def test_multiple_two_line_blocks() -> None:
    blocks = _blocks(f"{L1_ISS}\n{L2_ISS}\n{L1_TEST}\n{L2_TEST}\n")
    assert len(blocks) == 2
    assert [b[0] for b in blocks] == [0, 1]


def test_multiple_three_line_blocks() -> None:
    text = f"{NAME_ISS}\n{L1_ISS}\n{L2_ISS}\n{NAME_TEST}\n{L1_TEST}\n{L2_TEST}\n"
    blocks = _blocks(text)
    assert len(blocks) == 2
    assert NAME_ISS in blocks[0][1]
    assert NAME_TEST in blocks[1][1]


def test_mixed_with_and_without_name_lines() -> None:
    """Tercer caso: bloque con nombre seguido de bloque sin nombre."""
    text = f"{NAME_ISS}\n{L1_ISS}\n{L2_ISS}\n{L1_TEST}\n{L2_TEST}\n"
    blocks = _blocks(text)
    assert len(blocks) == 2
    assert NAME_ISS in blocks[0][1]
    assert NAME_TEST not in blocks[1][1]


def test_truncated_two_line_block_raises() -> None:
    with pytest.raises(NormalizationError):
        _blocks(f"{L1_ISS}\n")


def test_truncated_three_line_block_raises() -> None:
    with pytest.raises(NormalizationError):
        _blocks(f"{NAME_ISS}\n{L1_ISS}\n")


def test_blank_lines_are_skipped() -> None:
    text = f"\n{L1_ISS}\n{L2_ISS}\n\n\n{L1_TEST}\n{L2_TEST}\n\n"
    blocks = _blocks(text)
    assert len(blocks) == 2


def test_crlf_line_endings_supported() -> None:
    blocks = _blocks(f"{L1_ISS}\r\n{L2_ISS}\r\n")
    assert len(blocks) == 1


def test_empty_text_yields_nothing() -> None:
    assert _blocks("") == []
    assert _blocks("\n\n") == []
