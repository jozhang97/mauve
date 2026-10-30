#pragma once
// The shared four-lane scoring kernel uses only these exact Wasm operations.
// Native builds map them to NEON and compile with FP contraction disabled.
#include <arm_neon.h>
using v128_t = float32x4_t;
inline v128_t wasm_f32x4_splat(float x) { return vdupq_n_f32(x); }
inline v128_t wasm_v128_load(const void *p) { return vld1q_f32(static_cast<const float *>(p)); }
inline void wasm_v128_store(void *p, v128_t x) { vst1q_f32(static_cast<float *>(p), x); }
inline v128_t wasm_f32x4_add(v128_t a, v128_t b) { return vaddq_f32(a, b); }
inline v128_t wasm_f32x4_sub(v128_t a, v128_t b) { return vsubq_f32(a, b); }
inline v128_t wasm_f32x4_mul(v128_t a, v128_t b) { return vmulq_f32(a, b); }
