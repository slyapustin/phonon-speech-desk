// AudioContext resamples the microphone to 16 kHz before it reaches this node.
class PCMRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(800);
    this.used = 0;
    this.stopped = false;
    this.port.onmessage = (event) => {
      if (event.data === "stop") {
        this.stopped = true;
        if (this.used) this.port.postMessage(this.buffer.slice(0, this.used).buffer);
        this.port.postMessage("flushed");
      }
    };
  }
  process(inputs) {
    if (this.stopped) return true;
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (const sample of channel) {
      this.buffer[this.used++] = sample;
      if (this.used === this.buffer.length) {
        const block = this.buffer.slice();
        this.port.postMessage(block.buffer, [block.buffer]);
        this.used = 0;
      }
    }
    // Output stays silent, preventing microphone feedback.
    return true;
  }
}
registerProcessor("pcm-recorder", PCMRecorder);
