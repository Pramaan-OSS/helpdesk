<template>
  <SettingsLayoutBase title="Calling" description="Call from the browser and reach your own phone.">
    <template #content><div class="space-y-4 py-4">
      <p class="text-sm text-ink-gray-6">The browser phone opens from the header. Callbacks connect your phone to the customer's phone; they do not use your computer's microphone.</p>
      <FormControl v-model="personal" label="Your callback phone" placeholder="+441234567890" />
      <Button :loading="busy" @click="savePersonal">Save your phone</Button>
      <template v-if="auth.isAdmin"><FormControl v-model="calling" label="Owned Pramaan calling number" placeholder="+441234567890" /><Button :loading="busy" @click="saveCalling">Save calling number</Button></template>
      <p v-if="notice" role="status" class="text-sm">{{ notice }}</p>
    </div></template>
  </SettingsLayoutBase>
</template>
<script setup lang="ts">
import { ref, onMounted } from "vue";
import { call, Button, FormControl } from "frappe-ui";
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import { useAuthStore } from "@/stores/auth";
const auth = useAuthStore(); const personal = ref(""); const calling = ref(""); const notice = ref(""); const busy = ref(false);
onMounted(async () => { try { const data = await call("helpdesk.api.capabilities.callback_settings"); personal.value = data.personal; calling.value = data.calling; } catch { notice.value = "Could not load calling settings."; } });
async function savePersonal() { await save("configure_callback", personal.value); }
async function saveCalling() { await save("configure_calling_number", calling.value); }
async function save(method: string, number: string) { busy.value = true; try { await call("helpdesk.api.capabilities." + method, { number }); notice.value = "Phone saved."; } catch { notice.value = "Could not save. Enter a phone number with its country code."; } finally { busy.value = false; } }
</script>
