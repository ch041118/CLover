/** Expo may release its native recorder before component cleanup runs. */
type Recorder = { readonly uri: string | null; stop(): Promise<void> };
const pending = new WeakMap<Recorder, Promise<void>>();
export function stopAndCleanRecorder(recorder: Recorder, clean: (uri: string | null) => void): Promise<void> {
  const existing = pending.get(recorder);
  if (existing) return existing;
  const work = (async () => {
    let uri: string | null = null;
    // Both native methods and property getters may throw synchronously after release.
    try { uri = recorder.uri; } catch {}
    try { await recorder.stop(); } catch {}
    try { uri = recorder.uri || uri; } catch {}
    try { clean(uri); } catch {}
  })();
  pending.set(recorder, work);
  void work.then(() => { if (pending.get(recorder) === work) pending.delete(recorder); });
  return work;
}
