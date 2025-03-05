import argparse
import os
import subprocess
import tempfile
import importlib.resources as pkg_resources
from rv_profile.rv_profile import riscv_profile_main
from rv_profile.colors import fix_color
from yaspin import yaspin

def run_perl_script(fg_data, svg):
    """Run a Perl script bundled with the package."""
    scripts_path = pkg_resources.files("rv_profile") / "FlameGraph"
    script_path = scripts_path / "flamegraph.pl"

    if not script_path.exists():
        raise FileNotFoundError(f"Script flamegraph.pl not found in package")

    command = [f"{script_path}", "--flamechart", f"{fg_data}"]

    # Write the output to a file
    with open(svg, "w") as f:
        subprocess.run(command, check=True, stdout=f, text=True, stderr=subprocess.DEVNULL)

def main():
    parser = argparse.ArgumentParser(description='Generate a flamegraph from a RISC-V binary and a FST file.')
    parser.add_argument('--elf', metavar='ELF', type=str, help='The RISC-V .elf file', required=True)
    parser.add_argument('--fst', metavar='FST', type=str, help='The .fst file', required=True)
    parser.add_argument('--cfg', metavar='CFG', type=str, help='The .wal config file', required=True)
    parser.add_argument('--out', metavar='OUT', type=str, help='The output name of the flamegraph', default='flamegraph.svg')
    # parser.add_argument('--step', metavar='STEP', type=int, help='Start flamegraph generation from a given timestep', default=0)

    
    parser = parser.parse_args()
    ELF = parser.elf
    FST = parser.fst
    CFG = parser.cfg
    OUTPUT = parser.out
    STEP = 0 # Disabled for now


    config_file, _ = os.path.splitext(CFG)
    OUTPUT, _ = os.path.splitext(OUTPUT) # Get rid of the extension

    # Get relative path to config file
    config_file = os.path.relpath(config_file)

    # Create a temporary file to store the flamegraph data
    tmp = tempfile.NamedTemporaryFile(delete=False)

    # Generate the flamegraph data
    with yaspin(text="Reading the waveforms", color="cyan") as sp:
        riscv_profile_main(ELF, FST, config_file, tmp.name, STEP)
        sp.ok("✔")

    # Generate the flamegraph SVF
    with yaspin(text="Creating the flamegraph", color="cyan") as sp:
        run_perl_script(tmp.name, f"{OUTPUT}.svg")

        # Fix colors
        fix_color(f"{OUTPUT}.svg")

        sp.ok("✔")
        print(f"Generated flamegraph at {OUTPUT}.svg")

    # Close the temporary file and delete it
    tmp.close()

if __name__ == "__main__":
    main()
