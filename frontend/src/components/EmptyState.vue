<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="empty-state">
    <span class="empty-glyph" aria-hidden="true">档</span>
    <p class="empty-title">{{ title }}</p>
    <p v-if="description" class="empty-description">{{ description }}</p>
    <slot />
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: var(--space-6) var(--space-5);
  border: 1px dashed var(--color-border-strong);
  background: var(--color-bg);
  color: var(--color-text-muted);
  text-align: center;
}

.empty-glyph {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  margin-bottom: 8px;
  border: 1px solid var(--color-border-strong);
  font-family: var(--font-serif);
  font-size: 20px;
  color: var(--color-border-strong);
}

.empty-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
}

.empty-description {
  margin: 0;
  font-size: var(--text-sm);
}
</style>
