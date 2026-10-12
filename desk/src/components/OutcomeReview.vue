<template>
  <div>
    <p v-if="!configured" role="status">{{ missingKeyMessage }}</p>
    <Button :disabled="!configured || disabled || busy" @click="begin">{{ kind === 'Summary' ? 'Summarise attachment' : 'Review call' }}</Button>
    <Dialog v-if="kind === 'Summary'" v-model:open="open" title="Summarise attachment" size="xl">
      <template #default><ReviewBody /></template>
    </Dialog>
    <div v-else-if="open" class="mt-3 rounded border p-3"><ReviewBody /></div>
  </div>
</template>

<script setup lang="ts">
import { usePramaanAvailability, actionError } from "@/composables/pramaan";
const { configured, missingKeyMessage } = usePramaanAvailability();
import { computed, defineComponent, h, ref } from 'vue';
import { Button, Dialog, call } from 'frappe-ui';

const props = defineProps<{ kind: 'Summary' | 'Call'; ticket: string; fileName?: string; callName?: string; disabled?: boolean }>();
const open = ref(false);
const busy = ref(false);
const review = ref<any>(null);
const error = ref('');
const criteria = ref('The issue was described.\nA next step was agreed.');
const basis = ref('contract');
const price = computed(() => `$${((review.value?.price_max_micro || 0) / 1_000_000).toFixed(6)}`);

async function request(method: string, inputs: Record<string, any>) {
  busy.value = true;
  error.value = '';
  try {
    review.value = await call('helpdesk.api.outcome_reviews.' + method, inputs);
  } catch (err) {
    error.value = actionError(err, method === 'prepare' ? 'Could not prepare this estimate. Check access and try later.'
      : 'This request could not be confirmed. Check its status before doing anything else.');
    // A dropped browser response may hide an accepted run. Never offer Run again.
    if (method === 'run' && review.value) review.value.state = 'Uncertain';
  } finally {
    busy.value = false;
  }
}
async function begin() {
  open.value = true;
  if (props.kind === 'Summary' && !review.value) await prepare();
}
async function prepare() {
  await request('prepare', { kind: props.kind, ticket: props.ticket, file_name: props.fileName,
    call_name: props.callName, criteria: criteria.value.split('\n').map(x => x.trim()).filter(Boolean), basis: basis.value });
}
async function approve() {
  await request('run', { review_id: review.value.review_id, approved: true });
}
async function check() {
  await request('status', { review_id: review.value.review_id });
}
async function save() {
  await request('save_call_note', { review_id: review.value.review_id, confirmed: true });
}
function text() {
  return [review.value?.summary || '', ...(review.value?.points || []).map((point: any) => `• ${point.text}`)].filter(Boolean).join('\n\n');
}
async function copy() {
  try { await navigator.clipboard.writeText(text()); error.value = 'Copied. Paste into an internal comment and review before saving.'; }
  catch { error.value = 'Select and copy the summary text below.'; }
}

// Share the estimate/result review body between the attachment dialog and call panel.
const ReviewBody = defineComponent({
  setup() {
    return () => h('div', { class: 'space-y-3 text-sm', 'data-testid': 'outcome-review' }, [
      h('p', props.kind === 'Summary'
        ? 'Summarise the selected attachment. Nothing is added to the ticket; copy the result into an internal comment if useful. Only documents with selectable text can be summarised; scanned images cannot be read.'
        : 'Check what was said or done. Findings are suggestions based on a transcript, not a judgement of a person.'),
      !review.value && props.kind === 'Call' ? h('div', { class: 'space-y-2' }, [
        h('label', [h('span', 'Checks (one per line, 1–10; up to 400 characters each)'),
          h('textarea', { class: 'w-full rounded border p-2', 'aria-label': 'Call review checks', value: criteria.value,
            onInput: (event: any) => criteria.value = event.target.value })]),
        h('label', ['Basis for processing the recording ', h('select', { value: basis.value, 'aria-label': 'Recording processing basis',
          onChange: (event: any) => basis.value = event.target.value },
          [['contract', 'Contract'], ['consent', 'Consent'], ['legitimate_interest', 'Legitimate interest']].map(([value, label]) => h('option', { value }, label)))]),
        h(Button, { loading: busy.value, onClick: prepare }, () => 'Get estimate'),
      ]) : null,
      busy.value ? h('p', { role: 'status' }, 'Working…') : null,
      review.value?.state === 'Ready' ? h('div', { class: 'space-y-2' }, [
        h('p', { class: 'font-medium' }, `${review.value.source_label} (${review.value.source_size} bytes)`),
        h('p', { class: 'font-medium' }, `Worst-case Pramaan outcome cost: ${price.value}`),
        h('ul', { class: 'list-disc pl-5' }, (review.value.steps || []).map((step: string) => h('li', step))),
        props.kind === 'Call' ? h('p', `Recording processing basis: ${review.value.basis.replace('_', ' ')}. Checks: ${(review.value.criteria || []).join(' ')}`) : null,
        h('p', 'This estimate is valid for 15 minutes. Approve only if you agree to these steps and cost.'),
        h(Button, { disabled: busy.value, variant: 'solid', onClick: approve }, () => props.kind === 'Summary' ? 'Approve and summarise' : 'Approve and review call'),
        h(Button, { disabled: busy.value, onClick: () => open.value = false }, () => 'Cancel'),
      ]) : null,
      review.value?.message ? h('p', { role: 'alert' }, review.value.message) : null,
      ['Running', 'Pending', 'Uncertain'].includes(review.value?.state) ? h(Button, { disabled: busy.value, onClick: check }, () => 'Check review status') : null,
      ['Failed', 'Expired', 'Unavailable'].includes(review.value?.state) ? h(Button, { disabled: busy.value, onClick: () => { review.value = null; if (props.kind === 'Summary') prepare(); } }, () => 'Get a new estimate') : null,
      review.value?.state === 'Completed' ? h('div', { class: 'space-y-3' }, [
        review.value.partial || review.value.truncated ? h('p', { role: 'status' }, 'Only part of the source was checked, or some results are missing. Review the text before using it.') : null,
        props.kind === 'Summary' ? h('div', { class: 'space-y-2' }, [
          text() ? h('textarea', { readonly: true, value: text(), 'aria-label': 'Attachment summary', class: 'h-48 w-full rounded border p-3' })
            : h('p', 'No usable summary was returned. Nothing was saved.'),
          h(Button, { disabled: !text() || busy.value, onClick: copy }, () => 'Copy summary'),
          h(Button, { onClick: () => open.value = false }, () => 'Close'),
        ]) : h('div', { class: 'space-y-3' }, [
          ...(review.value.findings || []).map((finding: any) => h('div', { class: 'rounded border p-2' }, [
            h('p', { class: 'font-medium' }, finding.criterion), h('p', ({ met: 'Evidence found', not_evidenced: 'Not evidenced in the call', not_checked: 'Not checked' } as Record<string, string>)[finding.outcome] || 'Not checked'),
            finding.quote ? h('blockquote', `“${finding.quote}”`) : null,
            finding.start != null ? h('p', `At ${finding.start} seconds`) : null,
            finding.note ? h('p', finding.note) : null,
          ])),
          !(review.value.findings || []).length ? h('p', 'No usable findings were returned. Nothing was saved.') : null,
          h(Button, { disabled: busy.value || review.value.saved || !(review.value.findings || []).length, onClick: save }, () => review.value.saved ? 'Internal note saved' : 'Confirm and save internal note'),
        ]),
      ]) : null,
      error.value ? h('p', { role: 'alert' }, error.value) : null,
    ]);
  },
});
</script>
