// Shared audio helpers for voice dictation: PCM16 WAV @16kHz for the
// STT endpoint. Kept in its own module — Composer.jsx and Discuss.jsx
// both use these and must not import each other (cycle → TDZ crash).
export const STT_RATE = 16000;

export function resample(chunks, srcRate, dstRate) {
  const srcLen = chunks.reduce((a, c) => a + c.length, 0);
  const src = new Float32Array(srcLen);
  let off = 0;
  for (const c of chunks) { src.set(c, off); off += c.length; }
  if (srcRate === dstRate || !srcLen) return [src];
  const dstLen = Math.round(srcLen * dstRate / srcRate);
  const dst = new Float32Array(dstLen);
  const ratio = srcRate / dstRate;
  for (let i = 0; i < dstLen; i++) {
    const p = i * ratio, i0 = Math.floor(p),
          i1 = Math.min(i0 + 1, srcLen - 1), f = p - i0;
    dst[i] = src[i0] + (src[i1] - src[i0]) * f;
  }
  return [dst];
}

export function encodeWav(chunks, rate) {
  const len = chunks.reduce((a, c) => a + c.length, 0);
  const buf = new ArrayBuffer(44 + len * 2), v = new DataView(buf);
  const ws = (o, s) => { for (let i = 0; i < s.length; i++)
    v.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, "RIFF"); v.setUint32(4, 36 + len * 2, true); ws(8, "WAVEfmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  ws(36, "data"); v.setUint32(40, len * 2, true);
  let o = 44;
  for (const ch of chunks)
    for (let i = 0; i < ch.length; i++, o += 2) {
      const s = Math.max(-1, Math.min(1, ch[i]));
      v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
  return buf;
}
