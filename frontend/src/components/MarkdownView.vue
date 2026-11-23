<script setup lang="ts">
import createDOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'

const purifier = createDOMPurify(window)

const props = defineProps<{ source?: string }>()

const text = computed(() => (props.source ?? '').trim())

const rendered = computed(() => {
  if (!text.value) {
    return ''
  }
  try {
    const html = marked.parse(text.value, { async: false }) as string
    return purifier.sanitize(html, {
      FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form'],
      FORBID_ATTR: ['onerror', 'onclick', 'onload'],
    })
  } catch {
    return ''
  }
})
</script>

<template>
  <div v-if="!text" class="markdown-empty">暂无求职建议</div>
  <div v-else-if="rendered" class="markdown-body" v-html="rendered"></div>
  <pre v-else class="markdown-fallback">{{ source }}</pre>
</template>

<style scoped>
.markdown-empty {
  padding: var(--space-4);
  border: 1px dashed var(--color-border-strong);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.markdown-body {
  min-width: 0;
  max-width: 100%;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin: var(--space-4) 0 var(--space-2);
  font-family: var(--font-serif);
  font-size: var(--text-lg);
}

.markdown-body :deep(h1) {
  font-size: var(--text-xl);
}

.markdown-body :deep(h2) {
  font-size: var(--text-lg);
}

.markdown-body :deep(h3) {
  font-size: var(--text-md);
}

.markdown-body :deep(h4) {
  margin: var(--space-3) 0 var(--space-2);
  color: var(--color-primary);
  font-family: var(--font-serif);
  font-size: var(--text-sm);
}

.markdown-body :deep(p) {
  margin: 0 0 var(--space-2);
  line-height: 1.8;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 var(--space-3);
  padding-left: var(--space-5);
  list-style: disc;
}

.markdown-body :deep(ol) {
  list-style: decimal;
}

.markdown-body :deep(li) {
  margin-bottom: 4px;
}

.markdown-body :deep(strong) {
  color: var(--color-text);
  font-weight: 600;
}

.markdown-body :deep(a) {
  color: var(--color-primary);
}

.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: var(--space-4) 0;
}

.markdown-body :deep(code) {
  padding: 1px 5px;
  background: var(--color-surface-muted);
  font-family: var(--font-mono);
  font-size: 0.9em;
}

.markdown-body :deep(pre) {
  max-width: 100%;
  overflow-x: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 0 0 var(--space-3);
  padding: var(--space-3);
  background: var(--color-code-bg);
  color: var(--color-code-text);
}

.markdown-body :deep(pre code) {
  padding: 0;
  background: none;
  color: inherit;
}

.markdown-body :deep(blockquote) {
  margin: 0 0 var(--space-3);
  padding: 10px 14px;
  border-left: 2px solid var(--color-primary);
  background: var(--color-bg);
  color: var(--color-text-muted);
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 7px 10px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}

.markdown-body :deep(th) {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.markdown-fallback {
  margin: 0;
  padding: var(--space-3);
  background: var(--color-code-bg);
  color: var(--color-code-text);
  white-space: pre-wrap;
}
</style>
