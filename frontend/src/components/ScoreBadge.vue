<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ score: number }>()

const tone = computed(() => {
  if (props.score >= 80) {
    return 'score-high'
  }
  if (props.score >= 50) {
    return 'score-mid'
  }
  return 'score-low'
})
</script>

<template>
  <span class="score-badge" :class="tone">
    <span class="score-value">{{ score }}</span>
    <span class="score-scale">/ 100</span>
  </span>
</template>

<style scoped>
.score-badge {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  color: var(--color-text);
  line-height: 0.85;
}

.score-value {
  font-family: var(--font-serif);
  font-size: 54px;
  font-weight: 900;
  letter-spacing: -0.04em;
}

.score-scale {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.06em;
  color: var(--color-text-muted);
}

.score-high .score-value {
  color: var(--color-moss);
}

.score-mid .score-value {
  color: var(--color-amber);
}

.score-low .score-value {
  color: var(--color-primary);
}
</style>
