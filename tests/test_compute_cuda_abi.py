"""Host C ABI checks only: these tests do not claim CUDA/PTX hardware execution."""
import ctypes
from pathlib import Path
import platform
import re
import shutil
import subprocess

import numpy as np
import pytest

from slab_preflight.compute_devices import _CudaDriver


def test_bundled_ptx_entry_parameter_widths_match_driver_launch_contract():
    from slab_preflight import compute_devices
    source = (Path(compute_devices.__file__).with_name("kernels") / "density_cuda.ptx").read_text()
    entries = {name: re.findall(r"\.param\s+\.(u64|u32)\s+\w+", arguments)
               for name, arguments in re.findall(r"\.visible\s+\.entry\s+(\w+)\s*\((.*?)\)\s*\{", source, re.S)}
    assert entries == {
        "vector_norms": ["u64", "u64", "u32"],
        "density_difference": ["u64", "u64", "u64", "u64", "u32"],
        "density_planar": ["u64", "u64", "u32", "u32", "u32", "u32"],
    }
    assert ctypes.sizeof(ctypes.c_uint64) == 8
    assert ctypes.sizeof(ctypes.c_uint) == 4


@pytest.mark.skipif(platform.system() not in {"Darwin", "Linux"} or shutil.which("clang") is None,
                    reason="Host ABI probe needs a local clang shared-library compiler")
def test_actual_c_shared_library_receives_launch_parameters_and_transfers(tmp_path):
    # A native C fixture checks Python↔C pointer/size/argument marshalling. Its
    # vector arithmetic runs on the CPU and is deliberately named an ABI stub.
    source = tmp_path / "cuda_abi_stub.c"
    source.write_text(r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
int cuInit(unsigned flags) { return flags ? 901 : 0; }
int cuDeviceGetCount(int *count) { *count = 1; return 0; }
int cuDeviceGet(int *device, int ordinal) { *device = ordinal; return 0; }
int cuDeviceGetName(char *name, int length, int device) {
    if (device || length < 20) return 902;
    strcpy(name, "CPU host ABI stub"); return 0;
}
int cuCtxCreate_v2(void **ctx, unsigned flags, int device) { *ctx = (void*)1; return flags || device; }
int cuCtxDestroy_v2(void *ctx) { return ctx != (void*)1; }
int cuCtxSynchronize(void) { return 0; }
int cuModuleLoadData(void **module, const void *image) { *module = (void*)2; return image ? 0 : 903; }
int cuModuleUnload(void *module) { return module != (void*)2; }
int cuModuleGetFunction(void **function, void *module, const char *name) {
    if (module != (void*)2 || strcmp(name, "vector_norms")) return 904;
    *function = (void*)3; return 0;
}
int cuMemAlloc_v2(uint64_t *pointer, size_t bytes) { *pointer = (uint64_t)(uintptr_t)malloc(bytes); return *pointer ? 0 : 905; }
int cuMemFree_v2(uint64_t pointer) { free((void*)(uintptr_t)pointer); return 0; }
int cuMemcpyHtoD_v2(uint64_t dst, const void *src, size_t bytes) { memcpy((void*)(uintptr_t)dst, src, bytes); return 0; }
int cuMemcpyDtoH_v2(void *dst, uint64_t src, size_t bytes) { memcpy(dst, (void*)(uintptr_t)src, bytes); return 0; }
int cuGetErrorName(int code, const char **name) { *name = "HOST_ABI_STUB_ERROR"; return 0; }
int cuLaunchKernel(void *function, unsigned gx, unsigned gy, unsigned gz,
                   unsigned bx, unsigned by, unsigned bz, unsigned shared,
                   void *stream, void **parameters, void **extra) {
    if (function != (void*)3 || gy != 1 || gz != 1 || bx != 128 || by != 1 || bz != 1 || shared || stream || extra) return 906;
    double *vectors = (double*)(uintptr_t)*(uint64_t*)parameters[0];
    double *output = (double*)(uintptr_t)*(uint64_t*)parameters[1];
    unsigned count = *(unsigned*)parameters[2];
    if (count != 3 || gx != 1) return 907;
    for (unsigned i = 0; i < count; i++) {
        double x = vectors[3*i], y = vectors[3*i+1], z = vectors[3*i+2];
        output[i] = sqrt(x*x + y*y + z*z);
    }
    return 0;
}
''')
    library = tmp_path / ("cuda_abi_stub.dylib" if platform.system() == "Darwin" else "cuda_abi_stub.so")
    flags = ["-dynamiclib"] if platform.system() == "Darwin" else ["-shared", "-fPIC"]
    subprocess.run([shutil.which("clang"), *flags, "-std=c11", str(source), "-lm", "-o", str(library)],
                   check=True, capture_output=True, timeout=30)
    driver = object.__new__(_CudaDriver)
    driver.library = ctypes.CDLL(str(library))
    driver.context = ctypes.c_void_p()
    driver.module = ctypes.c_void_p(2)
    driver.buffers = []
    driver._bind()
    driver.check(driver.library.cuCtxCreate_v2(ctypes.byref(driver.context), 0, 0), "check native host ABI")
    try:
        vectors = np.array([[3., 4., 0.], [0., 0., 2.], [1., 2., 2.]])
        source_pointer = driver.allocate(vectors)
        output_pointer = driver.allocate(None, 3)
        driver.launch(b"vector_norms", [source_pointer, output_pointer, ctypes.c_uint(3)], 3)
        np.testing.assert_array_equal(driver.download(output_pointer, (3,)), [5., 2., 3.])
    finally:
        driver.close()
