<script setup>
/**
 * BlockEditView（/blocks/:id/edit）—— 草稿编辑 + 双态发布流程。
 * 保存草稿 PUT /blocks/:id；发布先 dryRun 预览（不落库），非破坏性走 fastTrack
 * 确认发布，破坏性需勾选知晓后 confirm 发布；422 结构校验逐条列出并锚点定位。
 */
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'
import BlockStatusBadge from '../components/BlockStatusBadge.vue'
import BlockApiCard from '../components/BlockApiCard.vue'
import BlockDeltaGroups from '../components/BlockDeltaGroups.vue'
import BlockMd from '../components/BlockMd.vue'

const route = useRoute()
const router = useRouter()
const bid = route.params.id

const loading = ref(true)
const loadError = ref('')
const block = ref(null)
const versions = ref([])
const form = ref(null)

const contentTab = ref('edit')
const nfrTab = ref('edit')

const saving = ref(false)
const savedAt = ref('')
const saveError = ref('')

const changeNote = ref('')
const previewing = ref(false)
const publishing = ref(false)
const preview = ref(null)
const ackBreaking = ref(false)
const gateProblems = ref([])
const publishError = ref('')
const flagged = ref('')

function errText(e) {
  const d = e && e.detail
  if (!d) return '请求失败，请检查网络后重试。'
  if (typeof d === 'string') return d
  return d.error || JSON.stringify(d)
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [d, vs] = await Promise.all([
      api.get(`/blocks/${bid}/draft`),
      api.get(`/blocks/${bid}/versions`),
    ])
    block.value = d
    versions.value = [...vs].sort((a, b) =>
      String(a.published_at || '').localeCompare(String(b.published_at || '')),
    )
    form.value = {
      title: d.title || '',
      summary: d.summary || '',
      content_md: d.content_md || '',
      rules: (d.rules || []).map((r) => ({ name: r.name || '', detail: r.detail || '' })),
      apis: (d.apis || []).map((a) => ({
        name: a.name || '',
        api: a.api || '',
        desc: a.desc || '',
        request: a.request || [],
        response: a.response || [],
      })),
      nfr_md: d.nfr_md || '',
    }
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function addRule() {
  form.value.rules.push({ name: '', detail: '' })
}

function removeRule(i) {
  form.value.rules.splice(i, 1)
}

function addApi() {
  form.value.apis.push({ name: '', api: '', desc: '', request: [], response: [] })
}

function removeApi(i) {
  form.value.apis.splice(i, 1)
}

async function save() {
  saving.value = true
  saveError.value = ''
  savedAt.value = ''
  try {
    await api.put(`/blocks/${bid}`, { ...form.value })
    savedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    return true
  } catch (e) {
    saveError.value = errText(e)
    return false
  } finally {
    saving.value = false
  }
}

// ---------- 发布 ----------

function anchorFor(text) {
  if (text.includes('背景')) return 'content'
  if (text.includes('规则')) return 'rules'
  if (text.includes('API')) return 'apis'
  return ''
}

async function flagSection(anchor) {
  flagged.value = anchor
  await nextTick()
  document
    .getElementById(`sec-${anchor}`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  setTimeout(() => {
    if (flagged.value === anchor) flagged.value = ''
  }, 1800)
}

function handlePublishError(e) {
  const d = e && e.detail
  if (e.status === 422 && d && typeof d === 'object' && Array.isArray(d.missing)) {
    gateProblems.value = d.missing.map((m) => ({ text: m, anchor: anchorFor(m) }))
    publishError.value = ''
  } else {
    // 409（秒批遇破坏性）等：展示后端原文
    publishError.value = errText(e)
    gateProblems.value = []
  }
}

async function runPreview() {
  preview.value = null
  gateProblems.value = []
  publishError.value = ''
  ackBreaking.value = false
  // 预览针对已保存的草稿：先保存，保存失败（如 desc 缺失的 422）则不继续
  const ok = await save()
  if (!ok) return
  previewing.value = true
  try {
    preview.value = await api.post(`/blocks/${bid}/publish`, {
      change_note: changeNote.value,
      dryRun: true,
    })
    await nextTick()
    document
      .getElementById('publish-preview')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (e) {
    handlePublishError(e)
  } finally {
    previewing.value = false
  }
}

async function confirmPublish() {
  if (!preview.value) return
  publishing.value = true
  publishError.value = ''
  try {
    const body = preview.value.breaking
      ? { change_note: changeNote.value, confirm: true }
      : { change_note: changeNote.value, fastTrack: true }
    await api.post(`/blocks/${bid}/publish`, body)
    router.push({ name: 'block', params: { id: bid } })
  } catch (e) {
    preview.value = null
    handlePublishError(e)
  } finally {
    publishing.value = false
  }
}

function cancelPreview() {
  preview.value = null
  ackBreaking.value = false
}

const previewRulesDelta = computed(() =>
  preview.value
    ? {
        rules_added: preview.value.delta.rules_added || [],
        rules_modified: preview.value.delta.rules_modified || [],
        rules_removed: preview.value.delta.rules_removed || [],
      }
    : null,
)
</script>

<template>
  <div class="page edit-page">
    <div v-if="loading" class="muted">正在加载草稿…</div>

    <div v-else-if="loadError" class="card load-fail">
      <p class="error-text" role="alert">{{ loadError }}</p>
      <button type="button" class="btn" @click="load">重新加载</button>
    </div>

    <template v-else-if="block && form">
      <p class="page-eyebrow">接口块 · 草稿编辑</p>
      <p class="crumb muted">
        <RouterLink to="/">文档树</RouterLink> ›
        <RouterLink :to="`/documents/${block.document_id}`">所属文档</RouterLink> ›
        {{ block.title }}
      </p>

      <div class="edit-head">
        <h1 class="page-title">{{ block.title }}</h1>
        <BlockStatusBadge :status="block.status" />
        <VersionChip
          v-if="block.current_published_version"
          :version="block.current_published_version"
        />
        <span class="head-links">
          <RouterLink
            v-if="block.current_published_version"
            class="btn btn-mini"
            :to="`/blocks/${bid}`"
            >查看</RouterLink
          >
          <RouterLink class="btn btn-mini" :to="`/blocks/${bid}/diff`"
            >版本对比</RouterLink
          >
        </span>
      </div>

      <section class="card sec" id="sec-base">
        <h2 class="sec-title">基本信息</h2>
        <label class="label">模块名</label>
        <input class="input" v-model="form.title" />
        <label class="label mt">摘要</label>
        <input
          class="input"
          v-model="form.summary"
          placeholder="一句话说明这个模块做什么"
        />
      </section>

      <section
        class="card sec"
        id="sec-content"
        :class="{ flag: flagged === 'content' }"
      >
        <div class="sec-head">
          <h2 class="sec-title">
            业务背景与流程 <span class="req">必填 · 至少 20 字</span>
          </h2>
          <span class="tabs">
            <button
              type="button"
              class="tab"
              :class="{ on: contentTab === 'edit' }"
              @click="contentTab = 'edit'"
              >编辑</button
            >
            <button
              type="button"
              class="tab"
              :class="{ on: contentTab === 'preview' }"
              @click="contentTab = 'preview'"
              >预览</button
            >
          </span>
        </div>
        <textarea
          v-if="contentTab === 'edit'"
          class="input md-input mono"
          v-model="form.content_md"
          rows="12"
          placeholder="用 Markdown 写清楚业务背景与流程"
          spellcheck="false"
        ></textarea>
        <BlockMd v-else :source="form.content_md" />
      </section>

      <section class="card sec" id="sec-rules" :class="{ flag: flagged === 'rules' }">
        <h2 class="sec-title">业务规则清单 <span class="req">至少 1 条</span></h2>
        <table v-if="form.rules.length" class="rules-table">
          <thead>
            <tr>
              <th class="col-name">规则名</th>
              <th>规则详述</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, ri) in form.rules" :key="ri">
              <td>
                <input
                  class="input"
                  v-model="r.name"
                  placeholder="规则名，如 销售额口径"
                />
              </td>
              <td><input class="input" v-model="r.detail" placeholder="规则详述" /></td>
              <td class="rowops">
                <button
                  type="button"
                  class="btn btn-mini btn-danger"
                  @click="removeRule(ri)"
                  >删</button
                >
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">还没有规则。规则是发布关口，至少写 1 条。</p>
        <button type="button" class="btn btn-mini" @click="addRule">+ 新增规则</button>
      </section>

      <section class="card sec" id="sec-apis" :class="{ flag: flagged === 'apis' }">
        <h2 class="sec-title">API 列表</h2>
        <div class="api-list">
          <BlockApiCard
            v-for="(a, ai) in form.apis"
            :key="ai"
            :api="a"
            :index="ai"
            @remove="removeApi(ai)"
          />
        </div>
        <p v-if="!form.apis.length" class="muted">
          还没有 API。模块可以不挂 API，只承载业务规则与背景叙述。
        </p>
        <button type="button" class="btn btn-mini" @click="addApi">+ 新增 API</button>
      </section>

      <section class="card sec" id="sec-nfr">
        <div class="sec-head">
          <h2 class="sec-title">非功能性需求</h2>
          <span class="tabs">
            <button
              type="button"
              class="tab"
              :class="{ on: nfrTab === 'edit' }"
              @click="nfrTab = 'edit'"
              >编辑</button
            >
            <button
              type="button"
              class="tab"
              :class="{ on: nfrTab === 'preview' }"
              @click="nfrTab = 'preview'"
              >预览</button
            >
          </span>
        </div>
        <textarea
          v-if="nfrTab === 'edit'"
          class="input md-input mono"
          v-model="form.nfr_md"
          rows="5"
          placeholder="性能、可用性、安全等非功能性约束（Markdown）"
          spellcheck="false"
        ></textarea>
        <BlockMd v-else :source="form.nfr_md" />
      </section>

      <div class="action-bar">
        <button
          type="button"
          class="btn btn-primary"
          :disabled="saving"
          @click="save"
        >
          {{ saving ? '正在保存…' : '保存草稿' }}
        </button>
        <span v-if="savedAt" class="saved-ok">草稿已保存 {{ savedAt }}</span>
        <span v-if="saveError" class="error-text" role="alert">{{ saveError }}</span>
      </div>

      <section class="card sec publish-sec">
        <h2 class="sec-title">发布</h2>
        <p class="muted publish-desc">
          发布把当前草稿固化为不可变版本，并派生所属文档的新版本。先预览，确认
          delta 后再真正发布。
        </p>
        <label class="label">变更说明</label>
        <input
          class="input note-input"
          v-model="changeNote"
          placeholder="这次改了什么（写进版本历史）"
        />
        <div class="publish-ops">
          <button
            type="button"
            class="btn btn-primary"
            :disabled="previewing || publishing || saving"
            @click="runPreview"
          >
            {{ previewing ? '正在预览…' : '预览发布' }}
          </button>
          <span class="muted publish-hint">预览会先保存草稿，再做 dryRun，不落库。</span>
        </div>

        <div v-if="gateProblems.length" class="gate" role="alert">
          <strong>结构不完备，补齐以下各项后再发布：</strong>
          <ul>
            <li v-for="(p, i) in gateProblems" :key="i">
              <a v-if="p.anchor" href="#" @click.prevent="flagSection(p.anchor)">{{
                p.text
              }}</a>
              <span v-else>{{ p.text }}</span>
            </li>
          </ul>
        </div>
        <p v-if="publishError" class="error-text" role="alert">{{ publishError }}</p>

        <div v-if="preview" id="publish-preview" class="preview card">
          <div class="preview-head">
            <strong>确认发布</strong>
            <span class="arrow mono">→</span>
            <VersionChip
              :version="preview.version"
              :status="preview.breaking ? 'breaking' : 'published'"
            />
            <span v-if="preview.breaking" class="badge-breaking">破坏性变更</span>
            <span v-else class="badge-safe">非破坏性</span>
            <span class="cnt cnt-add">新增 {{ preview.delta.added.length }}</span>
            <span class="cnt cnt-mod">修改 {{ preview.delta.modified.length }}</span>
            <span class="cnt cnt-del">删除 {{ preview.delta.removed.length }}</span>
            <span class="muted doc-ver">
              文档版本 → <VersionChip :version="preview.document_version" />
            </span>
          </div>

          <BlockDeltaGroups :groups="preview.groups" :rules-delta="previewRulesDelta" />

          <div v-if="preview.breaking" class="breaking-warn">
            <strong>破坏性变更警告</strong>：以上删除 / 修改会让正在消费旧版本的下游失效。发布后版本号为
            MAJOR 升级（v{{ preview.version }}）。
            <label class="ack">
              <input type="checkbox" v-model="ackBreaking" />
              我已知晓破坏性影响
            </label>
          </div>

          <div class="preview-ops">
            <button
              type="button"
              class="btn btn-primary"
              :disabled="publishing || (preview.breaking && !ackBreaking)"
              @click="confirmPublish"
            >
              {{ publishing ? '正在发布…' : `确认发布 v${preview.version}` }}
            </button>
            <button type="button" class="btn" @click="cancelPreview">取消</button>
          </div>
        </div>
      </section>

      <section class="sec history">
        <h2 class="sec-title">历史版本</h2>
        <ul v-if="versions.length" class="ver-list">
          <li v-for="v in versions" :key="v.version">
            <VersionChip :version="v.version" />
            <span class="ver-note">{{ v.change_note || '（无变更说明）' }}</span>
            <span class="muted ver-time">{{ v.published_at }}</span>
          </li>
        </ul>
        <p v-else class="muted">还没有已发布版本。补齐内容后从上方「预览发布」开始。</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.crumb {
  font-size: var(--text-sm);
  margin-bottom: var(--sp-2);
}

.edit-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-bottom: var(--sp-5);
}

.head-links {
  margin-left: auto;
  display: inline-flex;
  gap: var(--sp-2);
}

.btn-mini {
  padding: 3px var(--sp-2);
  font-size: var(--text-xs);
}

.load-fail {
  margin-top: var(--sp-5);
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.sec {
  padding: var(--sp-4) var(--sp-5);
  margin-bottom: var(--sp-4);
  transition: border-color var(--dur) var(--ease);
}

.sec.flag {
  border-color: var(--danger);
  box-shadow: 0 0 0 2px rgba(196, 53, 28, 0.15);
}

.sec-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}

.sec-title {
  font-size: var(--text-lg);
  font-weight: 600;
}

.sec-head .sec-title {
  margin: 0;
}

.sec > .sec-title {
  margin-bottom: var(--sp-3);
}

.req {
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--danger);
  margin-left: var(--sp-2);
}

.mt {
  margin-top: var(--sp-3);
}

.tabs {
  display: inline-flex;
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  overflow: hidden;
}

.tab {
  appearance: none;
  border: none;
  background: var(--card);
  padding: 3px var(--sp-3);
  font-size: var(--text-xs);
  color: var(--ink-2);
  cursor: pointer;
}

.tab.on {
  background: var(--contract-wash);
  color: var(--contract);
  font-weight: 500;
}

.md-input {
  width: 100%;
  resize: vertical;
  font-size: var(--text-sm);
  line-height: 1.7;
}

.rules-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: var(--sp-2);
}

.rules-table th {
  text-align: left;
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ink-2);
  padding: 0 var(--sp-2) var(--sp-1) 0;
  border-bottom: 1px solid var(--hairline);
}

.rules-table td {
  padding: var(--sp-1) var(--sp-2) var(--sp-1) 0;
  vertical-align: middle;
}

.col-name {
  width: 220px;
}

.api-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin-bottom: var(--sp-2);
}

.api-list + .muted {
  margin-bottom: var(--sp-2);
}

.action-bar {
  position: sticky;
  bottom: var(--sp-4);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  background: var(--card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  margin-bottom: var(--sp-4);
  z-index: 5;
}

.saved-ok {
  color: var(--success);
  font-size: var(--text-sm);
}

.publish-desc {
  margin-bottom: var(--sp-3);
  font-size: var(--text-sm);
}

.note-input {
  max-width: 420px;
  margin-bottom: var(--sp-3);
}

.publish-ops {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.publish-hint {
  font-size: var(--text-xs);
}

.gate {
  margin-top: var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--danger);
  border-radius: var(--radius);
  background: var(--card);
}

.gate ul {
  margin-top: var(--sp-2);
  padding-left: var(--sp-5);
  list-style: disc;
}

.gate li {
  font-size: var(--text-sm);
  margin-bottom: var(--sp-1);
}

.preview {
  margin-top: var(--sp-4);
  padding: var(--sp-4);
  border-color: var(--contract);
}

.preview-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin-bottom: var(--sp-3);
}

.arrow {
  color: var(--ink-2);
}

.badge-breaking {
  font-size: var(--text-xs);
  color: var(--danger);
  border: 1px solid var(--danger);
  border-radius: var(--radius-sm);
  padding: 1px 7px;
}

.badge-safe {
  font-size: var(--text-xs);
  color: var(--success);
  border: 1px solid var(--success);
  border-radius: var(--radius-sm);
  padding: 1px 7px;
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

.doc-ver {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--text-xs);
}

.breaking-warn {
  margin-top: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--danger);
  border-radius: var(--radius);
  font-size: var(--text-sm);
}

.ack {
  display: block;
  margin-top: var(--sp-2);
  font-size: var(--text-sm);
  cursor: pointer;
}

.preview-ops {
  margin-top: var(--sp-4);
  display: flex;
  gap: var(--sp-2);
}

.history {
  margin-top: var(--sp-2);
}

.ver-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.ver-list li {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-size: var(--text-sm);
}

.ver-time {
  font-size: var(--text-xs);
}
</style>
