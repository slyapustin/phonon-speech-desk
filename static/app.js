"use strict";
const $ = (id) => document.getElementById(id);
let ready = false, busy = false, starting = false, recorder = null, stream = null;
let audioContext = null, analyser = null, animation = null, interval = null;
let started = 0, result = null, engineStatus = null;
let selectedAudio = null, audioUrl = null, loadingAudio = false, sampleLibrary = [];
let liveCapture = null, stopping = false;
const maxBytes = 32 * 1024 * 1024;
const canvas = $("wave"), context = canvas.getContext("2d");

function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}
function syncControls() {
  const recording = recorder?.state === "recording";
  $("record").disabled = stopping || (!recording && (!ready || busy || starting || loadingAudio));
  $("file").disabled = !ready || busy || recording || starting || loadingAudio;
  $("sample").disabled = $("file").disabled || !selectedAudio;
  $("sample-select").disabled = busy || recording || starting || loadingAudio || !sampleLibrary.length;
  $("audio-player").controls = !recording && !starting;
  $("hotwords").disabled = busy || recording || starting;
  $("live-mode").disabled = busy || recording || starting || stopping;
  $("record").classList.toggle("recording", recording);
  $("record-label").textContent = recording ? (liveCapture ? "Stop recording" : "Stop & transcribe") : "Start recording";
  $("copy").disabled = !$("transcript").value.trim();
  $("download").disabled = $("copy").disabled;
  $("json").disabled = !result;
}
async function status() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error("Server is unavailable.");
    const data = await response.json();
    const changed = engineStatus !== data.status;
    engineStatus = data.status;
    ready = data.status === "ready";
    $("engine-status").textContent = ready ? "Local engine ready" : data.status === "error" ? "Engine unavailable" : "Loading model…";
    $("engine-status").parentElement.className = `status ${ready ? "ready" : data.status === "error" ? "error" : ""}`;
    if (ready) {
      const device = data.engine.device?.device_name || "Apple silicon";
      $("engine-detail").textContent = `Phonon-2 · MLX GPU · ${device}. Model startup: ${data.load_seconds.toFixed(2)} s. Fast paths: ${(data.engine.levers || []).join(", ") || "none"}.`;
      if (changed && !busy) notice("Choose a file, record your voice, or try the sample.");
    } else if (data.error) notice(`Model could not start: ${data.error}`, true);
    syncControls();
  } catch (error) {
    ready = false;
    engineStatus = "disconnected";
    $("engine-status").textContent = "Server disconnected";
    $("engine-status").parentElement.className = "status error";
    if (!busy) notice("Cannot reach the local server. Run ./run.sh in the project folder.", true);
    syncControls();
  }
}
function drawWave() {
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = recorder?.state === "recording" ? "#b34337" : "#a7bddc";
  context.lineWidth = 3;
  context.beginPath();
  if (analyser) {
    const values = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(values);
    values.forEach((value, index) => {
      const x = index / (values.length - 1) * canvas.width;
      const y = value / 128 * canvas.height / 2;
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    animation = requestAnimationFrame(drawWave);
  } else {
    context.moveTo(25, canvas.height / 2);
    context.lineTo(canvas.width - 25, canvas.height / 2);
  }
  context.stroke();
}
function releaseMicrophone() {
  clearInterval(interval);
  cancelAnimationFrame(animation);
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  if (audioContext) audioContext.close().catch(() => {});
  audioContext = null;
  analyser = null;
  drawWave();
}
async function microphoneError(error) {
  if (error.name === "NotAllowedError" || error.name === "SecurityError") {
    const permission = await navigator.permissions?.query({name: "microphone"}).then(value => value.state).catch(() => "unknown");
    if (permission === "denied") {
      return "Microphone blocked for this site. Click the site controls beside the address bar, allow Microphone, then reload and try again. Also check macOS System Settings → Privacy & Security → Microphone.";
    }
    return "The browser could not access your microphone. Open http://127.0.0.1:8765 in regular Chrome or Safari (automated or embedded browsers may block recording). In macOS System Settings → Privacy & Security → Microphone, enable that browser, then quit and reopen it if needed. File upload still works.";
  }
  if (error.name === "NotFoundError") return "No microphone was found. Connect one or select an available input in macOS Sound settings.";
  if (error.name === "NotReadableError") return "The microphone could not be opened. Check the selected input and close other apps using it, then retry.";
  return error.message || "Recording failed. Try an audio file instead.";
}
async function record() {
  if (stopping) return;
  if (recorder?.state === "recording") {
    stopping = true;
    busy = true;
    syncControls();
    await liveCapture?.flush();
    recorder.stop();
    releaseMicrophone();
    syncControls();
    return;
  }
  starting = true;
  $("audio-player").pause();
  syncControls();
  try {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      throw new Error("This browser cannot record audio. Open localhost in Safari or Chrome, or upload a file.");
    }
    stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true}, video: false});
    audioContext = new AudioContext($("live-mode").checked ? {sampleRate: 16000} : undefined);
    await audioContext.resume();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    const source = audioContext.createMediaStreamSource(stream);
    source.connect(analyser);
    if ($("live-mode").checked) {
      notice("Connecting to live transcription…");
      liveCapture = new window.LiveCapture(updateLiveTranscript, message => notice(message, true));
      await liveCapture.open(audioContext, source, $("hotwords").value.split(",").map(word => word.trim()).filter(Boolean));
      $("transcript").value = "";
      $("transcript").readOnly = true;
      $("live-indicator").hidden = false;
      result = null;
      updateWords();
    }
    const capture = liveCapture;
    const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find((type) => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
    const chunks = [];
    let bytes = 0, failed = false;
    recorder.ondataavailable = (event) => {
      if (event.data.size) { chunks.push(event.data); bytes += event.data.size; }
      if (bytes > maxBytes && recorder.state === "recording") record();
    };
    recorder.onerror = () => {
      failed = true;
      capture?.abort();
      releaseMicrophone();
      busy = false;
      stopping = false;
      liveCapture = null;
      $("transcript").readOnly = false;
      $("live-indicator").hidden = true;
      notice("Recording failed. Check microphone access and try again.", true);
      syncControls();
    };
    recorder.onstop = async () => {
      releaseMicrophone();
      if (failed) return;
      const blob = new Blob(chunks, {type: recorder.mimeType});
      recorder = null;
      $("record-hint").textContent = "Recording complete.";
      const filename = mimeType?.includes("mp4") ? "recording.m4a" : "recording.webm";
      selectAudio(blob, filename);
      if (capture) {
        busy = true;
        notice("Finalizing the live transcript…");
        const data = await capture.result();
        if (data) {
          renderResult(data, filename);
          notice(data.text ? "Live transcript complete. Play back your recording or transcribe it again for word timestamps." : "No speech detected. You can play back your recording below.");
        } else notice("Live transcription ended early. Your audio is available: choose Transcribe this audio to process the whole recording.", true);
        busy = false;
        liveCapture = null;
        stopping = false;
        $("transcript").readOnly = false;
        $("live-indicator").hidden = true;
        syncControls();
      } else {
        busy = false;
        stopping = false;
        await transcribe(blob, filename);
      }
    };
    recorder.start(250);
    started = Date.now();
    $("timer").textContent = "00:00";
    $("record-hint").textContent = capture ? "Listening. Words appear as you speak." : "Listening. Stop when you’re finished.";
    notice(capture ? "Live transcription is on. The current phrase may change as you speak." : "Recording locally. Your transcript appears after you stop.");
    interval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - started) / 1000);
      $("timer").textContent = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;
      // Leave a small margin below the server's hard duration limit.
      if (elapsed >= 599 && recorder?.state === "recording") record();
    }, 250);
    drawWave();
  } catch (error) {
    liveCapture?.abort();
    liveCapture = null;
    $("transcript").readOnly = false;
    $("live-indicator").hidden = true;
    releaseMicrophone();
    notice(await microphoneError(error), true);
  } finally {
    starting = false;
    syncControls();
  }
}
function updateWords() {
  const text = $("transcript").value.trim();
  const count = text ? text.split(/\s+/).length : 0;
  $("word-count").textContent = `${count} ${count === 1 ? "word" : "words"}`;
  syncControls();
}
function updateLiveTranscript(data) {
  if (data.type !== "partial" && data.type !== "final") return;
  $("transcript").value = [data.final_text, data.type === "partial" ? data.text : ""].filter(Boolean).join(" ");
  $("transcript").scrollTop = $("transcript").scrollHeight;
  $("live-indicator").textContent = data.type === "partial" ? "Live draft" : "Listening";
  updateWords();
}
function renderResult(data, filename) {
  result = data;
  $("transcript").value = data.text;
  $("audio-time").textContent = `${data.audio_seconds.toFixed(1)} s`;
  $("process-label").textContent = data.mode === "live" ? "Live decode work" : "Processing";
  $("process-time").textContent = `${data.processing_seconds.toFixed(2)} s`;
  $("speed").textContent = `${data.speed_x.toFixed(1)}×`;
  $("timing-detail").textContent = data.mode === "live"
    ? `Live decoding used ${data.decode_seconds.toFixed(3)} s across all provisional and final updates. Session elapsed: ${data.session_seconds.toFixed(1)} s. This is cumulative decode work, not word latency. Transcribe the recording again for word timestamps.`
    : `Decode: ${data.decode_seconds.toFixed(3)} s. Conversion: ${data.conversion_seconds.toFixed(3)} s. Total processing: ${data.processing_seconds.toFixed(3)} s. Excludes upload and model startup. Word timestamps are included in timing data.`;
  notice(data.truncated ? "Some audio hit the decoder limit. Check the transcript for missing words." : data.text ? `Finished ${filename}. You can edit or save the transcript.` : "No speech detected. Try speaking louder or choose another recording.", data.truncated);
  updateWords();
}
async function transcribe(blob, filename) {
  if (!ready || busy || recorder?.state === "recording") return;
  if (blob.size > maxBytes) { notice("File is larger than 32 MB. Choose a smaller file.", true); return; }
  if (!blob.size) { notice("The recording is empty. Try recording again.", true); return; }
  busy = true;
  syncControls();
  notice(`Transcribing ${filename} on your Mac…`);
  const form = new FormData();
  form.append("file", blob, filename);
  form.append("hotwords", $("hotwords").value);
  try {
    const response = await fetch("/api/transcribe", {method: "POST", body: form});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The request could not be processed.");
    renderResult(data, filename);
  } catch (error) {
    notice(error.message || "Transcription failed. Check the server and try again.", true);
  } finally {
    busy = false;
    syncControls();
  }
}
function save(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function selectAudio(blob, filename, sample = null) {
  const player = $("audio-player");
  player.pause();
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = URL.createObjectURL(blob);
  selectedAudio = {blob, filename};
  player.src = audioUrl;
  player.load();
  $("audio-name").textContent = sample?.title || filename;
  $("save-audio").href = audioUrl;
  $("save-audio").download = filename;
  $("save-audio").hidden = false;
  $("reference-panel").hidden = !sample;
  $("reference-text").textContent = sample?.reference || "";
  if (!sample) {
    $("sample-select").value = "";
    $("sample-description").textContent = "Listening to your selected file or microphone recording.";
  }
  syncControls();
}
async function loadSelectedSample() {
  const sample = sampleLibrary.find(item => item.id === $("sample-select").value);
  if (!sample) return;
  loadingAudio = true;
  syncControls();
  try {
    const response = await fetch(`/api/sample?sample_id=${encodeURIComponent(sample.id)}`);
    if (!response.ok) throw new Error("The sample could not be loaded. Run ./make_sample.sh to regenerate it.");
    selectAudio(await response.blob(), `${sample.id}.wav`, sample);
    $("sample-description").textContent = sample.description;
    notice(`Loaded ${sample.title}. Press play to listen, or Transcribe this audio. Any existing transcript is from your previous run.`);
  } catch (error) { notice(error.message, true); }
  finally { loadingAudio = false; syncControls(); }
}
async function loadSamples() {
  try {
    const response = await fetch("/api/samples");
    if (!response.ok) throw new Error("Sample library unavailable. Restart the server after updating the app.");
    sampleLibrary = await response.json();
    $("sample-select").replaceChildren(new Option("Choose a sample", ""));
    for (const sample of sampleLibrary) {
      const seconds = Math.round(sample.duration);
      $("sample-select").add(new Option(`${sample.title} · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`, sample.id));
    }
    $("sample-select").value = sampleLibrary.some(item => item.id === "long-noisy") ? "long-noisy" : "demo";
    await loadSelectedSample();
  } catch (error) { notice(error.message, true); }
}
$("record").addEventListener("click", record);
$("file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file && file.size <= maxBytes) selectAudio(file, file.name);
  if (file) transcribe(file, file.name);
  event.target.value = "";
});
$("dropzone").addEventListener("dragover", (event) => { event.preventDefault(); $("dropzone").classList.add("dragover"); });
$("dropzone").addEventListener("dragleave", () => $("dropzone").classList.remove("dragover"));
$("dropzone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("dropzone").classList.remove("dragover");
  if ($("file").disabled) return;
  const file = event.dataTransfer.files[0];
  if (file && file.size <= maxBytes) selectAudio(file, file.name);
  if (file) transcribe(file, file.name);
});
$("sample-select").addEventListener("change", loadSelectedSample);
$("sample").addEventListener("click", () => {
  if (selectedAudio) transcribe(selectedAudio.blob, selectedAudio.filename);
});
$("transcript").addEventListener("input", updateWords);
$("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("transcript").value); notice("Transcript copied."); }
  catch { notice("Clipboard access is unavailable. Select the transcript and copy it manually.", true); }
});
$("download").addEventListener("click", () => save("transcript.txt", $("transcript").value, "text/plain"));
$("json").addEventListener("click", () => save("transcript.json", JSON.stringify({...result, edited_text: $("transcript").value}, null, 2), "application/json"));
window.addEventListener("pagehide", () => { liveCapture?.abort(); releaseMicrophone(); $("audio-player").pause(); });
drawWave();
status();
loadSamples();
setInterval(status, 3000);
