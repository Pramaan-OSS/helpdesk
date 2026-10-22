<template>
  <details class="max-h-[40vh] shrink-0 overflow-y-auto border-b px-4 py-2 text-sm"><summary class="cursor-pointer font-medium">Pramaan assistance</summary>
    <p v-if="!configured" role="status" class="py-2">{{ missingKeyMessage }}</p><div class="flex flex-wrap gap-2 py-3"><Button :disabled="!configured" :loading="busy" @click="runDraft">{{ incomplete ? "Retry draft" : "Draft a reply" }}</Button><FormControl v-model="phone" label="Customer phone" placeholder="+441234567890" /><label><input v-model="recordAudio" type="checkbox" /> Request recording (confirm everyone agrees)</label><Button :disabled="!configured" :loading="busy" @click="callback">Request phone callback</Button></div>
    <div class="flex flex-wrap gap-2 pb-3"><label class="flex flex-col gap-1">Attachment<select v-model="selectedFile" aria-label="Attachment" class="min-h-7 rounded border bg-surface-base px-2"><option value="" disabled>Choose an attachment</option><option v-for="file in files" :key="file.value" :value="file.value">{{ file.label }}</option></select></label><Button :disabled="!configured || !selectedFile || busy" @click="parseFile">Read attachment text</Button><OutcomeReview :key="selectedFile" kind="Summary" :ticket="ticket" :file-name="selectedFile" :disabled="!configured || !selectedFile || busy" /></div>
    <p v-if="error" role="alert" class="mb-3 text-red-700">{{ error }}</p>
    <p v-if="state" role="status" class="mb-3">{{ state }} <Button v-if="callName" @click="checkCall">Check call status</Button> <Button v-if="callName && state === 'Ended' && recordAudio" @click="transcribe">Transcribe recording</Button> <Button v-if="callName && state === 'Ended' && recordAudio" @click="listen">Listen to recording</Button></p><OutcomeReview :key="callName" v-if="callName && state === 'Ended' && recordAudio" kind="Call" :ticket="ticket" :call-name="callName" /><audio v-if="recordingSource" :src="recordingSource" controls class="mb-3" />
    <div v-if="output" class="pb-3"><p class="mb-2 text-ink-gray-5">{{ incomplete ? "This draft is incomplete because it reached the reply limit. Retry the draft before using it." : "Review this text before using it." }}</p><textarea v-model="output" aria-label="Suggested text" class="h-36 w-full rounded border p-3" /><Button @click="copy">Copy text</Button></div>
  </details>
</template>
<script setup lang="ts">
import { usePramaanAvailability, actionError } from "@/composables/pramaan";
const { configured, missingKeyMessage } = usePramaanAvailability();
import OutcomeReview from "./OutcomeReview.vue";
import { ref, onMounted, onBeforeUnmount } from "vue";
import { call, Button, FormControl } from "frappe-ui";
const props = defineProps<{ticket:string}>(); const busy = ref(false); const error = ref(""); const incomplete = ref(false); const output = ref(""); const phone = ref(""); const state = ref(""); const callName = ref(""); const selectedFile = ref(""); const files = ref<any[]>([]); const recordAudio = ref(false); const recordingSource = ref(""); const requestId = ref(crypto.randomUUID());
onMounted(async()=>{try {const rows = await call("helpdesk.api.capabilities.ticket_files",{ticket:props.ticket}); files.value = rows.map((row:any)=>({label:row.file_name,value:row.name}));}catch {}});
async function action(method:string, inputs:any){busy.value=true;error.value="";try{return await call("helpdesk.api.capabilities."+method,inputs);}catch(err){error.value=actionError(err, "Could not complete this request. Check its status before trying again.");return null;}finally{busy.value=false;}}
async function runDraft(){const result=await action("draft_ticket_reply",{ticket:props.ticket});if(result){output.value=result.text;incomplete.value=!!result.incomplete;}}
async function parseFile(){const result=await action("parse_attachment",{file_name:selectedFile.value});if(result){output.value=result.text;incomplete.value=false;}}
async function callback(){const result=await action("start_callback",{ticket:props.ticket,recipient:phone.value,request_id:requestId.value,record_audio:recordAudio.value});if(result){callName.value=result.name;state.value=result.state;}}
async function checkCall(){const result=await action("callback_status",{name:callName.value});if(result){state.value=result.state;if(result.state==="Ended")requestId.value=crypto.randomUUID();}}
async function transcribe(){const result=await action("transcribe_call",{name:callName.value});if(result){output.value=result.text;incomplete.value=false;}}
async function listen(){
  busy.value=true;error.value="";
  try {
    const response=await fetch(`/api/method/helpdesk.api.capabilities.play_call?name=${encodeURIComponent(callName.value)}`,{credentials:"same-origin",headers:{Accept:"application/json"}});
    if(!response.ok){const body=await response.json().catch(()=>null);error.value=actionError(body,"Recording playback could not be opened. Check its status before trying again.");return;}
    if(recordingSource.value)URL.revokeObjectURL(recordingSource.value);
    recordingSource.value=URL.createObjectURL(await response.blob());
  }catch{error.value="Recording playback could not be opened. Check its status before trying again.";}
  finally{busy.value=false;}
}
onBeforeUnmount(()=>{if(recordingSource.value)URL.revokeObjectURL(recordingSource.value);});
async function copy(){try {await navigator.clipboard.writeText(output.value);state.value="Text copied.";}catch {error.value="Select and copy the text above.";}}
</script>
