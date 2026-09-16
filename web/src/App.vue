<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearKey, keyHint } from './api/client.js'
import VersionChip from './components/VersionChip.vue'

const route = useRoute()
const router = useRouter()

const isPublic = computed(() => route.meta.public === true)
const hint = computed(() => keyHint())

const mainNav = [
  { to: '/', label: '文档树' },
  { to: '/proposals', label: '提案' },
  { to: '/acks', label: '回执' },
  { to: '/archive', label: '归档' },
]

const bottomNav = [
  { to: '/mcp', label: 'AI 接入' },
  { to: '/keys', label: '密钥管理' },
]

function logout() {
  clearKey()
  router.push({ name: 'login' })
}
</script>

<template>
  <!-- 登录页等公共路由：不带布局壳 -->
  <router-view v-if="isPublic" v-slot="{ Component }">
    <transition name="fade" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>

  <div v-else class="shell">
    <aside class="sidebar">
      <nav class="side-nav" aria-label="主导航">
        <RouterLink
          v-for="item in mainNav"
          :key="item.to"
          :to="item.to"
          class="side-link"
          >{{ item.label }}</RouterLink
        >
      </nav>

      <!-- 文档树导航占位：文档树页面接入后，树形导航渲染在这里 -->
      <div class="side-tree mono" aria-label="文档树">
        <span class="side-tree-hint">文档树将展示在这里</span>
      </div>

      <nav class="side-nav side-bottom" aria-label="辅助导航">
        <RouterLink
          v-for="item in bottomNav"
          :key="item.to"
          :to="item.to"
          class="side-link"
          >{{ item.label }}</RouterLink
        >
      </nav>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="brand">
          <span class="brand-name">SpecLock</span>
          <VersionChip version="0.1.0" status="draft" />
        </div>
        <div class="topbar-right">
          <span class="key-hint mono" :title="hint">{{ hint }}</span>
          <button type="button" class="btn" @click="logout">退出登录</button>
        </div>
      </header>

      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
}

/* ---------- 侧边栏 ---------- */

.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  width: var(--sidebar-w);
  display: flex;
  flex-direction: column;
  background: var(--card);
  border-right: 1px solid var(--hairline);
  padding: var(--sp-5) var(--sp-4) var(--sp-4);
}

.side-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.side-link {
  display: block;
  padding: 7px var(--sp-3);
  border-radius: var(--radius);
  color: var(--ink-2);
  font-size: var(--text-sm);
  transition:
    color var(--dur) var(--ease),
    background var(--dur) var(--ease);
}

.side-link:hover {
  color: var(--ink);
  background: var(--paper);
}

.side-link.is-active {
  color: var(--contract);
  background: var(--contract-wash);
  font-weight: 500;
}

.side-tree {
  flex: 1;
  margin-top: var(--sp-5);
  padding: var(--sp-4) var(--sp-3);
  border: 1px dashed var(--hairline);
  border-radius: var(--radius);
  color: var(--ink-2);
  font-size: var(--text-xs);
  display: flex;
  align-items: flex-start;
}

.side-bottom {
  border-top: 1px solid var(--hairline);
  padding-top: var(--sp-4);
}

/* ---------- 主区 ---------- */

.main {
  flex: 1;
  margin-left: var(--sidebar-w);
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  height: var(--topbar-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--sp-8);
  background: var(--card);
  border-bottom: 1px solid var(--hairline);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.brand-name {
  font-family: var(--font-mono);
  font-size: var(--text-md);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}

.key-hint {
  font-size: var(--text-xs);
  color: var(--ink-2);
  padding: 3px var(--sp-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
}

.content {
  flex: 1;
}

/* 窄屏：侧边栏收为顶部通栏（质量底线，不是设计目标） */
@media (max-width: 760px) {
  .shell {
    flex-direction: column;
  }

  .sidebar {
    position: static;
    width: auto;
    border-right: none;
    border-bottom: 1px solid var(--hairline);
  }

  .side-tree {
    display: none;
  }

  .main {
    margin-left: 0;
  }
}
</style>
