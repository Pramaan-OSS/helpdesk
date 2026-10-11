<template><div class="rounded border p-3 text-sm">Historical call · {{ activity.status || "Recorded locally" }}<p class="text-ink-gray-5">Use Callbacks to check new Pramaan calls.</p></div></template>
<script setup lang="ts">defineProps<{activity:any}>();</script>
