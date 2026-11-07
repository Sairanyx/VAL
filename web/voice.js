// Records one thing said to Val, and stops by itself when the speaker stops.
const NOISE_WINDOW = 400; // milliseconds used to learn how noisy the room is
const QUIET_TO_STOP = 1200; // milliseconds of quiet after speech that end the recording
const NOTHING_SAID = 7000; // give up if no speech starts by then
const LONGEST = 20000; // never record longer than this
const SPEECH_ABOVE_NOISE = 2.5;
const MIN_SPEECH_LEVEL = 0.015;

// Something the person can act on, rather than a program error.
export class MicProblem extends Error {}

async function openMic() {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new MicProblem(
      "The browser only allows the mic on a secure page. Start with ./start tablet and open its https address.",
    );
  }
  if (!window.MediaRecorder) throw new MicProblem("This browser can't record from the mic.");
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (error) {
    if (error.name === "NotAllowedError") {
      throw new MicProblem("The mic is blocked. Allow it in the browser's site settings, then try again.");
    }
    if (error.name === "NotFoundError") throw new MicProblem("No mic was found on this device.");
    throw error;
  }
}

// Returns { result, stop, cancel }. `result` gives the audio, or null if nothing was said or it was
// cancelled. `stop` sends what's been said so far.
export function recordSpeech({ onLevel }) {
  let finish = () => {};
  let abandoned = false;

  async function run() {
    const stream = await openMic();
    if (abandoned) {
      stream.getTracks().forEach((track) => track.stop());
      return null;
    }
    const audio = new AudioContext();
    await audio.resume();
    const analyser = audio.createAnalyser();
    analyser.fftSize = 1024;
    audio.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);

    const type = ["audio/webm;codecs=opus", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
    const recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const pieces = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size) pieces.push(event.data);
    };
    const stopped = new Promise((resolve) => {
      recorder.onstop = resolve;
    });
    recorder.start(250);

    const started = performance.now();
    let noise = 0;
    let noiseReadings = 0;
    let spoke = false;
    let lastSpeech = started;
    await new Promise((resolve) => {
      finish = resolve;
      const timer = setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        const level = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
        onLevel?.(Math.min(level * 8, 1));
        const now = performance.now();
        if (now - started < NOISE_WINDOW) {
          noise += level;
          noiseReadings += 1;
          return;
        }
        const room = noiseReadings ? noise / noiseReadings : 0;
        if (level > Math.max(room * SPEECH_ABOVE_NOISE, MIN_SPEECH_LEVEL)) {
          spoke = true;
          lastSpeech = now;
        }
        const quietLongEnough = spoke && now - lastSpeech > QUIET_TO_STOP;
        const nothing = !spoke && now - started > NOTHING_SAID;
        if (quietLongEnough || nothing || now - started > LONGEST) finish();
      }, 50);
      finish = () => {
        clearInterval(timer);
        resolve();
      };
    });

    recorder.stop();
    await stopped;
    stream.getTracks().forEach((track) => track.stop());
    await audio.close();
    if (abandoned || !pieces.length) return null;
    // A tap on stop counts as speech: trust the person over the level meter.
    return spoke || stoppedByHand ? new Blob(pieces, { type: recorder.mimeType }) : null;
  }

  let stoppedByHand = false;
  return {
    result: run(),
    stop() {
      stoppedByHand = true;
      finish();
    },
    cancel() {
      abandoned = true;
      finish();
    },
  };
}
