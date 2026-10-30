export function alignerConfig(scope = globalThis, requested) {
  const supported = scope.crossOriginIsolated === true && typeof scope.SharedArrayBuffer === 'function';
  const available = Math.max(1, Math.min(8, Math.floor(scope.navigator?.hardwareConcurrency || 1)));
  if (requested !== undefined && (!Number.isInteger(requested) || requested < 1 || requested > 16)) {
    throw Error('Alignment thread count must be an integer from 1 to 16.');
  }
  const threads = supported ? requested ?? available : 1;
  return {threads, directory: threads > 1 ? 'wasm-threaded' : 'wasm', threaded: threads > 1};
}
