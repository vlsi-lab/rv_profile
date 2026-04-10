"""End-to-end tests for the TraceProcessor state machine.

These tests fabricate (pc, instr, mcycle) streams against a tiny synthetic
function table and check that the resulting CallStack matches what a sane
profiler would record. They run without WAL or any FST file.
"""

from rv_profile.CallStack import CallStack
from rv_profile.rv_profile import TraceProcessor


# Synthetic function table: name, start, end_inclusive (last legal PC).
FUNCS = [
    ["main", 0x100, 0x140],
    ["foo",  0x200, 0x240],
    ["bar",  0x300, 0x340],
    ["baz",  0x400, 0x440],
]

# Canonical encodings used throughout the tests.
NOP        = 0x00000013          # addi x0, x0, 0
JAL_RA     = 0x000000EF          # jal  ra, 0  (real call)
JAL_X0     = 0x0000006F          # jal  x0, 0  (j label / tail call)
RET_INSTR  = 0x00008067          # jalr x0, 0(ra) — `ret`
JALR_RA_A0 = 0x000500E7          # jalr ra, 0(a0) — function pointer call
JR_A0      = 0x00050067          # jalr x0, 0(a0) — indirect jump / tail call
BEQ        = 0x00000063          # beq  x0, x0, 0


def stack_names(p):
    return [name for name, _addr, _t in p.cs.stack]


def history_strings(p):
    return [s for s, _d in p.cs.call_stack_history]


def feed(p, events):
    for ev in events:
        p.feed(*ev)


# ----- basic call/return --------------------------------------------------------

def test_first_event_pushes_function():
    p = TraceProcessor(FUNCS)
    p.feed(0x100, NOP, 0)
    assert stack_names(p) == ["main"]


def test_simple_call_then_return():
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP,       0),    # main entry
        (0x104, JAL_RA,    1),    # main: call foo
        (0x200, NOP,       2),    # foo entry
        (0x204, RET_INSTR, 3),    # foo: ret
        (0x108, NOP,       4),    # back in main
    ])
    assert stack_names(p) == ["main"]
    assert any(s.endswith("main;foo") for s in history_strings(p))


def test_nested_calls():
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP,       0),
        (0x104, JAL_RA,    1),    # main → foo
        (0x200, NOP,       2),
        (0x204, JAL_RA,    3),    # foo → bar
        (0x300, NOP,       4),
        (0x304, RET_INSTR, 5),    # bar ret
        (0x208, NOP,       6),    # back in foo
        (0x20c, RET_INSTR, 7),    # foo ret
        (0x108, NOP,       8),    # back in main
    ])
    assert stack_names(p) == ["main"]
    history = history_strings(p)
    assert any("main;foo;bar" in s for s in history)
    assert any(s.endswith("main;foo") for s in history)


# ----- the bug-#1 cases ---------------------------------------------------------

def test_unconditional_jump_within_function_does_not_push():
    """Bug #1 used to treat `j label` as a call. It must not."""
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP,    0),
        (0x104, JAL_X0, 1),       # j label (rd = x0) inside main
        (0x120, NOP,    2),       # still inside main
    ])
    assert stack_names(p) == ["main"]
    # No spurious frame should have been recorded.
    assert all("main;main" not in s for s in history_strings(p))


def test_tail_call_via_jal_x0_replaces_frame():
    """A tail call must replace the caller's frame, not stack on top of it."""
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP,    0),
        (0x104, JAL_X0, 1),       # main: tail call to foo (rd = x0)
        (0x200, NOP,    2),       # foo entry
    ])
    # main has been replaced by foo — depth must still be 1.
    assert stack_names(p) == ["foo"]


def test_chained_tail_calls_keep_depth_constant():
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP,    0),
        (0x104, JAL_X0, 1),       # main → foo (tail)
        (0x200, NOP,    2),
        (0x204, JAL_X0, 3),       # foo  → bar (tail)
        (0x300, NOP,    4),
        (0x304, JAL_X0, 5),       # bar  → baz (tail)
        (0x400, NOP,    6),
    ])
    assert stack_names(p) == ["baz"]


def test_indirect_jump_to_other_function_is_tail_call():
    """`jalr x0, 0(a0)` to a different function = tail call via fn pointer."""
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP,    0),
        (0x104, JR_A0,  1),       # main: jr a0 (rs1 = a0, not a link reg)
        (0x200, NOP,    2),       # lands in foo
    ])
    assert stack_names(p) == ["foo"]


def test_function_pointer_call_pushes_frame():
    """`jalr ra, 0(a0)` is a real call and must push."""
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP,        0),
        (0x104, JALR_RA_A0, 1),
        (0x200, NOP,        2),
        (0x204, RET_INSTR,  3),
        (0x108, NOP,        4),
    ])
    assert stack_names(p) == ["main"]
    assert any(s.endswith("main;foo") for s in history_strings(p))


# ----- branches -----------------------------------------------------------------

def test_branch_does_not_push_frame():
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP, 0),
        (0x104, BEQ, 1),          # branch backwards
        (0x100, NOP, 2),          # taken — back to top of main
    ])
    assert stack_names(p) == ["main"]


def test_branch_not_taken():
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP, 0),
        (0x104, BEQ, 1),
        (0x108, NOP, 2),          # not taken — fall through
    ])
    assert stack_names(p) == ["main"]


# ----- pipeline-stall dedupe ----------------------------------------------------

def test_repeated_event_is_deduplicated():
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP, 0),
        (0x100, NOP, 1),          # same pc/instr — pipeline stall
        (0x100, NOP, 2),
        (0x104, NOP, 3),
    ])
    # Stack must not contain duplicate main entries; CallStack.call dedupes
    # but the more important property is that no spurious history was created.
    assert stack_names(p) == ["main"]
    assert all("main;main" not in s for s in history_strings(p))


# ----- function-range lookup ----------------------------------------------------

def test_func_at_lookup():
    p = TraceProcessor(FUNCS)
    assert p.func_at(0x100) == "main"
    assert p.func_at(0x140) == "main"
    assert p.func_at(0x141) is None
    assert p.func_at(0x200) == "foo"
    assert p.func_at(0x0FF) is None
    assert p.func_at(0x500) is None


# ----- mcycle attribution -------------------------------------------------------

def test_mcycle_durations_are_recorded():
    p = TraceProcessor(FUNCS)
    feed(p, [
        (0x100, NOP,       0),
        (0x104, JAL_RA,   10),    # main: call foo at cycle 10
        (0x200, NOP,      11),
        (0x204, RET_INSTR, 50),   # foo runs for ~40 cycles
        (0x108, NOP,      51),
    ])
    foo_entries = [d for s, d in p.cs.call_stack_history if s.endswith("foo")]
    assert foo_entries, "no foo frame recorded"
    # foo's frame should have a duration > 0 and <= the elapsed mcycles.
    assert all(d > 0 for d in foo_entries)
    assert all(d <= 51 for d in foo_entries)
