<template>
  <component v-if="tab" :is="tab.component" class="h-full overflow-auto" />
  <p v-else role="status" class="p-6">This settings page is not available for your account.</p>
</template>
<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { tabs } from "@/components/Settings/settingsModal";
const route = useRoute();
const aliases: Record<string, string> = {
  telephony: 'Calling', signin: 'Sign-in', 'sign-in': 'Sign-in',
  'email-config': 'Email Accounts', 'email': 'Email Accounts', 'email-accounts': 'Email Accounts',
  'email-notifications': 'Email Notifications', sla: 'SLA Policies',
  'sla-policies': 'SLA Policies', holidays: 'Business Holidays',
  'business-holidays': 'Business Holidays', erpnext: 'Customer sync',
};
const tab = computed(() => {
  const slug = String(route.params.tab);
  return tabs.value.flatMap(group => group.items).find(item =>
    item.label === aliases[slug] || item.label.toLowerCase().replaceAll(' ', '-') === slug);
});
</script>
