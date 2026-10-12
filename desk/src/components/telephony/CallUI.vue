<template>
  <div v-if="isCallingEnabled" class="relative">
    <Tooltip :text="__('Browser calling')">
      <Button aria-label="Browser calling" :variant="phoneActive ? 'subtle' : 'ghost'" @click="togglePanel">
        <template #icon>
          <PhoneIcon class="size-4" />
        </template>
      </Button>
    </Tooltip>
    <div
      v-if="phoneActive"
      class="absolute end-0 top-10 z-50 w-72 rounded-6 border border-outline-gray-2 bg-surface-white p-4 shadow-lg"
    >
      <div class="mb-2 flex items-center justify-between">
        <span class="text-base font-medium text-ink-gray-9">{{ __("Phone") }}</span>
        <Badge :label="stateLabel" :theme="stateBadgeTheme" />
      </div>
      <p v-if="!configured" role="status" class="mb-2 text-sm">{{ missingKeyMessage }}</p>
      <p v-if="phone.micError.value" class="mb-2 text-p-sm text-ink-red-5">
        {{ __(phone.micError.value) }}
      </p>
      <p v-else-if="phone.stateReason.value" class="mb-2 text-p-sm text-ink-gray-6">
        {{ __(reasonText) }}
      </p>
      <div v-if="phone.incoming.value" class="mb-3 rounded-4 bg-surface-gray-2 p-3">
        <p class="text-p-base text-ink-gray-9">{{ phone.incoming.value.from }}</p>
        <p class="mb-2 text-p-sm text-ink-gray-6">{{ __("Incoming call") }}</p>
        <div class="flex gap-2">
          <Button variant="solid" :label="__('Accept')" @click="phone.accept()" />
          <Button :label="__('Reject')" @click="phone.reject()" />
        </div>
      </div>
      <div v-if="onCall" class="mb-3 rounded-4 bg-surface-gray-2 p-3">
        <p class="text-p-base text-ink-gray-9">{{ __("Call in progress") }}</p>
        <div class="mt-2 flex gap-2">
          <Button
            :label="phone.muted.value ? __('Unmute') : __('Mute')"
            @click="phone.toggleMute()"
          />
          <Button variant="solid" theme="red" :label="__('Hang up')" @click="phone.hangup()" />
        </div>
      </div>
      <template v-if="!onCall">
        <FormControl v-model="dialNumber" :label="__('Number')" placeholder="+441234567890" />
        <Button
          class="mt-2 w-full"
          variant="solid"
          :label="__('Call')"
          :disabled="!configured || !dialNumber"
          @click="dialOut()"
        />
      </template>
      <p class="mt-2 text-p-xs text-ink-gray-6">
        {{ __("Audio connects through your session; the call lands in the call log.") }}
      </p>
    </div>
  </div>
</template>
<script setup lang="ts">
import { usePramaanAvailability, actionError } from "@/composables/pramaan";
const { configured, missingKeyMessage } = usePramaanAvailability();
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { Badge, Button, FormControl, Tooltip } from "frappe-ui";
import { PhoneIcon } from "@/components/icons/";
import { useBrowserPhone } from "@/composables/browserPhone";
import { useTelephonyStore } from "@/stores/telephony";
import { __ } from "@/translation";

const telephony = useTelephonyStore();
const { isCallingEnabled } = storeToRefs(telephony);

const phone = useBrowserPhone();
const phoneActive = ref(false);
const dialNumber = ref("");
const dialing = ref(false);

const onCall = computed(() => dialing.value || phone.activeCallRef.value != null);

const stateLabel = computed(() => {
  switch (phone.state.value) {
    case "ready": return __("Ready");
    case "connecting": return __("Connecting");
    case "reconnecting": return __("Reconnecting");
    default: return __("Off");
  }
});
const stateBadgeTheme = computed(() => (phone.state.value === "ready" ? "green" : "gray"));
const reasonText = computed(() => {
  switch (phone.stateReason.value) {
    case "credential": return "The phone session expired. Reopen the phone.";
    case "origin": return "This page's address is not allowed for calling.";
    case "session_ended": return "The phone session ended. Reopen the phone.";
    default: return "Reconnecting to the call.";
  }
});

async function togglePanel() {
  phoneActive.value = !phoneActive.value;
  if (configured.value && phoneActive.value && phone.state.value !== "ready") {
    telephony.setMakeCall(dialFromTicket);
    await phone.connect();
  }
}

async function dialFromTicket(params: { number: string; doctype: string; docname: string }) {
  phoneActive.value = true;
  if (phone.state.value !== "ready") await phone.connect();
  dialNumber.value = params.number;
  await dialOut(params.docname);
}

async function dialOut(ticket?: string) {
  const docname = ticket ?? (telephony.linkDoc.docname as string | undefined);
  if (!dialNumber.value) return;
  dialing.value = true;
  try {
    await phone.dial(dialNumber.value, docname ?? "");
    dialNumber.value = "";
  } finally {
    dialing.value = false;
  }
}

onMounted(() => {
  telephony.fetchCallIntegrationStatus();
});

onBeforeUnmount(() => {
  phone.disconnect();
});
</script>
