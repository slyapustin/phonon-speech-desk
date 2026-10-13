# Phonon local speech desk

A working Apple silicon speech-to-text POC: live microphone transcription, audio playback, clean/noisy sample comparisons, file uploads, editable transcripts, and text/JSON export.

## Quick start

This is the original browser experiment, separate from the Call Note desktop app. Each coworker runs it locally on an **Apple Silicon Mac**. It is not a hosted website or a Windows release.

Install Python 3.13 and FFmpeg if needed, then:

```sh
git clone https://github.com/slyapustin/phonon-speech-desk.git
cd phonon-speech-desk
brew install python@3.13 ffmpeg
./setup.sh
./make_sample.sh
./run.sh
```

The first launch downloads the model. Subsequent transcription stays on your Mac. No API key is required. For a private repository, your GitHub account needs access before cloning.

## Try it

Open **http://127.0.0.1:8765** in regular Chrome. Wait for “Local engine ready”, then **Start recording** with **Live transcript while you speak** enabled. Provisional text appears while you talk; phrases finalize after pauses or when you stop. Turn the checkbox off for record-then-transcribe mode. Safari has not been validated.

For sample audio, choose a clip in **Sample library**, press the audio player's play button to listen, and choose **Transcribe this audio** to run recognition. You can seek, change playback speed through the player's menu, or **Save audio**. New microphone recordings and uploaded files also appear in this player. They remain in browser memory until replaced or the page reloads.

For microphone input, allow microphone access for this site in your browser and for the browser in macOS System Settings → Privacy & Security → Microphone. If an embedded browser denies access, open the URL in regular Chrome or Safari. Actual microphone capture requires your permission; the sample and file uploads do not.

Stop with Ctrl-C in the server terminal. To choose another port: `PORT=8766 ./run.sh`.

## Longer samples

All three project-briefing samples use the same original text and the Mac's synthetic Samantha voice. They are controlled test fixtures, not recordings of real rooms or calls. Open **Read the reference text** to compare the expected wording.

| Sample | Length | Treatment |
| --- | ---: | --- |
| Short introduction | 10.4 s | Original clean sample |
| Project briefing — clean | 107.9 s | Clean synthetic speech |
| Project briefing — room noise | 107.9 s | Fixed-seed low-pass noise, 12 dB SNR |
| Project briefing — muffled call | 108.0 s | 300–2800 Hz filtering, 8 kHz intermediate audio, 75 ms echo and 8 dB SNR noise |

The noisy briefing took 1.31 s and 1.02 s in two local runs. The muffled version took 1.58 s, but lost a passage and misrecognized several words: it deliberately exposes recognition weaknesses. Compare the transcript to the reference instead of treating speed as a quality score. Regenerate all fixtures with `./make_sample.sh`; the generation code and reference text are included.

## Live transcription

The browser uses an AudioWorklet to send 50 ms blocks of 16 kHz mono float32 PCM over a same-origin WebSocket at `/api/live`. The server uses Fermion 0.2.11's `LiveSession` implementation: it re-decodes the current phrase around twice per second, finalizes after about 0.7 seconds of quiet, and caps each phrase at 30 seconds. Partials can change; this is rolling recognition, not a guarantee that the earliest words are final.

GPU work stays on the same single worker as file transcription. One recording holds the engine exclusively. The browser preserves a separate MediaRecorder recording for playback and optional full-file reprocessing. Live results have no word timestamps; use **Transcribe this audio** after stopping to obtain them. The UI's **Live decode work** is cumulative inference across partial/final updates, not latency or elapsed recording time. Live mode uses more inference work than one-shot transcription.

The model now receives a warmup decode during startup. A paced WebSocket smoke test on the M1 Pro produced its first partial at **0.42 s**, 21 partial updates, a finalized phrase at 10.79 s and completion at 11.43 s (10.42 s speech plus 1 s appended silence). The final words matched the reference, apart from punctuation. These measurements exercise the live server with synthetic audio; microphone/browser timing can differ.

```sh
.venv/bin/python stream_smoke.py
```

This saves the full update sequence to `test-results/live-stream.json`. The WebSocket protocol is: send `{ "type": "start", "sample_rate": 16000, "hotwords": [] }`, wait for `ready`, send little-endian float32 binary blocks of at most 800 samples, then send `{ "type": "stop" }`. Responses are `partial`, `final`, `complete`, or `error`. `final_text` carries all committed text and a partial's `text` replaces the current provisional phrase.

## What the research means

[Fermion's paper](https://www.fermionresearch.com/research/phonon-2/) reports a 164 MB model download and 5.21% average word error across seven English datasets. Its published 174× realtime result is on an **M5 MacBook Air**, with model loading excluded. These are vendor measurements, not a speed guarantee for this machine.

The small download is not the working-memory footprint: the Apple silicon fast path expands the encoder into dense 16-bit weights and executes on the GPU through MLX. Keeping one model instance alive is therefore central to this POC's design. Phonon-2 is an English model; it is not the right choice for testing Polish or Russian recognition.

[Official speech documentation](https://www.fermionresearch.com/docs/speech/) describes local file transcription, hotword biasing and word timings. Long inputs are split at pauses into roughly 25–35-second windows. This app uses the Python `fermion.load_speech` API directly and adds FFmpeg conversion for browser recordings, MP3 and M4A.

## Measured on this Mac

The current setup is verified with **Python 3.13.16**: all 14 backend tests pass, dependency checks pass, and the 107.9-second clean sample transcribed locally in 1.31 seconds (conversion and inference, excluding model startup).

The initial measurements below were verified on **Apple M1 Pro, 16 GB RAM, macOS 27.0.1, Python 3.11.17**, with `fermion-research 0.2.11`, MLX 0.32.3 and the `tdt16,dense16` fast paths. No CPU fallback was used.

The synthetic English sample is 10.424 seconds, generated with the built-in Samantha voice. Its output matched `samples/expected.txt` in the initial browser test and all three subsequent benchmark requests.

| Measurement | Observed |
| --- | ---: |
| Cached-model app startup, before live warmup was added | 8.75 s |
| First browser transcription, before live warmup was added | 5.07 s |
| Subsequent requests, total processing | 0.482 / 0.162 / 0.157 s |
| Subsequent requests, speed | 21.6× / 64.5× / 66.5× realtime |
| Actual microphone recording in regular Chrome | 13.9 s audio / 0.55 s processing (25.2×) |

Processing includes conversion and inference, excludes HTTP upload and model loading. Short repeated synthetic speech is a smoke benchmark, not a real-world accuracy evaluation or an hour-long throughput test. New audio lengths can incur additional first-use costs.

Run your own comparison:

```sh
.venv/bin/python benchmark.py samples/demo.wav
.venv/bin/python benchmark.py /path/to/recording.m4a --runs 3
```

Detailed results are written to `test-results/benchmark.json`. File transcription's timing-data download includes the original model output, word/segment timestamps, conversion/decode/processing timings, and separately the current edited text.

## Install from scratch

Requirements: Apple silicon Mac with Metal access, Python 3.13, FFmpeg, and internet for installation/model download. `requirements.txt` pins the complete tested environment; it includes upstream dependencies beyond the 164 MB model. Older macOS/Python combinations have not been validated.

```sh
brew install python@3.13 ffmpeg  # only if missing
./setup.sh
./make_sample.sh
./run.sh
```

`setup.sh` uses `python3.13`; set `PYTHON_BIN` if your Python 3.13 executable has another path. An existing virtual environment made with a different Python must be renamed before rerunning setup:

```sh
mv .venv .venv.previous
./setup.sh
```

This preserves the old environment and leaves your model cache intact. The first launch downloads and verifies the official model. Caches live under this project's `.cache/`. After installation and model caching, transcription runs locally without an API key or cloud inference. `check_engine.py` downloads/loads the model and prints the actual backend and GPU.

## Scope and data handling

- English, one recording/request at a time; maximum 32 MiB and 10 minutes.
- WAV, MP3, M4A, FLAC, OGG, AIFF and WebM through local FFmpeg.
- Up to 25 comma-separated hotwords; they bias recognition, not guaranteed spelling.
- Temporary uploaded/converted files are removed after each request. No audio/transcript database, history or browser local storage. Results stay in the current page until you export or reload.
- The server binds only to `127.0.0.1`, rejects foreign browser origins and arbitrary hostnames, and has no remote fonts, analytics or CDN dependencies. It is a local single-user POC, not a publicly deployable service.
- No speaker diarization, translation, system-audio capture or global dictation shortcut. Live microphone text is supported in the UI; the upstream `phonon listen` command offers a separate terminal interface.

## Verification and files

```sh
.venv/bin/python -m pytest -q
node --check static/app.js
```

Fourteen backend tests cover invalid and empty audio, size/duration/hotword limits, loading/busy responses, foreign-origin rejection, per-request hotwords, temporary-file cleanup, sample metadata/HTTP range playback and live-session validation/exclusivity/cleanup. GPU inference is verified separately through the running app, benchmark and paced live-stream smoke test.

The browser sample flow, sample playback, and real microphone recording were verified. Live browser capture was also checked in regular Chrome: partial text appeared during a 9.5-second recording, Stop finalized the transcript, and the recording became available in the player. The automated browser session returned microphone denial despite granted site permission; opening the same local URL in the user's regular Chrome profile resolved recording without changing macOS permissions. Desktop layout was visually checked. Mobile layout and Safari recording have not been tested.

- `app.py`: FastAPI, persistent model, one inference worker, conversion and validation.
- `static/`: browser recording, upload, transcript editing, export and timing display.
- `run.sh`, `setup.sh`, `make_sample.sh`: launch, install and generate test speech.
- `benchmark.py`: repeatable local API measurements.
- `build_samples.py`: repeatable generation of the longer clean/noisy/muffled fixtures.
- `streaming.py`, `static/live.js`, `static/pcm-worklet.js`: live decoding and browser capture.
- `stream_smoke.py`: paced end-to-end WebSocket verification.

## Attribution

Phonon-2 is by Fermion Research, derived from NVIDIA's Parakeet TDT 0.6B v3. License and upstream notice copies are included in `licenses/`. Model weights are [CC BY 4.0](https://huggingface.co/FermionResearch/Phonon-2); upstream runtime code is Apache 2.0. Weights are downloaded unmodified by the official runtime, not checked into this project. Upstream LICENSE and NOTICE files remain in the model cache. This is an independent proof of concept, not an official Fermion product.
