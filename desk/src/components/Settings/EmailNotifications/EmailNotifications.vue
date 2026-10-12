<template>
  <SettingsLayoutBase v-if="!event" title="Email notifications" description="Ticket replies and automatic emails use Pramaan.">
    <template #content>
      <div class="space-y-3 py-4 text-sm">
        <p>Automatic acknowledgements and feedback emails are supported. They are off by default; enable the events below after connecting an outgoing mailbox. Automatic messages include loop-safe headers.</p>
        <p>Normal replies preserve their email thread, including edited recipients and subject.</p>
        <Button @click="event = 'acknowledgement'">Acknowledgement</Button>
        <Button @click="event = 'share_feedback'">Share feedback</Button>
      </div>
    </template>
  </SettingsLayoutBase>
  <Acknowledgement v-if="event === 'acknowledgement'" :on-back="() => event = ''" :notification="{ name: 'acknowledgement', label: 'Acknowledgement', description: 'Send an acknowledgement when a ticket is created.' }" />
  <ShareFeedback v-if="event === 'share_feedback'" :on-back="() => event = ''" :notification="{ name: 'share_feedback', label: 'Share feedback', description: 'Ask for feedback when a ticket reaches the chosen status.' }" />
</template>
<script setup lang="ts">
import { ref } from "vue";
import { Button } from "frappe-ui";
import SettingsLayoutBase from "@/components/layouts/SettingsLayoutBase.vue";
import Acknowledgement from "./Acknowledgement.vue";
import ShareFeedback from "./ShareFeedback.vue";
const event = ref('');
</script>
