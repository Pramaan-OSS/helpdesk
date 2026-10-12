<template>
  <SettingsLayoutBase title="Sign-in" description="Let people sign in with a connected identity account.">
    <template #content><div class="space-y-4 py-4">
      <div class="flex items-center gap-2">
        <Switch v-model="enabled" />
        <span class="text-sm text-ink-gray-6">Allow single sign-in</span>
      </div>
      <template v-if="enabled">
        <FormControl v-model="providerKey" label="Sign-in account key" placeholder="example" description="The connected sign-in account's key from the capability catalogue." />
        <FormControl v-model="clientId" label="Client id" placeholder="your-app-client-id" />
        <FormControl v-model="authorizeUrl" label="Authorization endpoint" placeholder="https://accounts.example.com/o/oauth2/v2/auth" />
        <FormControl v-model="scope" label="Scope" placeholder="openid email profile" />
        <div class="flex items-center gap-2">
          <Switch v-model="usePkce" />
          <span class="text-sm text-ink-gray-6">Use PKCE</span>
        </div>
      </template>
      <p class="text-sm text-ink-gray-6">People can only sign in when their verified email matches an account you invited. Password sign-in stays available.</p>
      <Button :loading="busy" :disabled="!changed" @click="save">Save</Button>
      <p v-if="notice" role="status" class="text-sm">{{ notice }}</p>
    </div></template>
  </SettingsLayoutBase>
</template>
<script setup lang="ts">
import { actionError } from "@/composables/pramaan";
import { computed, ref, onMounted } from "vue";
import { call, Button, FormControl, Switch } from "frappe-ui";
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
const enabled = ref(false); const providerKey = ref(""); const clientId = ref("");
const authorizeUrl = ref(""); const scope = ref("openid email profile"); const usePkce = ref(true);
const saved = ref(false); const notice = ref(""); const busy = ref(false);
const initial = ref({} as Record<string, unknown>);
const changed = computed(() => {
  return ["enabled", "providerKey", "clientId", "authorizeUrl", "scope", "usePkce"]
    .some((key) => current()[key] !== initial.value[key]);
});
function current() {
  return { enabled: enabled.value, providerKey: providerKey.value, clientId: clientId.value,
           authorizeUrl: authorizeUrl.value, scope: scope.value, usePkce: usePkce.value };
}
onMounted(async () => {
  try {
    const data = await call("helpdesk.api.settings.signin.get_data");
    enabled.value = data.enabled; saved.value = data.enabled;
    providerKey.value = data.providerKey; clientId.value = data.clientId;
    authorizeUrl.value = data.authorizeUrl; scope.value = data.scope; usePkce.value = data.usePkce;
    initial.value = current();
  } catch (error) { notice.value = actionError(error, "Could not load sign-in settings."); }
});
async function save() {
  busy.value = true;
  try {
    await call("helpdesk.api.settings.signin.update_data", {
      enabled: enabled.value, providerKey: providerKey.value, clientId: clientId.value,
      authorizeUrl: authorizeUrl.value, scope: scope.value, usePkce: usePkce.value,
    });
    saved.value = enabled.value;
    initial.value = current();
    notice.value = "Sign-in settings saved.";
  } catch (error) { notice.value = actionError(error, "Could not save. Check the fields and try again."); }
  finally { busy.value = false; }
}
</script>
