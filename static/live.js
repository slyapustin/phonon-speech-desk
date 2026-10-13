"use strict";
window.LiveCapture = class LiveCapture {
  constructor(onEvent, onError) {
    this.onEvent = onEvent;
    this.onError = onError;
    this.finished = false;
    this.done = new Promise(resolve => { this.resolveDone = resolve; });
  }
  async open(context, source, hotwords) {
    if (context.sampleRate !== 16000) throw new Error("This browser cannot capture 16 kHz live audio. Turn off Live transcript to record normally.");
    await context.audioWorklet.addModule("/static/pcm-worklet.js");
    this.socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/live`);
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => this.fail("Live connection timed out."), 10000);
      this.rejectOpen = message => { clearTimeout(timeout); reject(new Error(message)); };
      this.socket.onopen = () => this.socket.send(JSON.stringify({type: "start", sample_rate: 16000, hotwords}));
      this.socket.onmessage = event => {
        const data = JSON.parse(event.data);
        if (data.type === "ready") {
          clearTimeout(timeout);
          this.rejectOpen = null;
          resolve();
        } else if (data.type === "complete") {
          this.finished = true;
          this.resolveDone(data);
        } else if (data.type === "error") this.fail(data.message);
        else this.onEvent(data);
      };
      this.socket.onerror = () => this.fail("Cannot connect to live transcription. Check that the local server is running.");
      this.socket.onclose = () => {
        if (!this.finished) this.fail("Live connection closed. Your recording remains available after you stop.");
      };
    });
    this.node = new AudioWorkletNode(context, "pcm-recorder");
    this.node.port.onmessage = event => {
      if (event.data === "flushed") {
        if (this.socket.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({type: "stop"}));
        this.resolveFlush?.();
      } else if (this.socket.readyState === WebSocket.OPEN) {
        if (this.socket.bufferedAmount > 320000) this.fail("Live decoding fell behind. Stop and use Transcribe this audio for the complete recording.");
        else this.socket.send(event.data);
      }
    };
    source.connect(this.node);
    this.node.connect(context.destination);
  }
  async flush() {
    if (!this.node || this.finished) return;
    await new Promise(resolve => {
      const timeout = setTimeout(() => { this.fail("Audio capture did not finish cleanly. Use Transcribe this audio after stopping."); resolve(); }, 1500);
      this.resolveFlush = () => { clearTimeout(timeout); resolve(); };
      this.node.port.postMessage("stop");
    });
    this.node.disconnect();
  }
  async result() {
    const timeout = setTimeout(() => this.fail("The final live transcript timed out. You can transcribe the saved recording again."), 30000);
    try { return await this.done; }
    finally { clearTimeout(timeout); }
  }
  fail(message) {
    if (this.finished) return;
    this.finished = true;
    this.rejectOpen?.(message);
    this.resolveDone(null);
    this.node?.disconnect();
    this.socket?.close();
    this.onError(message);
  }
  abort() {
    this.finished = true;
    this.resolveDone(null);
    this.node?.disconnect();
    this.socket?.close();
  }
};
