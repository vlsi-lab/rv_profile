# rv_profile 
[![PyPI version](https://img.shields.io/pypi/v/rv-profile)](https://pypi.org/project/rv-profile/)
![License](https://img.shields.io/pypi/l/rv-profile)

![FlameGraph](https://vincenzo-petrolo.github.io/flamegraph_example/flamegraph.svg)

This project implements a cycle-accurate RISC-V profiler that extracts the cycles spent in each function from RTL simulations.


An interactive example is found [here](https://vincenzo-petrolo.github.io/flamegraph_example/flamegraph.svg).

## Installing
```
pip install rv-profile
```
> [!NOTE]  
> Python >=3.7 version is required.

## Supported RISC-V Cores
Currently, we support the following cores:
* [cv32e40x](https://github.com/openhwgroup/cv32e40x)
* [cv32e40px](https://github.com/esl-epfl/cv32e40px)
* [cv32e40p](https://github.com/openhwgroup/cv32e40p)
* [cv32e20](https://github.com/openhwgroup/cve2)

## Using
To profile a waveform you need to have a RISC-V `.elf` binary and a `.vcd`/`.fst` waveform of a RISC-V core running the binary.
This repository contains several examples for the [cv32e40x](https://github.com/Vincenzo-Petrolo/riscv-function-profiling/blob/main/cv32e40x/), [cv32e40px](https://github.com/Vincenzo-Petrolo/riscv-function-profiling/blob/main/cv32e40px/), [cv32e40p](https://github.com/Vincenzo-Petrolo/riscv-function-profiling/blob/main/cv32e40p/), and [cv32e20](https://github.com/Vincenzo-Petrolo/riscv-function-profiling/blob/main/cv32e20/) cores.

```bash
rv_profile --elf <.elf> --fst <.vcd/.fst file> --cfg <.wal file> [--out <flamegraph.svg>]
```

## Adapting to Other Cores
To adapt a new core to this script is easy. All you have to do is to have the following signals available.

```
(alias clk          ...cv32e40x_core_i.id_stage_i.clk               )
(alias rst_ni       ...cv32e40x_core_i.id_stage_i.rst_n             )
(alias pc           ...cv32e40x_core_i.id_stage_i.if_id_pipe_i.pc   )
(alias instr        ...cv32e40x_core_i.id_stage_i.instr             )
(alias instr_valid  ...cv32e40x_core_i.id_stage_i.instr_valid       )
(alias mcycle       ...cv32e40x_core_i.cs_registers_i.mcycle_o      )
```

So you have to change `(alias clk ....)` to `(alias clk your.clk.signal)` and so on.

This information can then be entered in a new `config.wal` file just like the ones in [cv32e40x](https://github.com/Vincenzo-Petrolo/riscv-function-profiling/blob/main/cv32e40x/config.wal).


## Contributing
If you want to contribute to this project, please open an issue or a pull request. We are happy to help you with any questions you might have.

If you use this tool on a different RISC-V core please open a pull request so that we can include it in the repository.

### Repositories that made this possible
* [RISC-V Function Profiling](https://github.com/LucasKl/riscv-function-profiling) 
* [WAL](https://github.com/ics-jku/wal)
* [FlameGraph](https://github.com/brendangregg/FlameGraph)
