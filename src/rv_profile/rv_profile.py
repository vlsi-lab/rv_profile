#!/bin/python
"""Cycle-accurate RISC-V function profiler.

The trace processor is driven event-by-event. For each fired clock we receive
(pc, instr, mcycle); the kind of the *previous* instruction tells us what
control-flow transition just landed us at the current pc. This avoids the
buffer-and-look-ahead state machine the previous implementation needed and
naturally distinguishes calls (rd in {ra, t0}) from unconditional jumps and
tail calls (rd == x0).
"""

import bisect
import os
import subprocess

from rv_profile.CallStack import CallStack
from rv_profile.decoder import classify, CALL, RET, JUMP, BRANCH

DEBUG = False


def ranges(binary_file):
    """Extract function symbols and their address ranges from an ELF using nm."""
    nm_bin = os.environ.get('RISCV_PREFIX', '') + 'nm'
    try:
        proc = subprocess.Popen([nm_bin, '-S', binary_file], stdout=subprocess.PIPE)
    except FileNotFoundError:
        print(f'"{nm_bin}" not found on system')
        exit(1)

    stdout, _ = proc.communicate()
    res = []
    for line in stdout.decode('UTF-8').split('\n'):
        cols = line.split()
        if len(cols) == 4 and cols[2] in ('T', 't'):
            name = cols[3]
            start = int(cols[0], 16)
            # Highest legal PC inside the function. Subtracting 2 covers the
            # case where the last instruction is a 16-bit compressed insn;
            # alignment guarantees no aliasing with the next function.
            end = start + int(cols[1], 16) - 2
            res.append([name, start, end])
    return res


class TraceProcessor:
    """Drives a CallStack from a stream of (pc, instr, mcycle) events.

    Maintains a single-instruction lookback so that the *kind* of the
    previous instruction tells the processor what control-flow transition
    landed it at the current pc. The class is intentionally side-effect free
    on construction so it can be exercised from tests with synthetic events.
    """

    def __init__(self, functions, callstack=None):
        self.cs = callstack or CallStack(verbose=False)
        sorted_funcs = sorted(functions, key=lambda f: f[1])
        self._sorted = sorted_funcs
        self._starts = [f[1] for f in sorted_funcs]
        self._prev_pc = None
        self._prev_instr = None
        self._prev_kind = None
        self._prev_func = None

    def func_at(self, addr):
        """Return the function name containing `addr`, or None."""
        i = bisect.bisect_right(self._starts, addr) - 1
        if i < 0:
            return None
        name, _lo, hi = self._sorted[i]
        if addr <= hi:
            return name
        return None

    def feed(self, addr, instr, mcycle):
        # Pipeline stalls re-fire the same (pc, instr) for several cycles;
        # skip duplicates so we don't synthesize spurious self-loops.
        if self._prev_pc == addr and self._prev_instr == instr:
            return

        cur_func = self.func_at(addr)

        if cur_func is None:
            # PC outside any nm-known function (trap vector, ROM stub, …).
            # We still classify the instruction so that a return-out-of-trap
            # can be picked up at the next known PC, but we don't touch the
            # call stack here.
            self._prev_pc = addr
            self._prev_instr = instr
            self._prev_kind = classify(instr)
            self._prev_func = None
            return

        prev_kind = self._prev_kind
        prev_func = self._prev_func

        if self._prev_pc is None:
            # First observed instruction: push the entry function.
            self.cs.call(cur_func, addr, mcycle)
        elif prev_kind == CALL:
            # Previous instruction wrote a link register; the current pc is
            # the callee entry point.
            self.cs.call(cur_func, addr, mcycle)
        elif prev_kind == RET:
            # Pop frames until cur_func is on top of the stack.
            self.cs.ret(cur_func, addr, mcycle)
        elif prev_kind in (JUMP, BRANCH):
            # rd=x0 jump or branch. If we crossed a function boundary it's
            # a tail call (or, in pathological code, a branch into another
            # function); replace the current frame with the new one.
            if cur_func != prev_func:
                self.cs.ret(cur_func, addr, mcycle)
        else:
            # Sequential execution. cur_func should equal prev_func; if it
            # doesn't we silently fell through into another function (alias
            # symbol, contiguous functions). Push it as an implicit call.
            if cur_func != prev_func:
                self.cs.call(cur_func, addr, mcycle)

        self._prev_pc = addr
        self._prev_instr = instr
        self._prev_kind = classify(instr)
        self._prev_func = cur_func


def riscv_profile_main(elf, fst, cfg, output, step):
    # Lazy-import so the rest of this module (TraceProcessor, classify, ranges)
    # remains usable in test environments that don't ship the wal-lang dep.
    from wal.core import Wal, WalEvalError

    functions = ranges(elf)
    processor = TraceProcessor(functions)

    wal = Wal()
    wal.load(fst)

    try:
        wal.eval_str(f'(eval-file {cfg})')
    except WalEvalError as e:
        print(f"\033[91m{e}\033[0m")
        exit(1)

    def count_function(seval, args):
        addr = seval.eval(args[0])
        instr = seval.eval(args[1])
        mcycle = seval.eval(args[2])
        if DEBUG:
            print(f"[????] addr: {hex(addr)} instr: {hex(instr)}, mcycle: {mcycle}")
        processor.feed(addr, instr, mcycle)

    wal.step(step)
    wal.register_operator("count-function", count_function)

    try:
        wal.eval_str('(whenever (fire) (count-function pc instr mcycle))', funcs=functions)
    except WalEvalError as e:
        print(e)
        exit(1)

    processor.cs.generate_flamegraph_data(output)
