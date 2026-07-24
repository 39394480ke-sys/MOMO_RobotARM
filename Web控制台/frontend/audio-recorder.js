(function initMomoAudio(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.MomoAudio = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : window, function createMomoAudio() {
  "use strict";

  function downsampleFloat32(input, inputRate, outputRate) {
    if (!(input instanceof Float32Array) || inputRate <= 0 || outputRate <= 0 || outputRate > inputRate) {
      throw new Error("不支持的音频采样率。");
    }
    if (inputRate === outputRate) return new Float32Array(input);
    const ratio = inputRate / outputRate;
    const output = new Float32Array(Math.floor(input.length / ratio));
    for (let index = 0; index < output.length; index += 1) {
      const start = Math.floor(index * ratio);
      const end = Math.max(start + 1, Math.floor((index + 1) * ratio));
      let total = 0;
      for (let sourceIndex = start; sourceIndex < end && sourceIndex < input.length; sourceIndex += 1) {
        total += input[sourceIndex];
      }
      output[index] = total / Math.max(1, Math.min(end, input.length) - start);
    }
    return output;
  }

  function encodePcm16Wav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    writeAscii(view, 0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeAscii(view, 8, "WAVE");
    writeAscii(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeAscii(view, 36, "data");
    view.setUint32(40, samples.length * 2, true);
    for (let index = 0; index < samples.length; index += 1) {
      const value = Math.max(-1, Math.min(1, samples[index]));
      view.setInt16(44 + index * 2, value < 0 ? value * 32768 : value * 32767, true);
    }
    return buffer;
  }

  function writeAscii(view, offset, text) {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  }

  function insertTranscript(value, selectionStart, selectionEnd, transcript) {
    const start = Number.isInteger(selectionStart) ? selectionStart : String(value).length;
    const end = Number.isInteger(selectionEnd) ? selectionEnd : start;
    const text = String(transcript || "").trim();
    return {
      value: String(value).slice(0, start) + text + String(value).slice(end),
      selectionStart: start + text.length,
    };
  }

  function joinChunks(chunks) {
    const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
    const joined = new Float32Array(length);
    let offset = 0;
    chunks.forEach((chunk) => {
      joined.set(chunk, offset);
      offset += chunk.length;
    });
    return joined;
  }

  class VoiceRecorder {
    constructor(options = {}) {
      this.workletUrl = options.workletUrl || "/static/audio-recorder-worklet.js";
      this.maxDurationMs = Number(options.maxDurationMs || 20000);
      this.onTick = options.onTick || (() => {});
      this.onAutoStop = options.onAutoStop || (() => {});
      this.state = "idle";
      this.chunks = [];
      this.startedAt = 0;
      this.timer = null;
      this.stream = null;
      this.context = null;
      this.source = null;
      this.node = null;
      this.silentGain = null;
    }

    async start() {
      if (this.state !== "idle") throw new Error("录音已经开始。");
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
        throw new Error("当前浏览器不支持网页录音。");
      }
      this.state = "starting";
      try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        this.context = new AudioContextClass();
        await this.context.resume();
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
          video: false,
        });
        await this.context.audioWorklet.addModule(this.workletUrl);
        this.chunks = [];
        this.source = this.context.createMediaStreamSource(this.stream);
        this.node = new AudioWorkletNode(this.context, "momo-pcm-recorder");
        this.node.port.onmessage = (event) => this.chunks.push(new Float32Array(event.data));
        this.silentGain = this.context.createGain();
        this.silentGain.gain.value = 0;
        this.source.connect(this.node);
        this.node.connect(this.silentGain);
        this.silentGain.connect(this.context.destination);
        this.startedAt = performance.now();
        this.state = "recording";
        this.timer = window.setInterval(() => this._tick(), 200);
        this._tick();
      } catch (error) {
        await this._cleanup();
        throw error;
      }
    }

    async stop() {
      if (this.state !== "recording") throw new Error("当前没有正在进行的录音。");
      this.state = "stopping";
      const inputRate = this.context.sampleRate;
      const samples = joinChunks(this.chunks);
      await this._cleanup();
      const pcm16k = downsampleFloat32(samples, inputRate, 16000);
      return new Blob([encodePcm16Wav(pcm16k, 16000)], { type: "audio/wav" });
    }

    async cancel() {
      await this._cleanup();
    }

    async _cleanup() {
      if (this.timer !== null) {
        window.clearInterval(this.timer);
        this.timer = null;
      }
      if (this.node) this.node.disconnect();
      if (this.source) this.source.disconnect();
      if (this.silentGain) this.silentGain.disconnect();
      if (this.stream) this.stream.getTracks().forEach((track) => track.stop());
      if (this.context && this.context.state !== "closed") await this.context.close();
      this.stream = null;
      this.context = null;
      this.source = null;
      this.node = null;
      this.silentGain = null;
      this.chunks = [];
      this.startedAt = 0;
      this.state = "idle";
    }

    _tick() {
      if (this.state !== "recording") return;
      const elapsedMs = performance.now() - this.startedAt;
      this.onTick(Math.min(elapsedMs, this.maxDurationMs));
      if (elapsedMs >= this.maxDurationMs) {
        this.stop().then(this.onAutoStop).catch((error) => this.onAutoStop(null, error));
      }
    }
  }

  return { VoiceRecorder, downsampleFloat32, encodePcm16Wav, insertTranscript };
});
