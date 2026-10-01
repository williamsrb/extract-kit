<template>
  <div class="card">
    <h3>{{ title }}</h3>
    <span v-if="price > 100" class="premium">Premium</span>
    <ul v-if="items.length > 0">
      <li v-for="item in items" :key="item">{{ item }}</li>
    </ul>
    <PriceTag :price="price" />
    <button @click="emit('buy')">Buy</button>
  </div>
</template>

<script setup lang="ts">
import PriceTag from './PriceTag.vue';

defineProps<{ title: string; price: number; items: string[] }>();
const emit = defineEmits(['buy']);
</script>
