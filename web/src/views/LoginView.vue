<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { resources } from '../api/resources.js'
import { errText } from '../errors.js'
import { api, setKey, clearKey } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'

const route = useRoute()
const router = useRouter()

const key = ref('')
const pending = ref(false)
const error = ref('')

async function submit() {
  const value = key.value.trim()
  if (!value) {
    error.value = '请输入管理密钥（human- 开头）。'
    return
  }
  pending.value = true
  error.value = ''
  // 先暂存密钥，用 GET /projects 试一次；失败立即清掉，不留坏密钥在本地
  setKey(value)
  try {
    await resources.projects()
    const from = typeof route.query.from === 'string' ? route.query.from : '/'
    router.push(from)
  } catch (e) {
    clearKey()
    if (e.status === 401) {
      error.value =
        '这把密钥不存在或已失效。请确认粘贴的是完整的密钥原文；没有的话，用 speclock-cli key create 创建，或让持有 admin key 的 Agent 在你同意后创建。'
    } else if (e.status === 403) {
      error.value = '这把密钥的角色没有读取规格的权限（spec.read），看不了内容。请换一把有权限的密钥。'
    } else {
      error.value = errText(e)
    }
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="login">
    <div class="sheet card">
      <header class="sheet-head">
        <div class="wordmark-row">
          <span class="wordmark">SpecLock</span>
          <VersionChip version="0.1.0" status="published" />
        </div>
        <p class="tagline">接口契约的单一事实来源</p>
      </header>

      <form class="sheet-body" @submit.prevent="submit">
        <label class="label" for="key-input">管理密钥</label>
        <input
          id="key-input"
          v-model="key"
          class="input mono"
          type="password"
          placeholder="human-…"
          autocomplete="off"
          spellcheck="false"
          :disabled="pending"
        />
        <p class="field-hint">
          管理端只接受 <span class="mono">human-</span> 开头的密钥；agent
          密钥通过 API / MCP 读取已发布内容。
        </p>

        <p v-if="error" class="error-text" role="alert">{{ error }}</p>

        <button class="btn btn-primary submit" type="submit" :disabled="pending">
          {{ pending ? '正在验证…' : '登录并验证' }}
        </button>
      </form>
    </div>

    <p class="foot mono">/api/v1 · X-API-Key</p>
  </div>
</template>

<style scoped>
.login {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-5);
  padding: var(--sp-5);
}

.sheet {
  width: 100%;
  max-width: 380px;
  padding: var(--sp-6);
}

.sheet-head {
  padding-bottom: var(--sp-5);
  margin-bottom: var(--sp-5);
  border-bottom: 1px solid var(--hairline);
}

.wordmark-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.wordmark {
  font-family: var(--font-mono);
  font-size: var(--text-2xl);
  font-weight: 600;
  letter-spacing: 0.01em;
  line-height: 1.2;
}

.tagline {
  margin-top: var(--sp-2);
  color: var(--ink-2);
  font-size: var(--text-sm);
}

.sheet-body {
  display: flex;
  flex-direction: column;
}

.field-hint {
  margin-top: var(--sp-2);
  color: var(--ink-2);
  font-size: var(--text-xs);
  line-height: 1.7;
}

.sheet-body .error-text {
  margin-top: var(--sp-3);
}

.submit {
  margin-top: var(--sp-5);
  justify-content: center;
}

.foot {
  color: var(--ink-2);
  font-size: var(--text-xs);
  letter-spacing: 0.06em;
}
</style>
