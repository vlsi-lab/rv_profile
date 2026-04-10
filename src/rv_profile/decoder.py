"""Instruction classifier for RISC-V control-flow tracking.

Each fetched instruction is classified into one of a small number of "kinds".
The trace processor uses the classification of the *previous* instruction to
decide what control-flow transition just landed it at the current PC, which
is what makes it possible to distinguish a real function call (jal/jalr with
rd in the link-register set) from an unconditional jump or a tail call
(jal/jalr with rd == x0).
"""

# Instruction kinds.
NORMAL = "NORMAL"
CALL = "CALL"
RET = "RET"
JUMP = "JUMP"      # unconditional jump that does not write a link register
BRANCH = "BRANCH"  # conditional branch

# RISC-V psABI link registers: ra (x1) and t0 (x5).
LINK_REGS = (1, 5)

MRET = 0x30200073


def classify(instr):
    """Classify a fetched RISC-V instruction.

    `instr` may be a 32-bit standard encoding or a 16-bit compressed encoding
    placed in the lower halfword of a 32-bit word. Some cores expose the
    instruction with the next halfword in the upper bits; that's fine, the
    quadrant bits in the low halfword still discriminate compressed vs.
    standard.
    """
    if instr == MRET:
        return RET

    low = instr & 0xFFFF
    if (low & 0x3) != 0x3:
        return _classify_compressed(low)

    return _classify_standard(instr)


def _classify_compressed(c):
    funct3 = (c >> 13) & 0x7
    quadrant = c & 0x3

    # Quadrant 1: c.j / c.jal / c.beqz / c.bnez
    if quadrant == 0b01:
        if funct3 == 0b101:        # c.j  (rd = x0)
            return JUMP
        if funct3 == 0b001:        # c.jal (rd = ra) — RV32 only
            return CALL
        if funct3 in (0b110, 0b111):  # c.beqz / c.bnez
            return BRANCH

    # Quadrant 2: c.jr / c.jalr live under funct3 == 100. The same funct3
    # also encodes c.mv / c.add / c.ebreak; we filter those out by requiring
    # rs2 == 0 and rs1 != 0.
    if quadrant == 0b10 and funct3 == 0b100:
        funct4 = (c >> 12) & 0xF
        rs1 = (c >> 7) & 0x1F
        rs2 = (c >> 2) & 0x1F
        if rs1 != 0 and rs2 == 0:
            if funct4 == 0b1000:   # c.jr  rs1 (rd implicit x0)
                return RET if rs1 in LINK_REGS else JUMP
            if funct4 == 0b1001:   # c.jalr rs1 (rd implicit ra)
                return CALL

    return NORMAL


def _classify_standard(instr):
    opcode = instr & 0x7F
    rd = (instr >> 7) & 0x1F
    rs1 = (instr >> 15) & 0x1F

    if opcode == 0b1101111:        # JAL
        return CALL if rd in LINK_REGS else JUMP

    if opcode == 0b1100111:        # JALR
        if rd in LINK_REGS:
            return CALL
        if rd == 0 and rs1 in LINK_REGS:
            return RET
        return JUMP                # rd=x0 with non-link rs1: indirect jump / tail call

    if opcode == 0b1100011:        # BRANCH (beq/bne/blt/bge/bltu/bgeu)
        return BRANCH

    return NORMAL
