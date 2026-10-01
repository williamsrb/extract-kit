<template>
  <div class="tile">
    <span v-if="price > 150" class="premium">Premium</span>
    <PriceTag :price="total" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import PriceTag from './PriceTag.vue';

const props = defineProps<{ price: number; quantity: number }>();
const total = computed(() => props.price * props.quantity);
</script>
