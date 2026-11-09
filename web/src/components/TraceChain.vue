<script setup>
/**
 * 追溯链：审核单 → Commit → 受影响的模块 / 小业务（版本从哪变到哪）→ 现在的执行状态。
 * 数据来自 trace.js 的 buildTrace；本组件只负责展示。
 */
import { ref } from 'vue'
import { COMMIT_STATUS, LEVEL, label } from '../labels.js'
import { changeWhere, charDiff } from '../reviewDiff.js'
import { fmtTime } from '../time.js'
import VersionChip from './VersionChip.vue'
import ExecStatusBadge from './ExecStatusBadge.vue'
import KeyChip from './KeyChip.vue'

defineProps({
  commits: { type: Array, required: true },
  internal: { type: Boolean, default: false },
})

const showOps = ref({})
function toggleOps(id) {
  showOps.value = { ...showOps.value, [id]: !showOps.value[id] }
}
</script>

<template>
  <ol class="chain">
    <li v-for="c in commits" :key="c.id" class="commit">
      <div class="commit-head">
        <strong>Commit #{{ c.seq }}</strong>
        <span v-if="c.status !== 'applied' || c.review" class="cstatus" :class="`is-${c.status}`">{{ label(COMMIT_STATUS, c.status) }}</span>
        <span class="note">{{ c.note }}</span>
        <span class="muted small"><KeyChip :hint="c.createdBy" /> · {{ fmtTime(c.createdAt) }}</span>
      </div>
      <p class="muted small">覆盖验收条件：{{ c.covers.join('、') || '无' }}</p>

      <!-- 语义复核：字变了、意思没变的小改动，另一个角色复核通过才生效 -->
      <div v-if="c.review" class="review" :class="`is-${c.status}`">
        <p v-if="c.status === 'pending_review'" class="review-head">
          这批改动只是单条条目里的小幅文字修改，提交者声明意思没变。<strong>规格暂时没有变</strong>，等另一个角色（扫描 Agent 或人）复核通过才会生效。
        </p>
        <p v-else-if="c.review.decision === 'approved'" class="review-head">
          已由 <KeyChip :hint="c.review.reviewed_by" /> 复核通过（{{ fmtTime(c.review.reviewed_at) }}）。
        </p>
        <p v-else-if="c.review.decision === 'rejected'" class="review-head">
          已由 <KeyChip :hint="c.review.reviewed_by" /> 复核<strong>不通过</strong>（{{ fmtTime(c.review.reviewed_at) }}），这批改动没有生效。
        </p>
        <p v-if="c.review.reason" class="review-reason">复核理由：{{ c.review.reason }}<template v-if="c.review.evidence">（原话：「{{ c.review.evidence }}」）</template></p>
        <ul class="changes">
          <li v-for="(ch, i) in c.review.changes || []" :key="i">
            <span class="where muted small">{{ changeWhere(ch) }}</span>
            <span class="diff">
              <template v-for="(seg, j) in charDiff(ch.old, ch.new)" :key="j">
                <del v-if="seg.kind === 'del'">{{ seg.text }}</del><ins v-else-if="seg.kind === 'add'">{{ seg.text }}</ins><template v-else>{{ seg.text }}</template>
              </template>
            </span>
          </li>
        </ul>
      </div>

      <ul class="effects">
        <li v-for="s in c.createdStructure" :key="`s-${s.type}-${s.id}`" class="effect">
          <span class="verb">新建</span>{{ s.typeText }}
          <RouterLink v-if="s.type === 'capability'" :to="`/capabilities/${s.id}`">{{ s.title }}</RouterLink>
          <span v-else class="strong">{{ s.title }}</span>
        </li>

        <li v-for="m in c.meta" :key="`meta-${m.type}-${m.id}`" class="effect">
          <span class="verb">修改</span>{{ m.typeText }}
          <RouterLink v-if="m.type === 'capability'" :to="`/capabilities/${m.id}`">{{ m.title }}</RouterLink>
          <RouterLink v-else-if="m.type === 'block'" :to="`/blocks/${m.id}`">{{ m.title }}</RouterLink>
          <span v-else class="strong">{{ m.title }}</span>
          <span class="muted small">{{ m.fields.join('、') }}（不产生新版本）</span>
        </li>

        <li v-for="b in c.blocks" :key="`b-${b.blockId}`" class="effect">
          <span class="verb">{{ b.created ? '新建' : '更新' }}</span>模块
          <RouterLink :to="`/blocks/${b.blockId}?version=${b.version}`">{{ b.title }}</RouterLink>
          <span class="versions">
            <template v-if="b.prevVersion"><VersionChip :version="b.prevVersion" /> → </template>
            <VersionChip :version="b.version" />
          </span>
          <span class="muted small">{{ label(LEVEL, b.level) }}</span>
          <ExecStatusBadge :status="b.executionStatus" />
        </li>

        <li v-for="cv in c.capabilities" :key="`c-${cv.id}`" class="effect">
          <span class="verb">派生</span>小业务
          <RouterLink :to="`/capabilities/${cv.id}`">{{ cv.title }}</RouterLink>
          <span class="versions">
            <template v-if="cv.prevVersion"><VersionChip :version="cv.prevVersion" /> → </template>
            <VersionChip :version="cv.version" />
          </span>
        </li>

        <li v-for="m in c.moved" :key="`m-${m.id}`" class="effect">
          <span class="verb">搬动</span>模块 <RouterLink :to="`/blocks/${m.id}`">{{ m.title }}</RouterLink>
          <span class="muted small">换了所属小业务，身份与历史版本不变</span>
        </li>
        <li v-for="m in c.archived" :key="`a-${m.id}`" class="effect">
          <span class="verb warn">归档</span>模块 <RouterLink :to="`/blocks/${m.id}`">{{ m.title }}</RouterLink>
        </li>
        <li v-for="m in c.restored" :key="`r-${m.id}`" class="effect">
          <span class="verb">恢复</span>模块 <RouterLink :to="`/blocks/${m.id}`">{{ m.title }}</RouterLink>
        </li>
      </ul>

      <button type="button" class="btn btn-mini" @click="toggleOps(c.id)">
        {{ showOps[c.id] ? '收起 ops' : '查看 ops' }}
      </button>
      <pre v-if="showOps[c.id]" class="ops-pre mono">{{ JSON.stringify(c.ops, null, 2) }}</pre>
    </li>
  </ol>
</template>

<style scoped>
.chain {
  margin-top: var(--sp-3);
  padding-left: var(--sp-4);
  border-left: 2px solid var(--hairline);
}

.commit {
  position: relative;
  padding: 0 0 var(--sp-5) var(--sp-4);
}

.commit:last-child {
  padding-bottom: 0;
}

.commit::before {
  content: '';
  position: absolute;
  left: calc(-1 * var(--sp-4) - 6px);
  top: 6px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--contract);
  border: 2px solid var(--card);
}

.commit-head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.small {
  font-size: var(--text-xs);
}

.effects {
  margin: var(--sp-2) 0;
}

.effect {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  padding: 3px 0;
  font-size: var(--text-sm);
}

.verb {
  display: inline-block;
  min-width: 2.4em;
  padding: 0 var(--sp-2);
  font-size: var(--text-xs);
  text-align: center;
  border-radius: var(--radius-sm);
  background: var(--contract-wash);
  color: var(--contract);
}

.verb.warn {
  background: color-mix(in srgb, var(--warning) 12%, var(--card));
  color: var(--warning);
}

.versions {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}

.strong {
  font-weight: 500;
}

.ops-pre {
  margin: var(--sp-2) 0 0;
  padding: var(--sp-3);
  background: var(--paper);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.cstatus {
  padding: 0 var(--sp-2);
  font-size: var(--text-xs);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  color: var(--ink-2);
}

.cstatus.is-pending_review {
  border-color: var(--warning);
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 8%, var(--card));
}

.cstatus.is-review_rejected {
  border-color: var(--danger);
  color: var(--danger);
}

.review {
  margin: var(--sp-2) 0;
  padding: var(--sp-3);
  background: var(--paper);
  border-radius: var(--radius);
  font-size: var(--text-sm);
}

.review-reason {
  margin-top: var(--sp-1);
}

.changes {
  margin-top: var(--sp-2);
}

.changes li {
  padding: var(--sp-1) 0;
}

.where {
  display: block;
}

.diff {
  overflow-wrap: anywhere;
}

.diff del {
  background: rgba(196, 53, 28, 0.14);
  color: var(--danger);
  text-decoration: line-through;
}

.diff ins {
  background: rgba(21, 122, 78, 0.14);
  color: var(--success);
  text-decoration: none;
}
</style>
