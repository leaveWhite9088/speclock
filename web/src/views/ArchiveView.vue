<script setup>
// 归档：已归档模块列表（只读）。恢复由 Agent 经审核单 + Commit（restore_block）完成。
import { resources } from '../api/resources.js'
import { useAsync } from '../composables/useAsync.js'
import { fmtTime } from '../time.js'
import VersionChip from '../components/VersionChip.vue'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

const { data: rows, loading, error, reload } = useAsync(() => resources.archive())
useAutoRefresh(reload)
</script>

<template>
  <div class="page archive-page">
    <PageHeader
      eyebrow="Archive"
      title="归档管理"
      desc="归档模块对 AI 不可见（读取 404、索引不出现），历史版本保留可查。归档与恢复都由 Agent 经审核单的 Commit 完成，并立即派生所属小业务的新版本（MINOR）。"
    />

    <AsyncState
      :loading="loading"
      :error="error"
      :empty="!rows?.length"
      empty-title="没有已归档的模块"
      empty-text="模块下线由 Agent 经审核单归档——归档后历史版本仍然保留，可随时恢复。"
      @retry="reload"
    >
    <div class="row-list">
      <article v-for="row in rows" :key="row.id" class="card arch-row">
        <div class="arch-main">
          <p class="arch-path mono muted">
            {{ row.project_name }} / {{ row.business_name }} /
            <RouterLink :to="`/capabilities/${row.capability_id}`">{{
              row.capability_title
            }}</RouterLink>
          </p>
          <div class="arch-title-line">
            <RouterLink :to="`/blocks/${row.id}`" class="arch-title">{{
              row.title
            }}</RouterLink>
            <VersionChip
              v-if="row.current_published_version"
              :version="row.current_published_version"
            />
            <span v-else class="muted text-sm">无已发布版本</span>
          </div>
          <p class="muted arch-time">归档于 {{ fmtTime(row.archived_at) }}</p>
        </div>

      </article>
    </div>
    </AsyncState>
  </div>
</template>

<style scoped>
.archive-page {
  max-width: 860px;
}

.state-card {
  margin-top: var(--sp-5);
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.row-list {
  margin-top: var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.arch-row {
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  align-items: center;
  gap: var(--sp-5);
  flex-wrap: wrap;
}

.arch-main {
  flex: 1;
  min-width: 260px;
}

.arch-path {
  font-size: var(--text-xs);
  margin-bottom: var(--sp-1);
}

.arch-title-line {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.arch-title {
  font-weight: 600;
  font-size: var(--text-md);
}

.text-sm {
  font-size: var(--text-sm);
}

.arch-time {
  font-size: var(--text-xs);
  margin-top: var(--sp-1);
}

.arch-ops {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.confirm-text {
  font-size: var(--text-sm);
  max-width: 320px;
}

.confirm-text.is-danger {
  color: var(--danger);
}

.confirm-btns {
  display: flex;
  gap: var(--sp-2);
}

.arch-error {
  flex-basis: 100%;
}
</style>
