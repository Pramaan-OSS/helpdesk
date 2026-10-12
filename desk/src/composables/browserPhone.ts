// Owns the browser phone: the app server mints the session, this composable
// captures the microphone, streams 8 kHz frames to Pramaan's relay and plays
// what comes back. Accept, reject, dial and hangup are server actions.
import { actionError } from "@/composables/pramaan";
import { ref } from "vue";
import { createResource } from "frappe-ui";
import {
  connectBrowserPhone,
  type BrowserPhone,
  type BrowserPhoneState,
  type BrowserVoiceEvent,
} from "@/browser-phone/pramaanBrowser";

const SAMPLE_RATE = 8000;

export interface IncomingCall {
  callRef: string;
  from: string;
}

const state = ref<"off" | BrowserPhoneState>("off");
const stateReason = ref<string | undefined>(undefined);
const muted = ref(false);
const incoming = ref<IncomingCall | null>(null);
const activeCallRef = ref<string | null>(null);
const micError = ref("");

let phone: BrowserPhone | null = null;
let audioContext: AudioContext | null = null;
let micStream: MediaStream | null = null;
let workletNode: AudioWorkletNode | null = null;
let playQueue: Float32Array[] = [];
let playScheduledUntil = 0;

const sessionResource = createResource({
  url: "helpdesk.api.calling.session",
  method: "POST",
  makeParams: () => ({}),
});

function play(samples: Float32Array) {
  if (!audioContext) return;
  playQueue.push(samples);
  const total = playQueue.reduce((sum, chunk) => sum + chunk.length, 0);
  if (total < SAMPLE_RATE / 5) return; // play in ~200 ms batches
  const buffer = audioContext.createBuffer(1, total, SAMPLE_RATE);
  const channel = buffer.getChannelData(0);
  let offset = 0;
  for (const chunk of playQueue) {
    channel.set(chunk, offset);
    offset += chunk.length;
  }
  playQueue = [];
  const source = audioContext.createBufferSource();
  source.buffer = buffer;
  source.connect(audioContext.destination);
  const now = audioContext.currentTime;
  const startAt = Math.max(now, playScheduledUntil);
  source.start(startAt);
  playScheduledUntil = startAt + buffer.duration;
}

async function captureMicrophone() {
  micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioContext = audioContext ?? new AudioContext();
  if (audioContext.state === "suspended") await audioContext.resume();
  const workletSource = `
    class ResampleTo8k extends AudioWorkletProcessor {
      process(inputs) {
        const input = inputs[0] && inputs[0][0];
        if (!input || !input.length) return true;
        const ratio = sampleRate / ${SAMPLE_RATE};
        const out = new Float32Array(Math.max(1, Math.floor(input.length / ratio)));
        for (let i = 0; i < out.length; i++) {
          const at = i * ratio;
          const low = Math.floor(at);
          const high = Math.min(input.length - 1, low + 1);
          out[i] = input[low] + (input[high] - input[low]) * (at - low);
        }
        this.port.postMessage(out);
        return true;
      }
    }
    registerProcessor("resample-to-8k", ResampleTo8k);
  `;
  const workletUrl = URL.createObjectURL(new Blob([workletSource], { type: "application/javascript" }));
  try {
    await audioContext.audioWorklet.addModule(workletUrl);
  } finally {
    URL.revokeObjectURL(workletUrl);
  }
  workletNode = new AudioWorkletNode(audioContext, "resample-to-8k");
  workletNode.port.onmessage = (event) => phone?.sendAudio(event.data as Float32Array);
  const source = audioContext.createMediaStreamSource(micStream);
  source.connect(workletNode);
  // The worklet is a sink: no connection to the destination (no echo).
}

function stopMedia() {
  workletNode?.disconnect();
  workletNode = null;
  micStream?.getTracks().forEach((track) => track.stop());
  micStream = null;
  playQueue = [];
  playScheduledUntil = 0;
}

function handleEvent(event: BrowserVoiceEvent) {
  if (event.type === "call.ringing" && event.callRef) {
    incoming.value = { callRef: event.callRef, from: event.from ?? "" };
  } else if (event.type === "call.connected") {
    incoming.value = null;
    activeCallRef.value = event.callRef ?? activeCallRef.value;
  } else if (event.type === "call.ended" || event.type === "call.rejected" || event.type === "call.failed") {
    if (activeCallRef.value && event.callRef === activeCallRef.value) activeCallRef.value = null;
    if (incoming.value && event.callRef === incoming.value.callRef) incoming.value = null;
  }
}

export function useBrowserPhone() {
  async function connect() {
    if (phone && state.value !== "closed") return;
    state.value = "connecting";
    let session;
    try { session = await sessionResource.fetch(); }
    catch (error) {
      micError.value = actionError(error, "Could not open the browser phone. Try again later.");
      state.value = "off";
      return;
    }
    micError.value = "";
    try {
      await captureMicrophone();
    } catch {
      micError.value = "Microphone permission was denied. Browser calling needs it.";
      state.value = "closed";
      return;
    }
    phone = connectBrowserPhone({
      connectUrl: session.connectUrl,
      credential: session.credential,
      onEvent: handleEvent,
      onAudio: play,
      onState: (value, reason) => {
        state.value = value;
        stateReason.value = reason;
        if (value === "closed") stopMedia();
      },
    });
  }

  function setCredential(credential: string) {
    phone?.setCredential(credential);
  }

  async function toggleMute() {
    muted.value = !muted.value;
    phone?.mute(muted.value);
    micStream?.getAudioTracks().forEach((track) => (track.enabled = !muted.value));
  }

  async function accept(ticket?: string) {
    const call = incoming.value;
    if (!call) return;
    incoming.value = null;
    await createResource({
      url: "helpdesk.api.calling.accept_call",
      method: "POST",
      params: { call_ref: call.callRef, request_id: crypto.randomUUID(), ticket: ticket ?? "" },
    }).fetch();
    activeCallRef.value = call.callRef;
  }

  async function reject() {
    const call = incoming.value;
    if (!call) return;
    incoming.value = null;
    await createResource({
      url: "helpdesk.api.calling.reject_call",
      method: "POST",
      params: { call_ref: call.callRef, request_id: crypto.randomUUID() },
    }).fetch();
  }

  async function dial(number: string, ticket: string) {
    await createResource({
      url: "helpdesk.api.calling.start_call",
      method: "POST",
      params: { ticket, number, request_id: crypto.randomUUID() },
    }).fetch();
    // The relay's call.dialing event carries the ref; clear any stale one.
    activeCallRef.value = null;
  }

  async function hangup() {
    const callRef = activeCallRef.value;
    if (!callRef) return;
    await createResource({
      url: "helpdesk.api.calling.hangup_by_ref",
      method: "POST",
      params: { call_ref: callRef },
    }).fetch();
    activeCallRef.value = null;
  }

  function disconnect() {
    phone?.close();
    phone = null;
    stopMedia();
    state.value = "off";
  }

  return {
    state, stateReason, muted, incoming, activeCallRef, micError,
    connect, setCredential, toggleMute, accept, reject, dial, hangup, disconnect,
  };
}
