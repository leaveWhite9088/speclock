<script setup>
/**
 * AiMeetingsView —— 会议记录分享面板（挂在 McpView 的「会议记录分享」Tab 下，
 * 不再是独立路由页面）：选会议 → 哈希码 → 范围勾选 → 生成 curl 命令与
 * 提示词模板（含完整 URL），可预览返回文档。
 * 会议记录不走 MCP——每个会议一个 /api/share/{token} 哈希码只读链接。
 */
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/client.js'
import { KIND_LABELS, SHAREABLE_KINDS, errText } from '../meetingMeta.js'

const series = ref([])
const loading = ref(true)
const loadError = ref('')

const selectedKey = ref('') // "m:<meetingId>" | "s:<seriesId>"
const meeting = ref(null)
const seriesDoc = ref(null) // 选中业务线时的详情
const detailError = ref('')
const kinds = ref([])

const preview = ref('')
const previewLoading = ref(false)
const previewError = ref('')

const copyState = ref('') // 'curl' | 'brief' | 'token'
const copied = ref(false)

const meetings = computed(() =>
  series.value.flatMap((s) =>
    s.meetings.map((m) => ({ ...m, seriesName: s.name })),
  ),
)

const target = computed(() => meeting.value || seriesDoc.value) // 两者都有 share_token/name
const isSeries = computed(() => !!seriesDoc.value)

const shareUrl = computed(() => {
  if (!target.value) return ''
  const base = `${window.location.origin}/api/share/${target.value.share_token}`
  // 业务线分享是固定范围（两个汇总文档），没有 kinds 覆盖
  if (isSeries.value) return base
  return kinds.value.length ? `${base}?kinds=${kinds.value.join(',')}` : base
})

const curlCmd = computed(() => (shareUrl.value ? `curl "${shareUrl.value}"` : ''))

const brief = computed(() => {
  if (!target.value) return ''
  if (isSeries.value) {
    return `# 业务线汇总资料：${seriesDoc.value.name}

你是一名开发 AI agent。下面这个 URL 是 SpecLock 会议记录模块为业务线「${seriesDoc.value.name}」生成的公开只读资料链接，返回 Markdown 文本（Content-Type: text/markdown），内容是该业务线下全部会议汇总出的「总精准需求」与「总业务事实」两份文档。

${shareUrl.value}

使用方法：
- 用 curl / fetch 直接 GET 该 URL 即可拿到全部资料（无需任何鉴权头，哈希码本身即授权）。
- 条目编号（REQ/CON/ACT/Q/FACT）在汇总文档内唯一且稳定；每条目带「来源」行（会议名 · 原编号，或「业务级增加」），引用时请带上编号。
- 该链接可由负责人随时重新生成（旧链接立即失效）；若返回 404，请向负责人索取新链接。
`
  }
  const kindNames = kinds.value.map((k) => KIND_LABELS[k]).join('、') || '（未勾选任何范围）'
  return `# 会议记录资料：${meeting.value.name}

你是一名开发 AI agent。下面这个 URL 是 SpecLock 会议记录模块为会议「${meeting.value.name}」（业务线：${meeting.value.series_name}）生成的公开只读资料链接，返回 Markdown 文本（Content-Type: text/markdown），当前导出范围：${kindNames}。

${shareUrl.value}

使用方法：
- 用 curl / fetch 直接 GET 该 URL 即可拿到全部资料（无需任何鉴权头，哈希码本身即授权）。
- 资料包含会议元信息（业务线、日期、原始目录）与按文件类型分节的 Markdown 正文：精准需求（REQ/CON/ACT/Q 条目，含 status/confirm/based_on/原文引用）、业务事实（FACT 条目）等。
- 条目编号（如 REQ-01、FACT-03）在会议内唯一且稳定，引用时请带上编号。
- 需要会议内检索时可用：${window.location.origin}/api/share/${meeting.value.share_token}/search?q=关键词&kind=req|fact
- 该链接可由会议负责人随时重新生成（旧链接立即失效）；若返回 404，说明哈希码已轮换，请向负责人索取新链接。
`
})

async function copyText(text, which) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copyState.value = which
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

async function selectTarget(key) {
  selectedKey.value = key
  meeting.value = null
  seriesDoc.value = null
  preview.value = ''
  previewError.value = ''
  detailError.value = ''
  if (!key) return
  try {
    if (key.startsWith('s:')) {
      seriesDoc.value = await api.get(`/meeting-series/${key.slice(2)}`)
    } else {
      meeting.value = await api.get(`/meetings/${key.slice(2)}`)
      kinds.value = [...meeting.value.share_kinds]
    }
  } catch (e) {
    detailError.value = errText(e)
  }
}

async function loadPreview() {
  previewLoading.value = true
  previewError.value = ''
  preview.value = ''
  try {
    const res = await fetch(shareUrl.value)
    if (!res.ok) throw { detail: `请求失败（HTTP ${res.status}）` }
    preview.value = await res.text()
  } catch (e) {
    previewError.value = errText(e)
  } finally {
    previewLoading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    series.value = await api.get('/meeting-series')
    const first = meetings.value[0]
    if (first) await selectTarget(`m:${first.id}`)
    else if (series.value.length) await selectTarget(`s:${series.value[0].id}`)
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ai-panel">
    <p class="page-desc">
      会议记录不走 MCP——每个会议有一个哈希码只读链接（<code>/api/share/…</code>），
      把链接或生成的提示词发给 AI 即可读取会议资料。
    </p>

    <div v-if="loading" class="muted loading">正在加载…</div>
    <p v-else-if="loadError" class="error-text" role="alert">{{ loadError }}</p>

    <div v-else-if="!series.length" class="card empty">
      <p class="empty-title">还没有会议</p>
      <p class="muted">先到「会议记录」页建业务线与会议并上传文件，再回来生成接入链接。</p>
      <RouterLink class="btn btn-primary" to="/meetings">去会议记录页</RouterLink>
    </div>

    <template v-else>
      <section class="section">
        <h2 class="section-title">第 1 步：选业务线或会议</h2>
        <div class="card section-card">
          <div class="pick-row">
            <select
              class="input meeting-picker"
              :value="selectedKey"
              @change="selectTarget($event.target.value)"
              aria-label="选择业务线或会议"
            >
              <optgroup label="业务线（汇总文档）">
                <option v-for="s in series" :key="`s-${s.id}`" :value="`s:${s.id}`">
                  {{ s.name }}
                </option>
              </optgroup>
              <optgroup label="会议">
                <option v-for="m in meetings" :key="`m-${m.id}`" :value="`m:${m.id}`">
                  {{ m.seriesName }} › {{ m.name }}{{ m.date ? `（${m.date}）` : '' }}
                </option>
              </optgroup>
            </select>
          </div>
          <p v-if="detailError" class="error-text" role="alert">{{ detailError }}</p>
          <template v-if="target">
            <div class="token-row">
              <span class="label token-label">哈希码</span>
              <code class="mono token">{{ target.share_token }}</code>
              <button type="button" class="btn" @click="copyText(target.share_token, 'token')">
                {{ copied && copyState === 'token' ? '已复制 ✓' : '复制' }}
              </button>
            </div>
            <template v-if="!isSeries">
              <div class="kinds-row">
                <label v-for="k in SHAREABLE_KINDS" :key="k" class="kind-check">
                  <input type="checkbox" :value="k" v-model="kinds" />
                  {{ KIND_LABELS[k] }}
                </label>
              </div>
              <p class="muted hint">
                这里的勾选只影响下方生成的链接（以 ?kinds= 临时覆盖）；要改会议的默认分享范围，
                请到<RouterLink :to="`/meetings/${meeting.id}`">会议详情页</RouterLink>保存。
              </p>
            </template>
            <p v-else class="muted hint">
              业务线分享输出该业务线的「总精准需求 + 总业务事实」汇总文档（条目带来源行）；
              汇总内容先到<RouterLink :to="`/meetings/series/${seriesDoc.id}`">业务线详情页</RouterLink>刷新生成。
            </p>
          </template>
        </div>
      </section>

      <template v-if="target">
        <section class="section">
          <h2 class="section-title">第 2 步：curl 命令</h2>
          <div class="card section-card">
            <pre class="code-pre mono">{{ curlCmd }}</pre>
            <button type="button" class="btn" @click="copyText(curlCmd, 'curl')">
              {{ copied && copyState === 'curl' ? '已复制到剪贴板 ✓' : '复制 curl 命令' }}
            </button>
          </div>
        </section>

        <section class="section">
          <h2 class="section-title">第 3 步：提示词模板（直接贴给 AI）</h2>
          <div class="card section-card">
            <pre class="code-pre mono brief-pre">{{ brief }}</pre>
            <button type="button" class="btn btn-primary" @click="copyText(brief, 'brief')">
              {{ copied && copyState === 'brief' ? '已复制到剪贴板 ✓' : '复制提示词' }}
            </button>
          </div>
        </section>

        <section class="section">
          <h2 class="section-title">预览返回文档</h2>
          <div class="card section-card">
            <div class="preview-ops">
              <button
                type="button"
                class="btn"
                :disabled="previewLoading"
                @click="loadPreview"
              >
                {{ previewLoading ? '拉取中…' : '拉取预览' }}
              </button>
              <span class="muted hint">实际请求上方链接，展示 AI 将看到的 Markdown 原文。</span>
            </div>
            <p v-if="previewError" class="error-text" role="alert">{{ previewError }}</p>
            <pre v-if="preview" class="code-pre mono preview-pre">{{ preview }}</pre>
          </div>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.ai-panel {
  margin-top: var(--sp-2);
}

.loading {
  margin-top: var(--sp-6);
}

.empty {
  margin-top: var(--sp-5);
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

.section {
  margin-top: var(--sp-6);
}

.section-title {
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-3);
}

.section-card {
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.pick-row {
  width: 100%;
}

.meeting-picker {
  width: auto;
  min-width: 280px;
  font-weight: 500;
}

.token-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.token-label {
  margin-bottom: 0;
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.token {
  font-size: var(--text-xs);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: 4px var(--sp-2);
  word-break: break-all;
}

.kinds-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.kind-check {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--text-sm);
  cursor: pointer;
}

.hint {
  font-size: var(--text-xs);
}

.code-pre {
  margin: 0;
  width: 100%;
  padding: var(--sp-3) var(--sp-4);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  font-size: var(--text-xs);
  line-height: 1.7;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.brief-pre {
  max-height: 320px;
  overflow-y: auto;
}

.preview-ops {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.preview-pre {
  max-height: 480px;
  overflow-y: auto;
}
</style>
