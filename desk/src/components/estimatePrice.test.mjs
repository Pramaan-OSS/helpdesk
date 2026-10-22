import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createSSRApp} from 'vue';
import {renderToString} from '@vue/server-renderer';
import {estimatePrice} from './estimatePrice.js';
for(const typical of [undefined,0,6000]) test(`fake review estimate with typical ${typical}`,async()=>{
 const fakeClient={prepare:async()=>({price_max_micro:12345,...(typical===undefined?{}:{price_typical_micro:typical})})};
 const review=await fakeClient.prepare();const html=await renderToString(createSSRApp({render:()=>estimatePrice(review)}));
 if(typical===undefined)assert.match(html,/Worst-case Pramaan outcome cost: \$0.012345/);
 else {assert.ok(html.includes(`<strong>usually about $${(typical/1_000_000).toFixed(6)}</strong>`));assert.ok(html.includes('<small class="block">at most $0.012345</small>'));}
});
