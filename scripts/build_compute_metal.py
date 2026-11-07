"""Build the native Metal helper for inclusion beside the bundled kernel source."""
from pathlib import Path
import argparse
import platform

from slab_preflight.compute_devices import build_metal_helper

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True,
                    help="Packager destination, normally kernels/calclens-metal-<architecture>")
arguments = parser.parse_args()
print(build_metal_helper(arguments.output))
print(f"Built native Metal helper for {platform.machine()}.")
