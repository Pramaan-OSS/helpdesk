<template>
  <div class="p-6">
    <h1 class="text-xl font-semibold">Callbacks</h1>
    <p class="my-3 text-sm text-ink-gray-6">Manual notes stay on the ticket. This list shows callbacks requested through Pramaan.</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="calls.error" role="alert">Could not load callbacks.</p>
    <div v-for="row in calls.data || []" :key="row.name" class="border-b py-3">
      <div class="flex items-center justify-between">
        <RouterLink :to="`/tickets/${row.ticket}`">Ticket {{ row.ticket }}</RouterLink>
        <span>{{ row.state }}</span>
        <Button @click="refresh(row.name)">Check status</Button>
      </div>
      <OutcomeReview v-if="row.state === 'Ended' && row.recording_enabled" class="mt-3" kind="Call" :ticket="row.ticket" :call-name="row.name" />
    </div>
    <p v-if="calls.data && !calls.data.length">No callbacks yet.</p>
  </div>
</template>
<script setup lang="ts">
import { ref } from "vue";
import { actionError } from "@/composables/pramaan";
import OutcomeReview from "@/components/OutcomeReview.vue";
import { createResource, call, Button } from "frappe-ui";
const calls = createResource({ url: "helpdesk.api.capabilities.list_calls", auto: true });
const error = ref("");
async function refresh(name: string) {
  error.value = "";
  try {
    await call("helpdesk.api.capabilities.callback_status", { name });
    await calls.reload();
  } catch (failure) { error.value = actionError(failure, "Could not check this call. Check its status before another action."); }
}
</script>
