<script setup lang="ts">
defineProps<{ label?: string }>()
</script>

<template>
  <div class="loading-state" role="status" aria-live="polite">
    <div class="skeleton" aria-hidden="true">
      <span class="skeleton-line skeleton-line-wide"></span>
      <span class="skeleton-line"></span>
      <span class="skeleton-line skeleton-line-short"></span>
    </div>
    <p class="loading-label">{{ label ?? '加载中…' }}</p>
  </div>
</template>

<style scoped>
.loading-state {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}

.skeleton {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.skeleton-line {
  height: 9px;
  width: 62%;
  background: var(--color-surface-muted);
  animation: pulse 1.4s var(--ease) infinite;
}

.skeleton-line-wide {
  width: 100%;
}

.skeleton-line-short {
  width: 36%;
}

.loading-label {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--color-text-muted);
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.55;
  }

  50% {
    opacity: 1;
  }
}
</style>
