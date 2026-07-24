"use strict";

class MomoPcmRecorderProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]?.[0];
    if (input?.length) {
      const samples = input.slice();
      this.port.postMessage(samples.buffer, [samples.buffer]);
    }
    return true;
  }
}

registerProcessor("momo-pcm-recorder", MomoPcmRecorderProcessor);
