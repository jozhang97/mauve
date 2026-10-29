import {pairCounts} from './core.mjs';
// Packed ASCII: four bases per u32, integer reductions, no floating point drift.
const shader = `
struct Params { length: u32, width: u32, bins: u32, pad: u32 }
@group(0) @binding(0) var<storage, read> a: array<u32>;
@group(0) @binding(1) var<storage, read> b: array<u32>;
@group(0) @binding(2) var<storage, read_write> output: array<vec4<u32>>;
@group(0) @binding(3) var<uniform> p: Params;
var<workgroup> sums: array<vec4<u32>, 128>;
fn canonical(x: u32) -> bool { return x == 65u || x == 67u || x == 71u || x == 84u; }
@compute @workgroup_size(128)
fn main(@builtin(workgroup_id) group: vec3<u32>, @builtin(local_invocation_id) local: vec3<u32>) {
 let bin = group.x; let lane = local.x;
 let start = bin * p.width; let end = min(start + p.width, p.length);
 var counts = vec4<u32>(0u);
 for (var i = start + lane; i < end; i += 128u) {
  let shift = (i & 3u) * 8u;
  let x = (a[i >> 2u] >> shift) & 255u; let y = (b[i >> 2u] >> shift) & 255u;
  if (x == 45u || y == 45u) { counts.z += 1u; }
  else if (canonical(x) && canonical(y)) { counts.y += 1u; if (x == y) { counts.x += 1u; } }
  else { counts.w += 1u; }
 }
 sums[lane] = counts; workgroupBarrier();
 for (var stride = 64u; stride > 0u; stride >>= 1u) {
  if (lane < stride) { sums[lane] += sums[lane + stride]; } workgroupBarrier();
 }
 if (lane == 0u) { output[bin] = sums[0]; }
}`;
export class Accelerator {
  constructor() { this.mode = 'CPU worker'; this.device = null; this.ready = this.init(); }
  async init() {
    try {
      const adapter = await globalThis.navigator?.gpu?.requestAdapter({powerPreference: 'high-performance'});
      if (!adapter) return;
      const device = await adapter.requestDevice();
      const module = device.createShaderModule({code: shader});
      this.pipeline = await device.createComputePipelineAsync({layout: 'auto', compute: {module, entryPoint: 'main'}});
      this.device = device; this.mode = 'WebGPU + CPU worker';
      this.adapter = adapter.info?.description || adapter.info?.vendor || 'WebGPU';
      device.lost.then(() => { this.device = null; this.mode = 'CPU worker (GPU unavailable)'; });
      // Verify on mixed gaps/ambiguity and a non-multiple-of-four length before use.
      const a = new TextEncoder().encode('ACGTN--RYACGT'.repeat(400) + 'A');
      const b = new TextEncoder().encode('ATGTAC-RY-CGT'.repeat(400) + 'T');
      const expected = pairCounts(a, b, 53), actual = await this.gpuCounts(a, b, 53);
      if (expected.some((v, i) => v !== actual[i])) throw Error('GPU parity check failed');
    } catch (e) { this.device?.destroy(); this.device = null; this.mode = 'CPU worker'; this.reason = e.message; }
  }
  async counts(a, b, width) {
    await this.ready;
    // Small blocks are quicker without upload/dispatch/readback overhead.
    if (this.device && a.length >= 1048576 && a.length <= Math.min(32 * 1024 * 1024, this.device.limits.maxStorageBufferBindingSize)) {
      try { return await this.gpuCounts(a, b, width); }
      catch (e) { this.device?.destroy(); this.device = null; this.mode = 'CPU worker'; this.reason = e.message; }
    }
    return pairCounts(a, b, width);
  }
  async gpuCounts(a, b, width) {
    const device = this.device, bins = Math.ceil(a.length / width), size = Math.ceil(a.length / 4) * 4, buffers = [];
    device.pushErrorScope('validation');
    const create = (size, usage) => { const buffer = device.createBuffer({size, usage}); buffers.push(buffer); return buffer; };
    try {
      const aa = create(size, GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST), bb = create(size, GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST);
      const upload = (buffer, data) => { if (data.byteLength === size) device.queue.writeBuffer(buffer, 0, data); else { const padded = new Uint8Array(size); padded.set(data); device.queue.writeBuffer(buffer, 0, padded); } };
      upload(aa, a); upload(bb, b);
      const result = create(bins * 16, GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC);
      const read = create(bins * 16, GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST);
      const params = create(16, GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST);
      device.queue.writeBuffer(params, 0, new Uint32Array([a.length, width, bins, 0]));
      const bind = device.createBindGroup({layout: this.pipeline.getBindGroupLayout(0), entries: [aa, bb, result, params].map((buffer, binding) => ({binding, resource: {buffer}}))});
      const command = device.createCommandEncoder(), pass = command.beginComputePass();
      pass.setPipeline(this.pipeline); pass.setBindGroup(0, bind); pass.dispatchWorkgroups(bins); pass.end();
      command.copyBufferToBuffer(result, 0, read, 0, bins * 16); device.queue.submit([command.finish()]);
      await read.mapAsync(GPUMapMode.READ);
      const values = new Uint32Array(read.getMappedRange()).slice(); read.unmap(); return values;
    } finally {
      for (const b of buffers) b.destroy();
      const error = await device.popErrorScope(); if (error) throw Error(error.message);
    }
  }
}
