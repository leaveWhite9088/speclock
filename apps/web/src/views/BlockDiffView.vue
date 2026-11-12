<script setup>
/**
 * BlockDiffView（/blocks/:id/diff）—— 版本对比：from/to 选择器（默认最近两版）、
 * 结构化 delta 分组表、规则变更表、文本 diff（绿增红删）。
 * 单版本时展示后端 message 的引导空状态。
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { resources } from '../api/resources.js'
import { errText } from '../errors.js'
import VersionChip from '../components/VersionChip.vue'
import BlockDeltaGroups from '../components/BlockDeltaGroups.vue'
import BlockTextDiff from '../components/BlockTextDiff.vue'
import AppBreadcrumb from '../components/AppBreadcrumb.vue'
import LoadingState from '../components/LoadingState.vue'
import ErrorState from '../components/ErrorState.vue'

const route = useRoute()
const router = useRouter()
const bid = route.params.id

const loading = ref(true)
const loadError = ref('')
const title = ref('')
const versions = ref([])

const fromV = ref('')
const toV = ref('')
const diffData = ref(null)
const singleMessage = ref('')
const diffLoading = ref(false)
const diffError = ref('')

async function runDiff() {
  diffData.value = null
  singleMessage.value = ''
  diffError.value = ''
  if (!fromV.value || !toV.value || fromV.value === toV.value) return
  diffLoading.value = true
  try {
    const res = await resources.blocks.diff(bid, { from: fromV.value, to: toV.value })
    if (res.message) singleMessage.value = res.message
    else diffData.value = res
  } catch (e) {
    diffError.value = errText(e)
  } finally {
    diffLoading.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const vs = await resources.blocks.versions(bid)
    versions.value = [...vs].sort((a, b) =>
      String(a.published_at || '').localeCompare(String(b.published_at || '')),
    )
    if (versions.value.length) {
      const snap = await resources.blocks.version(bid, versions.value.at(-1).version)
      title.value = snap.title
    }
    const q = route.query
    const last = versions.value.at(-1)?.version || ''
    const prev = versions.value.at(-2)?.version || ''
    fromV.value = typeof q.from === 'string' && q.from ? q.from : prev
    toV.value = typeof q.to === 'string' && q.to ? q.to : last
    await runDiff()
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

// 选择器变更：同步地址栏（可分享）并重新对比
watch([fromV, toV], ([f, t], [of, ot]) => {
  if (loading.value || (f === of && t === ot)) return
  router.replace({ query: { ...route.query, from: f || undefined, to: t || undefined } })
  runDiff()
})

const sameVersion = computed(
  () => fromV.value && toV.value && fromV.value === toV.value,
)

const itemsDelta = computed(() => (diffData.value ? diffData.value.delta : null))

const hasItemsDelta = computed(() => {
  const d = itemsDelta.value
  if (!d) return false
  return ['rules', 'acceptance'].some((k) =>
    ['added', 'modified', 'renamed', 'removed'].some((x) => (d[`${k}_${x}`] || []).length),
  )
})

// diff 接口只返回字符串 delta；分组表需要结构化的 groups，由后端 publish 预览提供。
// 这里从 delta 字符串重建最简分组（键形如 "response:GET /x:a.b: string required"）。
const groups = computed(() => {
  if (!diffData.value) return []
  const d = diffData.value.delta
  const out = new Map()
  const parse = (entry) => {
    const colon = entry.indexOf(': ')
    const keyPart = colon === -1 ? entry : entry.slice(0, colon)
    const detail = colon === -1 ? '' : entry.slice(colon + 2)
    const [kind, rest] = keyPart.split(':', 2)
    if (!rest.includes(':')) return { scope: kind, apiKey: rest, path: '', detail }
    const sp = rest.indexOf(' ')
    const colon2 = rest.indexOf(':', sp)
    return {
      scope: kind,
      apiKey: rest.slice(0, colon2),
      path: rest.slice(colon2 + 1),
      detail,
    }
  }
  const add = (kind, entries) => {
    for (const entry of entries || []) {
      const p = parse(entry)
      if (!out.has(p.apiKey))
        out.set(p.apiKey, { api_key: p.apiKey, api_name: '', changes: [] })
      out.get(p.apiKey).changes.push({
        kind,
        scope: p.scope,
        path: p.path,
        detail: p.detail,
        description: '',
      })
    }
  }
  add('added', d.added)
  add('modified', d.modified)
  add('removed', d.removed)
  return [...out.values()]
})
</script>

<template>
  <div class="page diff-page">
    <LoadingState v-if="loading" />
    <ErrorState v-else-if="loadError" :message="loadError" @retry="load" />

    <template v-else>
      <AppBreadcrumb :block-id="bid" append="版本对比" />
      <h1 class="page-title">版本对比 · {{ title }}</h1>

      <div class="selector-bar card">
        <label class="sel">
          <span class="sel-label mono">from</span>
          <select class="input" v-model="fromV" :disabled="!versions.length">
            <option v-for="v in versions" :key="v.version" :value="v.version">
              v{{ v.version }}
            </option>
          </select>
        </label>
        <span class="arrow mono">→</span>
        <label class="sel">
          <span class="sel-label mono">to</span>
          <select class="input" v-model="toV" :disabled="!versions.length">
            <option v-for="v in versions" :key="v.version" :value="v.version">
              v{{ v.version }}
            </option>
          </select>
        </label>
        <span v-if="diffLoading" class="muted">正在对比…</span>
      </div>

      <!-- 单版本 / 无可对比版本：引导空状态（后端原文 message） -->
      <div v-if="singleMessage" class="card empty">
        <p class="empty-title">{{ singleMessage }}</p>
        <p class="muted">模块有第二个版本后即可查看差异。</p>
        <div class="empty-vers">
          <VersionChip v-for="v in versions" :key="v.version" :version="v.version" />
        </div>
      </div>

      <p v-else-if="sameVersion" class="muted hint">
        请选择两个不同的已发布版本进行对比。
      </p>

      <p v-if="diffError" class="error-text" role="alert">{{ diffError }}</p>

      <template v-if="diffData">
        <div class="card summary-bar">
          <VersionChip :version="diffData.from" />
          <span class="arrow mono">→</span>
          <VersionChip :version="diffData.to" />
          <span v-if="diffData.level" class="level-tag mono" title="由 diff 机械算出，仅供参考">
            级别 {{ diffData.level }}
          </span>
          <span class="cnt cnt-add">新增 {{ diffData.delta.added.length }}</span>
          <span class="cnt cnt-mod">修改 {{ diffData.delta.modified.length }}</span>
          <span class="cnt cnt-del">删除 {{ diffData.delta.removed.length }}</span>
        </div>

        <section class="sec">
          <h2 class="sec-title">API 结构变更</h2>
          <BlockDeltaGroups :groups="groups" :items-delta="itemsDelta" />
          <p v-if="!hasItemsDelta" class="muted">业务规则与验收条件无变更。</p>
        </section>

        <section class="sec">
          <details class="textdiff" open>
            <summary class="sec-title">业务描述文本 diff</summary>
            <BlockTextDiff :text="diffData.content_diff" />
          </details>
        </section>

        <section class="sec">
          <details class="textdiff" open>
            <summary class="sec-title">OpenAPI 文本 diff</summary>
            <BlockTextDiff :text="diffData.openapi_diff" />
          </details>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.load-fail {
  margin-top: var(--sp-5);
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.selector-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  margin: var(--sp-4) 0;
}

.sel {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
}

.sel-label {
  font-size: var(--text-xs);
  color: var(--ink-2);
  letter-spacing: 0.06em;
}

.sel .input {
  width: auto;
  padding: 4px var(--sp-2);
}

.arrow {
  color: var(--ink-2);
}

.hint {
  margin-top: var(--sp-4);
}

.empty {
  margin-top: var(--sp-4);
  padding: var(--sp-6);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
  border-style: dashed;
}

.empty-title {
  font-size: var(--text-lg);
  font-weight: 600;
}

.empty-vers {
  display: flex;
  gap: var(--sp-2);
}

.summary-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  padding: var(--sp-3) var(--sp-4);
  margin-bottom: var(--sp-4);
}

.cnt {
  font-size: var(--text-xs);
  font-family: var(--font-mono);
}

.cnt-add {
  color: var(--success);
}

.cnt-mod {
  color: var(--warning);
}

.cnt-del {
  color: var(--danger);
}

.sec {
  margin-bottom: var(--sp-5);
}

.sec-title {
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-3);
}

.textdiff summary {
  cursor: pointer;
}
.level-tag {
  font-size: var(--text-xs);
  padding: 0 var(--sp-2);
  border-radius: 999px;
  background: var(--side);
  color: var(--ink-2);
}
</style>
