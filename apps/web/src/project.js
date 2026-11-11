/**
 * 网页看哪个项目。
 *
 * 一个网页只看得到**一个项目**：地址带 `?project=<项目 id>` 时用它，没带且库里只有一个项目时服务端
 * 自动选它，有多个项目就先显示选择页（见 ProjectPicker.vue）。网页用的 key 绑定了这个项目，
 * 所以别的项目的内容它根本拿不到。站内跳转一直带着 project 参数（见 router.js）。
 */

export function parseProject(search) {
  const v = new URLSearchParams(search).get('project')
  return v && /^\d+$/.test(v) ? Number(v) : null
}

/** 地址里指明的项目（没有就是 null）。 */
export const requestedProject = parseProject(window.location.search)

let sessionProject = null

/** 服务端实际给了哪个项目（可能是只有一个项目时自动选的）。 */
export function getSessionProject() {
  return sessionProject
}

export function setSessionProject(id) {
  sessionProject = id ?? null
}
