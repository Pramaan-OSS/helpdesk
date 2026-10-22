import { h } from 'vue';
export function estimatePrice(review) {
 const money = micro => `$${(micro / 1_000_000).toFixed(6)}`;
 return review.price_typical_micro !== undefined && review.price_typical_micro !== null
 ? h('p', [h('strong', `usually about ${money(review.price_typical_micro)}`), h('small', {class:'block'}, `at most ${money(review.price_max_micro)}`)])
 : h('p', {class:'font-medium'}, `Worst-case Pramaan outcome cost: ${money(review.price_max_micro || 0)}`);
}
