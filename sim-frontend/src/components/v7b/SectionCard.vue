<template>
  <section class="v7b-card">
    <div v-if="title || $slots.actions" class="v7b-card-head">
      <h2>{{ title }}</h2>
      <div v-if="$slots.actions" class="v7b-actions"><slot name="actions" /></div>
    </div>
    <div class="v7b-card-body"><slot /></div>
  </section>
</template>

<script setup lang="ts">
defineProps<{ title?: string }>()
</script>
