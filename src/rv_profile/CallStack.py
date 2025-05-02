import hashlib
import random

class CallStack:
    def __init__(self, verbose=False):
        self.stack = []  # Stack of (function name, address, start time)
        self.verbose = verbose
        self.call_stack_history = []  # To store the full call stack history

    def _generate_color(self, name):
        random.seed(int(hashlib.sha256(name.encode()).hexdigest(), 16) % 10**8)
        return (random.random(), random.random(), random.random())

    def call(self, func_name, addr, mcycle):
        if self.stack and self.stack[-1][0] == func_name:
            return
        
        self.stack.append((func_name, addr, mcycle))

    def ret(self, func_name, next_addr, mcycle):
        if self.stack:
            end_time = mcycle

            # Check if the func_name is not present in the stack, if so just pop
            # the first element
            if func_name not in [f[0] for f in self.stack] or self.stack[-1][0] == func_name:
                fn, _, start_time = self.stack.pop()
                call_stack = [f[0] for f in self.stack]

                duration = end_time - start_time

                if (duration < 0):
                    raise Exception(f"Negative duration: {duration} for function {fn}")

                call_stack += [fn]
                self.call_stack_history.append((";".join(call_stack), duration))

                # Issue a call to the function that was implicitly called
                self.call(func_name, next_addr, mcycle)
                print("[WARNING] Implict call detected") if self.verbose else None
            else:
                while self.stack and self.stack[-1][0] != func_name:
                    fn, _, start_time = self.stack.pop()

                    # Record the call stack and duration for flame graph data
                    call_stack = [f[0] for f in self.stack]

                    call_stack += [fn]

                    duration = end_time - start_time

                    if (duration < 0):
                        raise Exception(f"Negative duration: {duration} for function {fn}")

                    self.call_stack_history.append((";".join(call_stack), duration))

    def generate_flamegraph_data(self, file_name):
        self._postprocess_call_stack_history()

        with open(file_name, 'w') as f:
            for stack_str, duration in self.call_stack_history:
                f.write(";".join(stack_str) + f" {duration}\n")
    
    def _postprocess_call_stack_history(self):
        call_list = []

        for stack_str, duration in self.call_stack_history:
            call_list.append(([x.strip() for x in stack_str.split(";")], duration))
        
        call_list.append((["placeholder"], -1))
        

        start_level = 1
        # For each line in the list
        i = 0
        node = call_list[i]
        while node[1] != -1:
            # For each function in the call stack
            if (call_list[i][0][0] == "placeholder"):
                start_level = call_list[i][1]
                i += 1
                node = call_list[i]
                continue

            for j in range(start_level, len(call_list[i][0])):
                # While at the same level the function name is the same, keep increasing the k idx
                k = 0
                duration = 0

                while i+k+1 < len(call_list) and j < len(call_list[i+k+1][0]) and call_list[i+k+1][0][j] == call_list[i][0][j]:
                    
                    if (len(call_list[i+k][0]) - 1 == j):
                        break

                    if (len(call_list[i+k][0]) - 1 == j + 1):
                        duration += call_list[i+k][1]
                    k += 1

                if k == 0:
                    continue
                else:
                    # Copy the call stack and duration of the first instance
                    tmp = call_list[i+k]
                    tmp_list, dur = tmp
                    dur -= duration
                    tmp = (tmp_list, dur)
                    # Update the call stack with placeholder
                    call_list[i+k] = (["placeholder"], j)
                    # Re-insert the copied call stack and duration
                    call_list.insert(i, tmp)

                    # Look at the next level from the next line onwards
                    start_level += 1
                    break
            
            i += 1
            node = call_list[i]
        
        # Remove the placeholders from the call stack
        self.call_stack_history = [(stack_str, duration) for stack_str, duration in call_list if stack_str[0] != "placeholder"]

        