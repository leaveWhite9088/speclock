<script setup>
/**
 * BlockFieldRows —— 可编辑的递归字段行（请求体/响应体共用）。
 * 直接修改传入的响应式 fields 数组；object/array 类型可携带子字段。
 */
const props = defineProps({
  fields: { type: Array, required: true },
  depth: { type: Number, default: 0 },
})

const TYPES = ['string', 'number', 'integer', 'boolean', 'array', 'object']
const CONTAINERS = ['object', 'array']

function newField() {
  return { name: '', type: 'string', required: false, description: '', children: [] }
}

function onTypeChange(f) {
  // 切回标量则丢弃子字段
  if (!CONTAINERS.includes(f.type)) f.children = []
}

function addChild(f) {
  if (!Array.isArray(f.children)) f.children = []
  f.children.push(newField())
}

function remove(i) {
  // 删除父字段，children 随字段一起被移除（级联）
  props.fields.splice(i, 1)
}
</script>

<template>
  <template v-for="(f, i) in fields" :key="i">
    <tr class="frow">
      <td>
        <input
          class="input mono fname"
          :style="{ marginLeft: depth * 20 + 'px' }"
          v-model="f.name"
          placeholder="字段名"
          spellcheck="false"
        />
      </td>
      <td>
        <select class="input mono ftype" v-model="f.type" @change="onTypeChange(f)">
          <option v-for="t in TYPES" :key="t" :value="t">{{ t }}</option>
        </select>
      </td>
      <td class="freq"><input type="checkbox" v-model="f.required" /></td>
      <td>
        <input class="input" v-model="f.description" placeholder="说明" />
      </td>
      <td class="fops">
        <button
          v-if="CONTAINERS.includes(f.type)"
          type="button"
          class="btn btn-mini"
          @click="addChild(f)"
        >
          +子字段
        </button>
        <button type="button" class="btn btn-mini btn-danger" @click="remove(i)">
          删
        </button>
      </td>
    </tr>
    <BlockFieldRows
      v-if="f.children && f.children.length"
      :fields="f.children"
      :depth="depth + 1"
    />
  </template>
</template>

<style scoped>
.btn-mini {
  padding: 2px var(--sp-2);
  font-size: var(--text-xs);
}

.frow td {
  padding: var(--sp-1) var(--sp-2) var(--sp-1) 0;
  vertical-align: middle;
}

.fname {
  min-width: 140px;
}

.ftype {
  width: 104px;
}

.freq {
  text-align: center;
}

.fops {
  white-space: nowrap;
}

.fops .btn + .btn {
  margin-left: var(--sp-1);
}
</style>
