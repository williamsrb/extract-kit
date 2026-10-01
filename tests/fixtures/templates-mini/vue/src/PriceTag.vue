<template>
  <span class="price">{{ price }}</span>
</template>

<script setup lang="ts">
defineProps<{ price: number }>();
</script>
