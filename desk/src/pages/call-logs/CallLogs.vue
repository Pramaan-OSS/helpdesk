<template><div class="p-6"><h1 class="text-xl font-semibold">Callbacks</h1><p class="my-3 text-sm text-ink-gray-6">Manual notes stay on the ticket. This list shows callbacks requested through Pramaan.</p><p v-if="calls.error" role="alert">Could not load callbacks.</p><div v-for="row in calls.data || []" :key="row.name" class="flex items-center justify-between border-b py-3"><RouterLink :to="`/tickets/${row.ticket}`">Ticket {{ row.ticket }}</RouterLink><span>{{ row.state }}</span><Button @click="refresh(row.name)">Check status</Button></div><p v-if="calls.data && !calls.data.length">No callbacks yet.</p></div></template>
<script setup lang="ts">
import { createResource, call, Button } from "frappe-ui";
const calls = createResource({url:"helpdesk.api.capabilities.list_calls",auto:true});
async function refresh(name:string){try {await call("helpdesk.api.capabilities.callback_status",{name}); await calls.reload();}catch {}}
</script>
