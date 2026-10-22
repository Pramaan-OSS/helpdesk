<template>
  <SettingsLayoutBase title="Email Accounts" description="Outgoing mail uses the default sender. Connect an owned mailbox to receive incoming email.">
    <template #content>
      <div class="space-y-5 py-4"><p v-if="!configured" role="status">{{ missingKeyMessage }}</p>
        <p class="text-sm text-ink-gray-6">Automatic acknowledgements and feedback emails are supported when enabled in Email Notifications. Replies preserve their email thread, including edited recipients and subject.</p>
        <div v-for="account in accounts.data || []" :key="account.name" class="rounded border p-3">
          <strong>{{ account.name }}</strong><p class="text-sm">{{ account.email_id }}</p>
        </div>
        <form class="space-y-3" @submit.prevent="connect">
          <FormControl v-model="address" type="email" label="Owned mailbox address" placeholder="support@your-domain.com" required />
          <FormControl v-model="name" label="Mailbox name" placeholder="Support" />
          <Button :disabled="!configured" type="submit" variant="solid" :loading="busy">Connect mailbox</Button>
        </form>
        <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
        <p v-if="success" role="status" class="text-sm text-green-700">{{ success }}</p>
        <details class="border-t pt-4">
          <summary class="cursor-pointer text-sm">Need a new inbox?</summary>
          <p class="my-3 text-sm text-ink-gray-6">A new inbox starts a monthly rental on your Pramaan account. Creating it does not cancel existing inboxes.</p>
          <Button :disabled="!configured" :loading="busy" @click="provision">Create rented inbox</Button>
        </details>
      </div>
    </template>
  </SettingsLayoutBase>
</template>
<script setup lang="ts">
import { usePramaanAvailability, actionError } from "@/composables/pramaan";
const { configured, missingKeyMessage } = usePramaanAvailability();
import { ref } from "vue";
import { Button, FormControl, createResource, call } from "frappe-ui";
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
const accounts = createResource({ url: "helpdesk.api.settings.email.list_mailboxes", auto: true });
const address = ref(""); const name = ref(""); const busy = ref(false); const error = ref(""); const success = ref("");
const rentalRequest = ref(crypto.randomUUID());
async function connect() {
  busy.value = true; error.value = ""; success.value = "";
  try {
    await call("helpdesk.api.settings.email.create_email_account", { data: { email_id: address.value, email_account_name: name.value } });
    await accounts.reload(); success.value = "Mailbox connected."; address.value = "";
  } catch (err) { error.value = actionError(err, "Could not connect this mailbox. Check that it belongs to your Pramaan account."); }
  finally { busy.value = false; }
}
async function provision() {
  busy.value = true; error.value = "";
  try {
    const result = await call("helpdesk.api.settings.email.provision_mailbox", { display_name: name.value || "Support", request_id: rentalRequest.value });
    address.value = result.email; success.value = "Inbox created. Connect it above to use it here.";
    rentalRequest.value = crypto.randomUUID();
  } catch (err) { error.value = actionError(err, "Creation was not confirmed. Check your Pramaan inboxes before trying again."); }
  finally { busy.value = false; }
}
</script>
