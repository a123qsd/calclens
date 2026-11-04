"""Pure checks for the Windows frozen-executable smoke harness."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "calclens_windows_smoke", ROOT / "scripts" / "smoke_windows_exe.py"
)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_descendant_process_ids_follows_bootloader_child_chain_only():
    parents = {
        100: 50,
        101: 100,  # onefile Python child
        102: 101,  # any descendant owned by that runtime
        200: 50,   # unrelated process with the same parent
        201: 200,
    }
    assert smoke.descendant_process_ids(100, parents) == {100, 101, 102}


def test_descendant_process_ids_ignores_unrooted_cycles_and_pid_like_values():
    parents = {
        "11": "10",
        12: 11,
        30: 31,
        31: 30,
        40: 999,
    }
    assert smoke.descendant_process_ids(10, parents) == {10, 11, 12}
