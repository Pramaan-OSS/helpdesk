<template><details class="mb-4 rounded border p-3"><summary class="cursor-pointer text-sm">Draft from documentation</summary><div class="my-3 flex gap-2"><FormControl v-model="url" label="Public documentation page" placeholder="https://your-site.com/docs" /><Button :loading="busy" @click="draft">{{ incomplete ? "Retry draft" : "Suggest article" }}</Button></div><p v-if="error" role="alert" class="text-sm">{{ error }}</p><p class="text-sm text-ink-gray-5">Review the draft before creating or publishing your article.</p></details></template>
<script setup lang="ts">
import { actionError } from "@/composables/pramaan";
import {ref} from "vue";import {FormControl,Button,call} from "frappe-ui";
const incomplete=ref(false);const emit=defineEmits<{draft:[text:string]}>();const url=ref("");const busy=ref(false);const error=ref("");
async function draft(){busy.value=true;error.value="";try{const result=await call("helpdesk.api.capabilities.draft_article",{url:url.value});incomplete.value=!!result.incomplete;error.value=result.message || "";emit("draft",result.text);}catch(err){error.value=actionError(err,"Could not draft an article from that page.");}finally{busy.value=false;}}
</script>
