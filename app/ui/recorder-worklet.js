// Runs in the audio thread: copies microphone frames (first channel) to the page.
class VokalitRecorder extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}

registerProcessor("vokalit-recorder", VokalitRecorder);
