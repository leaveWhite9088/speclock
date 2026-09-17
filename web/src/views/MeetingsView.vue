<script setup>
/**
 * MeetingsView（/meetings）—— 会议记录主页：业务线 → 会议 树状展示，
 * 树样式用全局 tree.css（与文档树同一套 trow/caret/tkids/tops/k-* 词汇）。
 * 顶部项目切换器（持久化 localStorage，含「全部项目」）+ 项目管理展开区
 *（新建/重命名/删除，删除语义与后端 delete_project 一致：级联文档树与绑定
 * 密钥，业务线不随项目删除）；紧凑搜索行（回车即搜，带类型过滤）；
 * 新建业务线默认挂当前选中项目；会议行内编辑名称 + 日期（TreeNode rename
 * 同款：Enter 保存 / Esc 取消）；上传入口在会议详情页。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client.js'
import { errText } from '../meetingMeta.js'

const router = useRouter()

const series = ref([])
const projects = ref([])
const loading = ref(true)
const pageError = ref('')

// 项目切换（手动切换持久化到 localStorage，独立 key 不与文档树的
// speclock_project 互相干扰；null = 全部项目。无记忆时的默认选中逻辑在 load()）
const PROJECT_KEY = 'speclock_meeting_project'
const selectedProjectId = ref(null)

const visibleSeries = computed(() =>
  selectedProjectId.value
    ? series.value.filter((s) => s.project_id === selectedProjectId.value)
    : series.value,
)

const selectedProjectName = computed(
  () => projects.value.find((p) => p.id === selectedProjectId.value)?.name || '',
)

// 选中具体项目时标题带项目归属，一眼看清是谁的会议记录
const pageTitle = computed(() =>
  selectedProjectId.value ? `会议记录 · ${selectedProjectName.value}` : '会议记录',
)

function pickProject(id) {
  selectedProjectId.value = id
  localStorage.setItem(PROJECT_KEY, id ? String(id) : '')
}

// 项目管理（新建 / 重命名 / 删除）
const managingProjects = ref(false)
const newProjectName = ref('')
const renamingProjectId = ref(null)
const renameProjectName = ref('')
const projectPending = ref(false)
const projectError = ref('')

async function createProject() {
  const name = newProjectName.value.trim()
  if (!name) return
  projectPending.value = true
  projectError.value = ''
  try {
    const res = await api.post('/projects', { name })
    newProjectName.value = ''
    await load()
    pickProject(res.id) // 与文档树一致：新建后选中它
  } catch (e) {
    projectError.value = errText(e)
  } finally {
    projectPending.value = false
  }
}

function startRenameProject(p) {
  renamingProjectId.value = p.id
  renameProjectName.value = p.name
  projectError.value = ''
}

async function saveRenameProject(p) {
  const name = renameProjectName.value.trim()
  if (!name || name === p.name) {
    renamingProjectId.value = null
    return
  }
  projectPending.value = true
  projectError.value = ''
  try {
    await api.put(`/projects/${p.id}`, { name })
    renamingProjectId.value = null
    await load()
  } catch (e) {
    projectError.value = errText(e)
  } finally {
    projectPending.value = false
  }
}

async function removeProject(p) {
  // 文案按后端实际语义（api_admin.delete_project）：级联删文档树与绑定密钥；
  // 有已发布模块或会议业务线时 409 拒绝（会议记录不随项目级联删除）。
  if (
    !window.confirm(
      `删除项目「${p.name}」？将连带删除其文档树（大业务 / 文档 / 模块及版本历史）与绑定该项目的 API key。` +
        `若项目下还有已发布模块或会议业务线，后端会拒绝删除（409）——需先归档模块、并在「会议记录」里删掉对应业务线。`,
    )
  )
    return
  projectPending.value = true
  projectError.value = ''
  try {
    await api.delete(`/projects/${p.id}`)
    if (selectedProjectId.value === p.id) pickProject(null)
    await load()
  } catch (e) {
    projectError.value = errText(e)
  } finally {
    projectPending.value = false
  }
}

const searchQ = ref('')
const searchKind = ref('')

const collapsed = ref(new Set()) // 收起的 series id

const addingSeries = ref(false)
const seriesForm = ref({ project_id: null, name: '' })
const seriesPending = ref(false)
const seriesError = ref('')

const addingMeetingFor = ref(null) // series id
const meetingForm = ref({ name: '', date: '' })
const meetingPending = ref(false)
const meetingError = ref('')

// 会议行内编辑（名称 + 日期同一编辑态，学习 TreeNode 的 rename 模式）
const editingMeetingId = ref(null)
const editForm = ref({ name: '', date: '' })
const editPending = ref(false)
const editError = ref('')

function startEditMeeting(m) {
  editingMeetingId.value = m.id
  editForm.value = { name: m.name, date: m.date || '' }
  editError.value = ''
}

async function saveEditMeeting(m) {
  const name = editForm.value.name.trim()
  if (!name) {
    editError.value = '会议名称不能为空'
    return
  }
  editPending.value = true
  editError.value = ''
  try {
    await api.patch(`/meetings/${m.id}`, {
      name,
      date: editForm.value.date || null, // 清空日期 = 传 null
    })
    editingMeetingId.value = null
    await load()
  } catch (e) {
    editError.value = errText(e)
  } finally {
    editPending.value = false
  }
}

// 行内输入框出现时自动聚焦
const vFocus = { mounted: (el) => el.focus() }

async function load() {
  loading.value = true
  pageError.value = ''
  try {
    ;[series.value, projects.value] = await Promise.all([
      api.get('/meeting-series'),
      api.get('/projects'),
    ])
    const remembered = localStorage.getItem(PROJECT_KEY)
    if (remembered === null) {
      // 无记忆时的默认选中：优先名称含「尚诚购」的项目，只有一个项目时选它，
      // 多个项目才回落「全部项目」（自动默认值不写 localStorage，手动切换才记忆）
      const scg = projects.value.find((p) => p.name.includes('尚诚购'))
      selectedProjectId.value = scg
        ? scg.id
        : projects.value.length === 1
          ? projects.value[0].id
          : null
    } else if (remembered !== '') {
      // 有记忆：选中项目已不存在（被删）时回落到「全部项目」
      const id = Number(remembered)
      selectedProjectId.value = projects.value.some((p) => p.id === id) ? id : null
    } else {
      selectedProjectId.value = null // 手动选过「全部项目」
    }
  } catch (e) {
    pageError.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function toggleSeries(id) {
  const next = new Set(collapsed.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsed.value = next
}

function docsSummary(s) {
  const reqs = s.docs?.find((d) => d.kind === 'requirements')?.item_count
  const facts = s.docs?.find((d) => d.kind === 'facts')?.item_count
  const parts = []
  if (reqs != null) parts.push(`需求 ${reqs}`)
  if (facts != null) parts.push(`事实 ${facts}`)
  return parts.join(' · ')
}

function goSearch() {
  const q = searchQ.value.trim()
  const query = {}
  if (q) query.q = q
  if (searchKind.value) query.kind = searchKind.value
  router.push({ path: '/meetings/search', query })
}

function startAddSeries() {
  addingSeries.value = true
  seriesError.value = ''
  // 选中具体项目时新业务线默认挂它，表单里不再让手选
  seriesForm.value = {
    project_id: selectedProjectId.value ?? projects.value[0]?.id ?? null,
    name: '',
  }
}

async function submitSeries() {
  const name = seriesForm.value.name.trim()
  if (!name || !seriesForm.value.project_id) return
  seriesPending.value = true
  seriesError.value = ''
  try {
    await api.post('/meeting-series', {
      project_id: seriesForm.value.project_id,
      name,
    })
    addingSeries.value = false
    seriesForm.value = { project_id: null, name: '' }
    await load()
  } catch (e) {
    seriesError.value = errText(e)
  } finally {
    seriesPending.value = false
  }
}

function startAddMeeting(seriesId) {
  addingMeetingFor.value = seriesId
  meetingForm.value = { name: '', date: '' }
  meetingError.value = ''
  collapsed.value = new Set([...collapsed.value].filter((id) => id !== seriesId))
}

async function submitMeeting(seriesId) {
  const name = meetingForm.value.name.trim()
  if (!name) return
  meetingPending.value = true
  meetingError.value = ''
  try {
    await api.post('/meetings', {
      series_id: seriesId,
      name,
      date: meetingForm.value.date || null,
    })
    addingMeetingFor.value = null
    meetingForm.value = { name: '', date: '' }
    await load()
  } catch (e) {
    meetingError.value = errText(e)
  } finally {
    meetingPending.value = false
  }
}

async function removeMeeting(m) {
  if (
    !window.confirm(
      `删除会议「${m.name}」？其全部 ${m.file_count} 个文件及版本历史会一并删除，不可恢复。`,
    )
  )
    return
  pageError.value = ''
  try {
    await api.delete(`/meetings/${m.id}`)
    await load()
  } catch (e) {
    pageError.value = errText(e)
  }
}

async function removeSeries(s) {
  if (
    !window.confirm(
      `删除业务线「${s.name}」？其下全部 ${s.meetings.length} 个会议及所有文件、版本历史会一并删除，不可恢复。`,
    )
  )
    return
  pageError.value = ''
  try {
    await api.delete(`/meeting-series/${s.id}`)
    await load()
  } catch (e) {
    pageError.value = errText(e)
  }
}
</script>

<template>
  <div class="page meetings-page">
    <p class="page-eyebrow">SpecLock · Meetings</p>
    <div class="head">
      <h1 class="page-title">{{ pageTitle }}</h1>
      <div class="head-ops">
        <select
          v-if="projects.length"
          class="input project-picker"
          :value="selectedProjectId"
          @change="pickProject(Number($event.target.value) || null)"
          aria-label="选择项目"
        >
          <option :value="null">全部项目</option>
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <button
          type="button"
          class="btn"
          @click="((managingProjects = !managingProjects), (projectError = ''), (renamingProjectId = null))"
        >
          管理项目
        </button>
        <button type="button" class="btn btn-primary" @click="startAddSeries">
          新建业务线
        </button>
      </div>
    </div>
    <p class="page-desc">
      按 业务线 → 会议 组织会议纪要。精准需求与业务事实文件会自动切块成可检索、可逐条编辑的条目。
    </p>

    <!-- 项目管理展开区 -->
    <div v-if="managingProjects" class="card composer-card manage-panel">
      <div v-for="p in projects" :key="p.id" class="mrow">
        <template v-if="renamingProjectId === p.id">
          <input
            class="input mrow-input"
            v-model="renameProjectName"
            @keyup.enter="saveRenameProject(p)"
            @keyup.esc="renamingProjectId = null"
            v-focus
          />
          <button
            type="button"
            class="btn"
            :disabled="projectPending"
            @click="saveRenameProject(p)"
          >
            保存
          </button>
          <button type="button" class="btn" @click="renamingProjectId = null">取消</button>
        </template>
        <template v-else>
          <span class="pname">{{ p.name }}</span>
          <span class="mrow-ops">
            <button type="button" class="btn" @click="startRenameProject(p)">重命名</button>
            <button
              type="button"
              class="btn btn-danger"
              :disabled="projectPending"
              @click="removeProject(p)"
            >
              删除
            </button>
          </span>
        </template>
      </div>
      <div class="mrow">
        <input
          class="input mrow-input"
          v-model="newProjectName"
          placeholder="新项目名称"
          @keyup.enter="createProject"
        />
        <button
          type="button"
          class="btn btn-primary"
          :disabled="projectPending"
          @click="createProject"
        >
          新建项目
        </button>
      </div>
      <p class="muted manage-hint">
        删除项目只连带删除其文档树与绑定密钥；项目下若还有会议业务线会被拒绝（409），请先在下方树里删除对应业务线。
      </p>
      <p v-if="projectError" class="error-text" role="alert">{{ projectError }}</p>
    </div>

    <!-- 紧凑搜索行：回车即搜 -->
    <div class="search-row">
      <input
        class="input"
        v-model="searchQ"
        placeholder="搜索需求 / 事实条目关键词，如：计划表、口径…"
        @keyup.enter="goSearch"
      />
      <select class="input search-kind" v-model="searchKind" aria-label="条目类型">
        <option value="">全部类型</option>
        <option value="req">精准需求</option>
        <option value="fact">业务事实</option>
      </select>
      <button type="button" class="btn btn-primary search-btn" @click="goSearch">搜索</button>
    </div>

    <p v-if="pageError" class="error-text page-err" role="alert">{{ pageError }}</p>
    <div v-if="loading" class="muted loading">正在加载…</div>

    <div v-else-if="!series.length" class="card empty">
      <p class="empty-title">还没有业务线</p>
      <p class="muted">业务线是会议的顶层分组（如"采购部分"），先建一个业务线，再往里加会议。</p>
    </div>

    <p v-else-if="!visibleSeries.length" class="muted empty-filter">
      项目「{{ selectedProjectName }}」下还没有业务线，点右上角「新建业务线」创建一个。
    </p>

    <div v-if="addingSeries" class="card composer-card">
      <template v-if="selectedProjectId">
        <label class="label">所属项目</label>
        <p class="locked-project">{{ selectedProjectName }}<span class="muted">（当前选中项目）</span></p>
      </template>
      <template v-else>
        <label class="label">所属项目</label>
        <select class="input" v-model="seriesForm.project_id">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </template>
      <label class="label">业务线名称</label>
      <input
        class="input"
        v-model="seriesForm.name"
        placeholder="如：采购部分"
        @keyup.enter="submitSeries"
        @keyup.esc="addingSeries = false"
        v-focus
      />
      <div class="composer-ops">
        <button
          type="button"
          class="btn btn-primary"
          :disabled="seriesPending"
          @click="submitSeries"
        >
          创建业务线
        </button>
        <button type="button" class="btn" @click="addingSeries = false">取消</button>
      </div>
      <p v-if="seriesError" class="error-text" role="alert">{{ seriesError }}</p>
    </div>

    <!-- 业务线 → 会议 树（全局 tree.css 词汇，与文档树同款） -->
    <ul v-if="visibleSeries.length" class="mtree">
      <li v-for="s in visibleSeries" :key="s.id" class="tnode k-domain">
        <div class="trow">
          <button
            type="button"
            class="caret"
            :aria-label="collapsed.has(s.id) ? '展开' : '收起'"
            @click="toggleSeries(s.id)"
          >
            {{ collapsed.has(s.id) ? '▸' : '▾' }}
          </button>
          <RouterLink class="tname" :to="`/meetings/series/${s.id}`">{{ s.name }}</RouterLink>
          <span class="muted tmeta">{{ s.meetings.length }} 个会议</span>
          <span v-if="s.docs?.length" class="muted tmeta">
            汇总：{{ docsSummary(s) }}
          </span>
          <span class="tops">
            <button type="button" class="btn btn-mini" @click="startAddMeeting(s.id)">
              新建会议
            </button>
            <button type="button" class="btn btn-mini btn-danger" @click="removeSeries(s)">
              删除
            </button>
          </span>
        </div>

        <ul v-if="!collapsed.has(s.id)" class="tkids">
          <li v-for="m in s.meetings" :key="m.id" class="tnode k-document">
            <div class="trow">
              <span class="caret-sp"></span>
              <template v-if="editingMeetingId === m.id">
                <input
                  class="input rename-input"
                  v-model="editForm.name"
                  @keyup.enter="saveEditMeeting(m)"
                  @keyup.esc="editingMeetingId = null"
                  v-focus
                />
                <input
                  class="input date-input"
                  type="date"
                  v-model="editForm.date"
                  title="会议日期（清空 = 未定日期）"
                  @keyup.esc="editingMeetingId = null"
                />
                <button
                  type="button"
                  class="btn btn-mini btn-primary"
                  :disabled="editPending"
                  @click="saveEditMeeting(m)"
                >
                  保存
                </button>
                <button type="button" class="btn btn-mini" @click="editingMeetingId = null">
                  取消
                </button>
              </template>
              <template v-else>
                <RouterLink class="tname" :to="`/meetings/${m.id}`">{{ m.name }}</RouterLink>
                <button
                  type="button"
                  class="tmeta tmeta-btn muted"
                  :class="{ 'is-unset': !m.date }"
                  title="点击修改日期"
                  @click="startEditMeeting(m)"
                >
                  {{ m.date || '未定日期' }}
                </button>
                <span class="muted tmeta">{{ m.file_count }} 个文件</span>
                <span class="tops">
                  <button type="button" class="btn btn-mini" @click="startEditMeeting(m)">
                    改名
                  </button>
                  <button type="button" class="btn btn-mini btn-danger" @click="removeMeeting(m)">
                    删除
                  </button>
                </span>
              </template>
            </div>
            <p v-if="editingMeetingId === m.id && editError" class="error-text terror" role="alert">
              {{ editError }}
            </p>
          </li>

          <li v-if="addingMeetingFor === s.id" class="trow add-row">
            <span class="caret-sp"></span>
            <input
              class="input add-input"
              v-model="meetingForm.name"
              placeholder="会议名称，如：采购第5次业务交流"
              @keyup.enter="submitMeeting(s.id)"
              @keyup.esc="addingMeetingFor = null"
              v-focus
            />
            <input
              class="input date-input"
              type="date"
              v-model="meetingForm.date"
              title="会议日期（可选；留空则后端从目录名解析）"
            />
            <button
              type="button"
              class="btn btn-mini btn-primary"
              :disabled="meetingPending"
              @click="submitMeeting(s.id)"
            >
              创建会议
            </button>
            <button type="button" class="btn btn-mini" @click="addingMeetingFor = null">
              取消
            </button>
          </li>
          <li v-if="addingMeetingFor === s.id && meetingError" class="trow">
            <span class="caret-sp"></span>
            <p class="error-text" role="alert">{{ meetingError }}</p>
          </li>

          <li v-if="!s.meetings.length && addingMeetingFor !== s.id" class="trow empty-row">
            <span class="caret-sp"></span>
            <span class="muted">还没有会议，悬停业务线行点「新建会议」。</span>
          </li>
        </ul>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
}

.head-ops {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.project-picker {
  width: auto;
  min-width: 140px;
  font-weight: 500;
}

/* ---------- 项目管理展开区 ---------- */

.manage-panel {
  max-width: 560px;
}

.mrow {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.mrow + .mrow {
  border-top: 1px solid var(--hairline);
  padding-top: var(--sp-2);
}

.mrow-input {
  max-width: 260px;
  padding: 4px var(--sp-2);
}

.pname {
  font-size: var(--text-sm);
  font-weight: 500;
  flex: 1;
  min-width: 0;
}

.mrow-ops {
  display: flex;
  gap: var(--sp-2);
}

.manage-hint {
  font-size: var(--text-xs);
}

.locked-project {
  font-size: var(--text-sm);
  font-weight: 500;
}

.empty-filter {
  margin-top: var(--sp-5);
}

.page-err {
  margin-top: var(--sp-3);
}

.loading {
  margin-top: var(--sp-6);
}

/* ---------- 紧凑搜索行 ---------- */

.search-row {
  margin-top: var(--sp-4);
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  max-width: 640px;
}

.search-kind {
  width: auto;
  flex: none;
}

.search-btn {
  flex: none;
}

/* ---------- 空态与新建业务线 ---------- */

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

.composer-card {
  margin-top: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--sp-2);
  max-width: 420px;
}

.composer-ops {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}

/* ---------- 树布局（树词汇本体在全局 styles/tree.css） ---------- */

.mtree {
  margin-top: var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

/* 会议树的 meta 是纯文本（文档树的 meta 是自带字号的组件），补一个字号 */
.tmeta {
  font-size: var(--text-xs);
}

/* 可点击的日期 meta：无边框按钮，悬停提示可编辑 */
.tmeta-btn {
  appearance: none;
  border: none;
  background: none;
  padding: 1px var(--sp-1);
  font: inherit;
  font-size: var(--text-xs);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition:
    color var(--dur) var(--ease),
    background var(--dur) var(--ease);
}

.tmeta-btn:hover {
  color: var(--contract);
  background: var(--contract-wash);
}

.tmeta-btn.is-unset {
  font-style: italic;
}

.add-input {
  max-width: 300px;
  padding: 4px var(--sp-2);
}

.date-input {
  width: auto;
  padding: 4px var(--sp-2);
}

.empty-row {
  font-size: var(--text-xs);
}
</style>
