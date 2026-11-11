<script setup>
/**
 * BlockTextDiff —— unified diff 文本渲染：等宽字体，新增绿行 / 删除红行。
 * 配对的 删行+增行 块做行内字符级对比（剥离公共头尾），差异片段叠加深色高亮，
 * 使"看似一样的两行"（全半角/空格等不可见差异）能立刻看出变了哪几个字。
 */
import { computed } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
})

const lines = computed(() => {
  if (!props.text) return []
  const arr = props.text.split('\n')
  if (arr.length && arr[arr.length - 1] === '') arr.pop()
  return arr
})

function cls(line) {
  if (line.startsWith('+++') || line.startsWith('---')) return 'line-file'
  if (line.startsWith('@@')) return 'line-hunk'
  if (line.startsWith('+')) return 'line-add'
  if (line.startsWith('-')) return 'line-del'
  return ''
}

function plainLine(l, c) {
  if (c === 'line-del' || c === 'line-add') {
    return { cls: c, sign: l[0], segs: [{ t: l.slice(1) || ' ', em: false }] }
  }
  return { cls: c, sign: '', segs: [{ t: l || ' ', em: false }] }
}

// 配对行：剥离公共前缀/后缀，中间差异段标 em
function pairLine(l, other, c) {
  const a = l.slice(1)
  const b = other.slice(1)
  let p = 0
  const max = Math.min(a.length, b.length)
  while (p < max && a[p] === b[p]) p++
  let s = 0
  while (s < max - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s++
  const segs = []
  if (p) segs.push({ t: a.slice(0, p), em: false })
  const mid = a.slice(p, a.length - s)
  segs.push({ t: mid, em: mid.length > 0 })
  if (s) segs.push({ t: a.slice(a.length - s), em: false })
  return { cls: c, sign: l[0], segs }
}

// 连续的 - 行紧跟 + 行视为一个变更块，按序两两配对做行内对比
const rendered = computed(() => {
  const arr = lines.value
  const out = []
  let i = 0
  while (i < arr.length) {
    const c = cls(arr[i])
    if (c === 'line-del') {
      const dels = []
      while (i < arr.length && cls(arr[i]) === 'line-del') dels.push(arr[i++])
      const adds = []
      while (i < arr.length && cls(arr[i]) === 'line-add') adds.push(arr[i++])
      const pairs = Math.min(dels.length, adds.length)
      for (let k = 0; k < dels.length; k++) {
        out.push(k < pairs ? pairLine(dels[k], adds[k], 'line-del') : plainLine(dels[k], 'line-del'))
      }
      for (let k = 0; k < adds.length; k++) {
        out.push(k < pairs ? pairLine(adds[k], dels[k], 'line-add') : plainLine(adds[k], 'line-add'))
      }
      continue
    }
    out.push(plainLine(arr[i], c))
    i++
  }
  return out
})
</script>

<template>
  <pre v-if="rendered.length" class="diff mono"><code><span
      v-for="(l, i) in rendered"
      :key="i"
      class="dl"
      :class="l.cls"
    ><span v-if="l.sign" class="ds">{{ l.sign }}</span><span
      v-for="(s, j) in l.segs"
      :key="j"
      :class="{ dem: s.em && l.cls === 'line-del', aem: s.em && l.cls === 'line-add' }"
    >{{ s.t }}</span></span></code></pre>
  <p v-else class="muted">无差异。</p>
</template>

<style scoped>
.diff {
  margin: 0;
  padding: var(--sp-3);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  overflow-x: auto;
  font-size: var(--text-xs);
  line-height: 1.6;
}

.dl {
  display: block;
  white-space: pre;
  padding: 0 var(--sp-2);
}

.line-add {
  color: var(--success);
  background: rgba(21, 122, 78, 0.08);
}

.line-del {
  color: var(--danger);
  background: rgba(196, 53, 28, 0.08);
}

.line-hunk {
  color: var(--contract);
}

.line-file {
  color: var(--ink-2);
}

/* 行内差异片段：在行底色上叠加强调色（GitHub intra-line highlight 观感） */
.dem {
  background: rgba(196, 53, 28, 0.25);
  border-radius: 2px;
}

.aem {
  background: rgba(21, 122, 78, 0.25);
  border-radius: 2px;
}
</style>
