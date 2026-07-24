"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  VoiceRecorder,
  capPcmDuration,
  downsampleFloat32,
  encodePcm16Wav,
  insertTranscript,
} = require("../frontend/audio-recorder.js");

test("downsamples browser PCM to 16 kHz", () => {
  const source = new Float32Array(48000);
  source.fill(0.25);

  const output = downsampleFloat32(source, 48000, 16000);

  assert.equal(output.length, 16000);
  assert.ok(Math.abs(output[500] - 0.25) < 0.0001);
});

test("encodes mono 16-bit PCM with a valid WAV header", () => {
  const wav = encodePcm16Wav(new Float32Array([0, 0.5, -0.5]), 16000);
  const view = new DataView(wav);

  assert.equal(Buffer.from(wav, 0, 4).toString("ascii"), "RIFF");
  assert.equal(Buffer.from(wav, 8, 4).toString("ascii"), "WAVE");
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(view.getUint32(40, true), 6);
});

test("caps auto-stopped PCM at the backend 20 second limit", () => {
  const samples = new Float32Array(321000);

  const capped = capPcmDuration(samples, 16000, 20000);

  assert.equal(capped.length, 320000);
});

test("inserts transcript at the current selection without replacing other text", () => {
  const result = insertTranscript("请机械臂移动", 1, 4, "让底座");

  assert.deepEqual(result, { value: "请让底座移动", selectionStart: 4 });
});

test("creates and resumes AudioContext before awaiting microphone permission", async (t) => {
  const originalWindow = Object.getOwnPropertyDescriptor(global, "window");
  const originalNavigator = Object.getOwnPropertyDescriptor(global, "navigator");
  const originalPerformance = Object.getOwnPropertyDescriptor(global, "performance");
  const originalAudioWorkletNode = Object.getOwnPropertyDescriptor(global, "AudioWorkletNode");
  const events = [];
  const connectable = { connect() {}, disconnect() {} };
  const stream = { getTracks: () => [{ stop() {} }] };

  class MockAudioContext {
    constructor() {
      events.push("context");
      this.sampleRate = 48000;
      this.state = "running";
      this.destination = {};
      this.audioWorklet = { addModule: async () => events.push("worklet") };
    }
    async resume() {
      events.push("resume");
    }
    createMediaStreamSource() {
      return connectable;
    }
    createGain() {
      return { ...connectable, gain: { value: 1 } };
    }
    async close() {
      this.state = "closed";
    }
  }

  class MockAudioWorkletNode {
    constructor() {
      this.port = {};
    }
    connect() {}
    disconnect() {}
  }

  Object.defineProperty(global, "window", { configurable: true, writable: true, value: {
    AudioContext: MockAudioContext,
    AudioWorkletNode: MockAudioWorkletNode,
    setInterval: () => 1,
    clearInterval() {},
  } });
  Object.defineProperty(global, "AudioWorkletNode", { configurable: true, writable: true, value: MockAudioWorkletNode });
  Object.defineProperty(global, "navigator", { configurable: true, writable: true, value: {
    mediaDevices: {
      getUserMedia: async () => {
        events.push("getUserMedia");
        return stream;
      },
    },
  } });
  Object.defineProperty(global, "performance", { configurable: true, writable: true, value: { now: () => 0 } });
  t.after(() => {
    restoreGlobal("window", originalWindow);
    restoreGlobal("navigator", originalNavigator);
    restoreGlobal("performance", originalPerformance);
    restoreGlobal("AudioWorkletNode", originalAudioWorkletNode);
  });

  const recorder = new VoiceRecorder();
  await recorder.start();
  await recorder.cancel();

  assert.ok(events.indexOf("context") < events.indexOf("getUserMedia"));
  assert.ok(events.indexOf("resume") < events.indexOf("getUserMedia"));
});

function restoreGlobal(name, descriptor) {
  if (descriptor) Object.defineProperty(global, name, descriptor);
  else delete global[name];
}
