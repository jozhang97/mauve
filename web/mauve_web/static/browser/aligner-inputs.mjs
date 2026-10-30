// Each buffer is freshly allocated from an immutable Blob. Hand it to MEMFS
// rather than copying it again; callers must not retain or mutate these bytes.
export async function stageInputs(module, inputs) {
  for (let i = 0; i < inputs.length; i++) {
    const bytes = new Uint8Array(await inputs[i].arrayBuffer());
    module.FS.writeFile(`/input-${i + 1}.fa`, bytes, {canOwn: true});
  }
}
