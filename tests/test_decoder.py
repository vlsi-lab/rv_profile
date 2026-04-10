"""Unit tests for rv_profile.decoder.classify."""

from rv_profile.decoder import (
    BRANCH,
    CALL,
    JUMP,
    NORMAL,
    RET,
    classify,
)


def encode_jal(rd):
    """JAL with imm = 0; only rd matters for classification."""
    return ((rd & 0x1F) << 7) | 0x6F


def encode_jalr(rd, rs1):
    return ((rs1 & 0x1F) << 15) | ((rd & 0x1F) << 7) | 0x67


# ----- standard 32-bit encodings ------------------------------------------------

def test_jal_ra_is_call():
    assert classify(encode_jal(rd=1)) == CALL


def test_jal_t0_is_call():
    assert classify(encode_jal(rd=5)) == CALL


def test_jal_x0_is_jump():
    # `j label` — unconditional jump or tail call, not a call
    assert classify(encode_jal(rd=0)) == JUMP


def test_jal_other_rd_is_jump():
    assert classify(encode_jal(rd=10)) == JUMP


def test_canonical_ret():
    # `ret` == jalr x0, 0(ra)
    assert classify(0x00008067) == RET


def test_jalr_x0_t0_is_ret():
    # the t0-link return form
    assert classify(encode_jalr(rd=0, rs1=5)) == RET


def test_jalr_x0_other_rs1_is_jump():
    # indirect jump (switch table, function pointer tail call) — not a return
    assert classify(encode_jalr(rd=0, rs1=10)) == JUMP


def test_jalr_ra_is_call():
    # jalr ra, 0(a0) — function pointer call
    assert classify(encode_jalr(rd=1, rs1=10)) == CALL


def test_branch_opcode():
    # beq x0, x0, 0
    assert classify(0x00000063) == BRANCH


def test_mret():
    assert classify(0x30200073) == RET


def test_nop_is_normal():
    assert classify(0x00000013) == NORMAL


def test_addi_is_normal():
    # addi a0, a0, 1
    assert classify(0x00150513) == NORMAL


# ----- compressed encodings -----------------------------------------------------

def test_c_jr_ra_is_ret():
    # c.jr ra — compressed `ret`
    assert classify(0x8082) == RET


def test_c_jr_t0_is_ret():
    # c.jr t0 — also a return form
    assert classify(0x8282) == RET


def test_c_jr_a0_is_jump():
    # c.jr a0 — indirect jump, not a return
    assert classify(0x8502) == JUMP


def test_c_jalr_ra_is_call():
    # c.jalr ra — compressed call (rd implicit ra)
    assert classify(0x9082) == CALL


def test_c_j_is_jump():
    # c.j +0
    assert classify(0xA001) == JUMP


def test_c_beqz_is_branch():
    # c.beqz x8, +0
    assert classify(0xC001) == BRANCH


def test_c_add_is_normal():
    # c.add a0, a1 — same funct3/quadrant family as c.jalr but rs2 != 0
    # encoding: 1001 a0(01010) a1(01011) 10 = 1001_0101_0010_1110 = 0x952E
    assert classify(0x952E) == NORMAL


def test_c_mv_is_normal():
    # c.mv a0, a1 — funct4=1000, rs2 != 0 (same family as c.jr)
    # 1000 01010 01011 10 = 1000_0101_0010_1110 = 0x852E
    assert classify(0x852E) == NORMAL


# ----- robustness ---------------------------------------------------------------

def test_compressed_with_garbage_in_upper_bits():
    """Some cores expose `instr` as 32 bits with the next halfword in the
    upper bits. classify() must dispatch on the low halfword's quadrant bits
    and ignore the upper bits for compressed instructions."""
    assert classify(0xDEAD8082) == RET
    assert classify(0xCAFE9082) == CALL
