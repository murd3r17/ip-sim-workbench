<template>
  <header class="v7b-page-header">
    <div>
      <h1>{{ title }}</h1>
      <p v-if="subtitle" class="sub">{{ subtitle }}</p>
      <div v-if="$slots.meta" class="meta"><slot name="meta" /></div>
    </div>
    <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
  </header>
</template>

<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<style scoped>
.meta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
</style>
