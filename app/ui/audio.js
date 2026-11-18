// Audio helpers. Pure functions (tested with node --test) and browser-only recording/decoding.
// Everything the server receives is 16-bit mono WAV encoded here.

export function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  write(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, Math.round(s < 0 ? s * 32768 : s * 32767), true);
  }
  return buffer;
}

export function trim(samples, sampleRate, startSec, endSec) {
  const start = Math.max(0, Math.round(startSec * sampleRate));
  const end = Math.min(samples.length, Math.round(endSec * sampleRate));
  return samples.slice(start, Math.max(start, end));
}

// Loudest absolute value per bucket, scaled so the loudest bucket is 1.
export function peaks(samples, buckets) {
  const size = Math.max(1, Math.floor(samples.length / buckets));
  const values = [];
  for (let b = 0; b < buckets; b++) {
    let max = 0;
    for (let i = b * size; i < Math.min(samples.length, (b + 1) * size); i++) max = Math.max(max, Math.abs(samples[i]));
    values.push(max);
  }
  const top = Math.max(...values, 1e-9);
  return values.map((v) => v / top);
}

// --- Browser only -----------------------------------------------------------------------------

function mono(audioBuffer) {
  const out = new Float32Array(audioBuffer.length);
  for (let c = 0; c < audioBuffer.numberOfChannels; c++) {
    const data = audioBuffer.getChannelData(c);
    for (let i = 0; i < data.length; i++) out[i] += data[i] / audioBuffer.numberOfChannels;
  }
  return out;
}

// Decodes an uploaded file or fetched URL (wav, mp3, m4a, ogg...) to { samples, sampleRate }.
export async function decode(source) {
  const bytes = source instanceof Blob ? await source.arrayBuffer() : await (await fetch(source)).arrayBuffer();
  const context = new AudioContext();
  try {
    const audio = await context.decodeAudioData(bytes);
    return { samples: mono(audio), sampleRate: audio.sampleRate };
  } finally {
    context.close();
  }
}

export async function microphones() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((d) => d.kind === "audioinput");
}

// Starts recording. Returns { stop(): Promise<{samples, sampleRate}>, seconds(): number, level(): number }.
// onPermission(allowed) gets the answer to the microphone prompt, so the app can remember it.
export async function record(deviceId, onPermission = () => {}) {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { deviceId: deviceId ? { exact: deviceId } : undefined, echoCancellation: false, noiseSuppression: false,
        autoGainControl: false },
    });
  } catch (error) {
    if (error.name === "NotAllowedError") onPermission(false);
    throw error;
  }
  onPermission(true);
  const context = new AudioContext();
  await context.audioWorklet.addModule("/ui/recorder-worklet.js");
  const source = context.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(context, "vokalit-recorder");
  const chunks = [];
  let length = 0;
  let level = 0;
  node.port.onmessage = (event) => {
    chunks.push(event.data);
    length += event.data.length;
    level = Math.max(...event.data.map(Math.abs));
  };
  source.connect(node);
  return {
    seconds: () => length / context.sampleRate,
    level: () => level,
    async stop() {
      source.disconnect();
      node.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      const samples = new Float32Array(length);
      let offset = 0;
      for (const chunk of chunks) {
        samples.set(chunk, offset);
        offset += chunk.length;
      }
      const sampleRate = context.sampleRate;
      await context.close();
      return { samples, sampleRate };
    },
  };
}
