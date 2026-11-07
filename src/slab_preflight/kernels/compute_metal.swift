import Foundation
import Metal

enum ComputeFailure: Error { case message(String) }
func fail(_ message: String) throws -> Never { throw ComputeFailure.message(message) }

let source = """
#include <metal_stdlib>
using namespace metal;
kernel void vectorNorms(device const float* vectors [[buffer(0)]], device float* output [[buffer(1)]],
                        constant uint& count [[buffer(2)]], uint i [[thread_position_in_grid]]) {
    if (i < count) {
        float x = vectors[3 * i], y = vectors[3 * i + 1], z = vectors[3 * i + 2];
        output[i] = sqrt(x * x + y * y + z * z);
    }
}
kernel void difference(device const float* ab [[buffer(0)]], device const float* a [[buffer(1)]],
                       device const float* b [[buffer(2)]], device float* out [[buffer(3)]],
                       constant uint& count [[buffer(4)]], uint i [[thread_position_in_grid]]) {
    if (i < count) out[i] = (ab[i] - a[i]) - b[i];
}
kernel void planePartial(device const float* values [[buffer(0)]], device float* partial [[buffer(1)]],
                         constant uint4& dims [[buffer(2)]], constant uint& chunks [[buffer(3)]],
                         uint gid [[thread_position_in_grid]]) {
    uint axis = dims.w;
    uint planes = axis == 0 ? dims.x : (axis == 1 ? dims.y : dims.z);
    uint plane = gid / chunks, chunk = gid % chunks;
    if (plane >= planes) return;
    uint size = (dims.x * dims.y * dims.z) / planes;
    float sum = 0.0f, correction = 0.0f;
    for (uint j = chunk * 256; j < min(size, (chunk + 1) * 256); j++) {
        uint index = axis == 0 ? plane * size + j :
            (axis == 1 ? (j / dims.z) * dims.y * dims.z + plane * dims.z + j % dims.z : j * dims.z + plane);
        float adjusted = values[index] - correction;
        float next = sum + adjusted;
        correction = (next - sum) - adjusted;
        sum = next;
    }
    partial[gid] = sum;
}
kernel void planeFinish(device const float* partial [[buffer(0)]], device float* average [[buffer(1)]],
                        constant uint4& dims [[buffer(2)]], constant uint& chunks [[buffer(3)]],
                        uint plane [[thread_position_in_grid]]) {
    uint planes = dims.w == 0 ? dims.x : (dims.w == 1 ? dims.y : dims.z);
    if (plane >= planes) return;
    float sum = 0.0f, correction = 0.0f;
    for (uint j = 0; j < chunks; j++) {
        float adjusted = partial[plane * chunks + j] - correction;
        float next = sum + adjusted;
        correction = (next - sum) - adjusted;
        sum = next;
    }
    average[plane] = sum / float((dims.x * dims.y * dims.z) / planes);
}
"""

func respond(_ metadata: [String: Any], _ body: Data) throws {
    let header = try JSONSerialization.data(withJSONObject: metadata, options: [.sortedKeys])
    var length = UInt32(header.count).littleEndian
    var response = withUnsafeBytes(of: &length) { Data($0) }
    response.append(header)
    response.append(body)
    FileHandle.standardOutput.write(response)
}

func main() throws {
    guard let device = MTLCreateSystemDefaultDevice() else { try fail("No Metal compute device is available.") }
    let options = MTLCompileOptions()
    options.fastMathEnabled = false
    let library = try device.makeLibrary(source: source, options: options)
    guard let queue = device.makeCommandQueue() else { try fail("Metal command queue allocation failed.") }
    let input = FileHandle.standardInput.readDataToEndOfFile()
    if input.count < 4 || input.count > 12_010_000 { try fail("Bounded Metal input is missing or too large.") }
    let headerLength = input.prefix(4).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self).littleEndian }
    if headerLength > 4096 || input.count < 4 + Int(headerLength) { try fail("Invalid Metal request header.") }
    let object = try JSONSerialization.jsonObject(with: input.subdata(in: 4..<(4 + Int(headerLength))))
    guard let header = object as? [String: Any], let shape = header["shape"] as? [Int],
          let operation = header["operation"] as? String else { try fail("Invalid Metal request.") }
    if operation == "norms" {
        guard shape.count == 2, shape[1] == 3, shape[0] >= 1, shape[0] <= 80_000 else {
            try fail("Metal vector norms require 1–80,000 three-vectors.")
        }
        let count = shape[0], bodyStart = 4 + Int(headerLength)
        if input.count != bodyStart + count * 3 * 4 { try fail("Metal vector payload length mismatch.") }
        let data = input.subdata(in: bodyStart..<input.count)
        guard let vectors = data.withUnsafeBytes({ device.makeBuffer(bytes: $0.baseAddress!, length: data.count,
                                                                     options: .storageModeShared) }),
              let output = device.makeBuffer(length: count * 4, options: .storageModeShared),
              let function = library.makeFunction(name: "vectorNorms"),
              let command = queue.makeCommandBuffer(), let encoder = command.makeComputeCommandEncoder() else {
            try fail("Metal vector workload allocation failed.")
        }
        let pipeline = try device.makeComputePipelineState(function: function)
        encoder.setComputePipelineState(pipeline)
        encoder.setBuffer(vectors, offset: 0, index: 0)
        encoder.setBuffer(output, offset: 0, index: 1)
        var length = UInt32(count)
        encoder.setBytes(&length, length: 4, index: 2)
        encoder.dispatchThreads(MTLSize(width: count, height: 1, depth: 1),
                                threadsPerThreadgroup: MTLSize(width: min(256, pipeline.maxTotalThreadsPerThreadgroup), height: 1, depth: 1))
        encoder.endEncoding()
        command.commit()
        command.waitUntilCompleted()
        if command.status != .completed { try fail(command.error?.localizedDescription ?? "Metal vector execution failed.") }
        try respond(["device_name": device.name, "precision": "float32", "value_count": count, "plane_count": 0,
                     "gpu_seconds": max(0, command.gpuEndTime - command.gpuStartTime)],
                    Data(bytes: output.contents(), count: count * 4))
        return
    }
    guard
          shape.count == 3, shape.allSatisfy({ $0 >= 2 && $0 <= 1_000_000 }),
          let axis = header["axis"] as? Int, (0...2).contains(axis),
          ["planar", "difference_planar"].contains(operation) else { try fail("Unsupported Metal request.") }
    let count = shape.reduce(1, *)
    if count > 1_000_000 { try fail("Metal grid exceeds 1,000,000 points.") }
    let arrayCount = operation == "difference_planar" ? 3 : 1
    let bodyStart = 4 + Int(headerLength)
    if input.count != bodyStart + count * 4 * arrayCount { try fail("Metal array size mismatch.") }
    var buffers: [MTLBuffer] = []
    for index in 0..<arrayCount {
        let data = input.subdata(in: (bodyStart + index * count * 4)..<(bodyStart + (index + 1) * count * 4))
        guard let buffer = data.withUnsafeBytes({ device.makeBuffer(bytes: $0.baseAddress!, length: data.count,
                                                                    options: .storageModeShared) }) else {
            try fail("Metal input buffer allocation failed.")
        }
        buffers.append(buffer)
    }
    guard let output = device.makeBuffer(length: count * 4, options: .storageModeShared),
          let command = queue.makeCommandBuffer() else { try fail("Metal output allocation failed.") }
    func encode(_ name: String, _ arguments: [MTLBuffer], _ threads: Int,
                _ constants: (MTLComputeCommandEncoder) -> Void) throws {
        guard let function = library.makeFunction(name: name),
              let encoder = command.makeComputeCommandEncoder() else { try fail("Metal kernel allocation failed.") }
        let pipeline = try device.makeComputePipelineState(function: function)
        encoder.setComputePipelineState(pipeline)
        for (index, buffer) in arguments.enumerated() { encoder.setBuffer(buffer, offset: 0, index: index) }
        constants(encoder)
        encoder.dispatchThreads(MTLSize(width: threads, height: 1, depth: 1),
                                threadsPerThreadgroup: MTLSize(width: min(256, pipeline.maxTotalThreadsPerThreadgroup), height: 1, depth: 1))
        encoder.endEncoding()
    }
    if operation == "difference_planar" {
        var length = UInt32(count)
        try encode("difference", buffers + [output], count) { $0.setBytes(&length, length: 4, index: 4) }
    }
    let planes = shape[axis]
    var dimensions = SIMD4<UInt32>(UInt32(shape[0]), UInt32(shape[1]), UInt32(shape[2]), UInt32(axis))
    var chunks = UInt32((count / planes + 255) / 256)
    guard let partial = device.makeBuffer(length: planes * Int(chunks) * 4, options: .storageModeShared),
          let averages = device.makeBuffer(length: planes * 4, options: .storageModeShared) else {
        try fail("Metal reduction buffer allocation failed.")
    }
    try encode("planePartial", [operation == "difference_planar" ? output : buffers[0], partial], planes * Int(chunks)) {
        $0.setBytes(&dimensions, length: 16, index: 2)
        $0.setBytes(&chunks, length: 4, index: 3)
    }
    try encode("planeFinish", [partial, averages], planes) {
        $0.setBytes(&dimensions, length: 16, index: 2)
        $0.setBytes(&chunks, length: 4, index: 3)
    }
    command.commit()
    command.waitUntilCompleted()
    if command.status != .completed { try fail(command.error?.localizedDescription ?? "Metal execution failed.") }
    let metadata: [String: Any] = ["device_name": device.name, "precision": "float32",
        "gpu_seconds": max(0, command.gpuEndTime - command.gpuStartTime),
        "value_count": operation == "difference_planar" ? count : 0, "plane_count": planes]
    var body = Data()
    if operation == "difference_planar" { body.append(Data(bytes: output.contents(), count: count * 4)) }
    body.append(Data(bytes: averages.contents(), count: planes * 4))
    try respond(metadata, body)
}

do { try main() } catch {
    let message: String
    if case ComputeFailure.message(let text) = error { message = text } else { message = String(describing: error) }
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}
