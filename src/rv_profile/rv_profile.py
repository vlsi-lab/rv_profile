#!/bin/python
from wal.core import Wal, WalEvalError
import os
import subprocess
from rv_profile.CallStack import CallStack

RET=(0x8082, 0x8067)
MRET=(0x30200073,)
CALL=(0b1100111, 0b1101111)
BR=(0b1100011,)


BR_BUFF_LENGTH = 2
CALL_BUFF_LENGTH = 1
RET_BUFF_LENGTH = 1

DEBUG = False


def ranges(binary_file):
    '''This functions extracts the functions from elf files using "nm"'''
    res = []

    if 'RISCV_PREFIX' in os.environ:
        proc = subprocess.Popen( [ os.environ['RISCV_PREFIX'] + 'nm' , '-S', binary_file], stdout=subprocess.PIPE )
    else:
        # print('Please add the location of you RISC-V toolchain to the "RISCV_PREFIX" variable.')
        # print('Now trying to fall back to the regular "nm"..\n')
        try:
            proc = subprocess.Popen( [ 'nm' , '-S', binary_file], stdout=subprocess.PIPE )
        except:
            print('"nm" not found on system')
            exit(1)
        
    stdout, _ = proc.communicate()
    symbols = stdout.decode('UTF-8')

    for line in symbols.split('\n'):
        cols = line.split()
        if len(cols) == 4 and cols[2] in ['T', 't']:
            name = cols[3]
            start = int(cols[0], 16)
            end = start + int(cols[1], 16) - 2
            res.append([name, start, end])

    return res



def riscv_profile_main(elf, fst, cfg, output, step):
    BIN         = elf
    VCD         = fst
    CFG_FILE    = cfg
    FG_DATA     = output

    cs      = CallStack(verbose=False)
    functions = ranges(BIN)
    buffer  = []
    state = None # Can be BR, CALL, RET
    last = None

    wal     = Wal()
    wal.load(VCD)
    

    try:
        wal.eval_str(f'(eval-file {CFG_FILE})') # require config script to get concrete signal names
    except WalEvalError as e:
        # Print in red the error message
        print(f"\033[91m{e}\033[0m")
        exit(1)

    def count_function(seval, args):
        nonlocal buffer
        nonlocal state
        nonlocal last

        addr = seval.eval(args[0])
        instr = seval.eval(args[1])
        mcycle = seval.eval(args[2])

        print(f"[????] addr: {hex(addr)} instr: {hex(instr)}, mcycle: {mcycle}") if DEBUG else None

        if (last is not None and last[1] == instr and last[0] == addr):
            return

        found = False
        for function in functions:
            if addr >= function[1] and addr <= function[2]:
                found = True

        if (not found): 
            print("Ignoring instr") if DEBUG else None
            return

        assert (len(buffer) <= max(BR_BUFF_LENGTH, CALL_BUFF_LENGTH, RET_BUFF_LENGTH)+1)

        last = (addr, instr, mcycle)
        
        if (state == "BR"):
            """
            If the state is BR, then push until the buffer has length
            BR_BUFF_LENGTH, if at that point the pc has not changed then we can
            assume that the branch was not taken and we can pop the buffer and
            add those instructions to the call stack.

            Else if, at some point the pc changes, then we can assume that the
            branch was taken and we can pop the buffer and ignore those
            instructions.
            """
            if (len(buffer) < BR_BUFF_LENGTH+1):
                print("[BR] Appending to buffer") if DEBUG else None
                buffer.append((addr, instr, mcycle))

            if (len(buffer) == BR_BUFF_LENGTH+1):
                print("[BR] Buffer full") if DEBUG else None
                """
                Check if addresses in the buffer are contiguous, if they are
                then the branch was not taken and we can pop the buffer and add
                the instructions to the call stack.
                """
                taken = False
                another_func = False
                br_addr, _, _ = buffer[0]
                for function in functions:
                    if br_addr >= function[1] and br_addr <= function[2]:
                        br_func = function[0]
                        break

                buffer = buffer[1:]

                last_addr = br_addr
                for i in range(len(buffer)):
                    addr, instr, mcycle = buffer[i]
                    # print(last_addr, addr)
                    if (addr != last_addr+4 and addr != last_addr+2):
                        # Check if another function is called instead
                        for function in functions:
                            if addr >= function[1] and addr <= function[2]:
                                if (function[0] != br_func):
                                    another_func = True
                                break
                        
                        if (another_func):
                            print("[BR] Another function called") if DEBUG else None
                            break

                        taken = True
                        break
                    last_addr = addr

                
                if (taken):
                    print(f"[BR] Branch taken: {taken}") if DEBUG else None
                
                if (another_func):
                    print("[BR] Branch is not a real branch, entered another function") if DEBUG else None

                    # Iterate the buffer until we meet a CALL/RET instruction
                    for i in range(len(buffer)):
                        addr, instr, mcycle = buffer[i]
                        opcode = instr & 0x7F

                        print(f"[BR] Checking for corner case: {hex(addr)}, {hex(instr)}") if DEBUG else None
                        if (instr in set(RET + MRET) or opcode in set(CALL)):
                            print("[BR] Stopping at corner case") if DEBUG else None
                            buffer = buffer[i:]
                            break
                    
                    # Replay as a RET
                    state = "RET"

                    taken = None

                
                if (taken is not None):
                    if (not taken):
                        """
                        If the branch was not taken, then for each instruction, until
                        we meet a branch instruction/ret/call instruction, we can add
                        the instructions to the call stack.
                        """
                        for i in range(len(buffer)-1):
                            addr, instr, mcycle = buffer[i]

                            # Check if it is a corner-case, stop looping
                            if (instr in set(BR+ CALL+ RET+ MRET)):
                                print("[BR] Stopping at corner case") if DEBUG else None
                                buffer = buffer[i:]
                                break
                            else: # Add to call stack
                                print(f"[BR] Adding to call stack: {hex(addr)}") if DEBUG else None
                                for function in functions:
                                    if addr >= function[1] and addr <= function[2]:
                                        cs.call(function[0], addr, mcycle)
                                        break

                        addr, instr, mcycle = buffer[-1]
                        buffer = []
                        state = None
                    else: # Ignore all instructions in the buffer except last
                        # The last one overrides addr, instr, mcycle
                        addr, instr, mcycle = buffer[-1]
                        buffer = [] # Empty the buffer
                        print(f"[BR] Ignoring instructions in buffer, except last: {hex(addr)}") if DEBUG else None
                    
                    state = None
        if (state == "CALL"):
            """
            If the state is CALL, then push until the buffer has length
            CALL_BUFF_LENGTH, the PC will change at some point, which will be
            corresponding to the delay slot of the call instruction.

            When the buffer is full, we can pop the buffer ignoring all the
            instructions with PC continous to the call instruction, and add the
            rest to the call stack.
            """
            if (len(buffer) < CALL_BUFF_LENGTH+1):
                buffer.append((addr, instr, mcycle))
                print("[CALL] Appending to buffer, length: ", len(buffer)) if DEBUG else None
            
            if (len(buffer) == CALL_BUFF_LENGTH+1):
                print("[CALL] Buffer full") if DEBUG else None
                # Execute a first call to the oldest instruction in the buffer
                addr, instr, mcycle = buffer[0]
                print(f"[CALL] Adding to call stack: {hex(addr)}") if DEBUG else None
                for function in functions:
                    if addr >= function[1] and addr <= function[2]:
                        cs.call(function[0], addr, mcycle)
                        break
                
                buffer = buffer[1:]

                assert (len(buffer) == 1)
                
                addr, instr, mcycle = buffer[-1]
                buffer = []
                state = None
        if (state == "RET"):
            """Use the same algorithm as for CALL instructions."""
            if (len(buffer) < RET_BUFF_LENGTH+1):
                print("[RET] Appending to buffer") if DEBUG else None
                buffer.append((addr, instr, mcycle))
            
            if (len(buffer) == RET_BUFF_LENGTH+1):
                print("[RET] Buffer full") if DEBUG else None

                # Execute the RET
                addr, instr, mcycle = buffer[1]

                for function in functions:
                    if addr >= function[1] and addr <= function[2]:
                        cs.ret(function[0], addr, mcycle)
                        break

                buffer = buffer[2:]

                # assert (len(buffer) == 1)

                # Execute this last instruction
                if (len(buffer) > 0):
                    addr, instr, mcycle = buffer[-1]
                    buffer = []
                    state = None
                else:
                    state = None
                    return

        #Get the opcode from the instr
        opcode = instr & 0x7F

        if (state is not None):
            return

        if (instr in RET or instr in MRET):
            """A return instruction is detected, keep accepting new instructions
            until the buffer is full.
            """
            state = "RET"
            buffer.append((addr, instr, mcycle))
            print(f"[RET] addr: {hex(addr)} instr: {hex(instr)}, mcycle: {mcycle}, state: {state}") if DEBUG else None
            return
        elif (opcode in BR):
            """A branch instruction is detected, keep accepting new instructions
            until the buffer is full.
            """
            state = "BR"
            buffer.append((addr, instr, mcycle))
            print(f"[BR] addr: {hex(addr)} instr: {hex(instr)}, mcycle: {mcycle}, state: {state}") if DEBUG else None
            return
        elif (opcode in CALL):
            """A call instruction is detected, keep accepting new instructions"
            """
            state = "CALL"
            buffer.append((addr, instr, mcycle))
            print(f"[CALL] addr: {hex(addr)} instr: {hex(instr)}, mcycle: {mcycle}, state: {state}") if DEBUG else None
            return
        else:
            state = None

        # if (len(buffer) == 1):
        #     buffer.pop()

        #     # Return with the new func name
        #     for function in functions:
        #         if addr >= function[1] and addr <= function[2]:
        #             cs.ret(function[0], addr, mcycle)
        
        # if (instr in RET or instr in MRET):
        #     if (len(buffer) == 0):
        #         # buffer and wait for the next instruction
        #         buffer.append(addr)
        #         return

            for function in functions:
                if addr >= function[1] and addr <= function[2]:
                        print(f"[NONE] addr: {hex(addr)} instr: {hex(instr)}, mcycle: {mcycle}") if DEBUG else None
                        cs.call(function[0], addr, mcycle)
                        return

    wal.step(step)

    wal.register_operator("count-function", count_function)

    try:
        instructions_executed = wal.eval_str('(whenever (fire) (count-function pc instr mcycle))', funcs=functions)
    except WalEvalError as e:
        # Print in red the error message
        print(f"\033[91m{e}\033[0m")
        exit(1)

    cs.generate_flamegraph_data(FG_DATA)
