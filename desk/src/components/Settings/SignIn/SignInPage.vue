<template>
  <SettingsLayoutBase title="Sign-in" description="People sign in with their local workspace account.">
    <template #content><div class="space-y-4 py-4">
      <p class="text-sm text-ink-gray-6">Password sign-in is available for invited accounts. Change your password in Profile settings.</p>
      <p role="status" class="text-sm text-ink-gray-6">Single sign-in is not available yet. Use password sign-in.</p>
    </div></template>
  </SettingsLayoutBase>
</template>
<script setup lang="ts">
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
</script>
