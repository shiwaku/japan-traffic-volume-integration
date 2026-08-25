export function $<T extends HTMLElement = HTMLElement>(id: string): T {
  const el = document.getElementById(id)
  if (!el) throw new Error(`#${id} が見つかりません`)
  return el as T
}

/** 起動に失敗した理由を画面に出す（コンソールを開かなくても分かるように）。 */
export function fatal(message: string): void {
  const el = document.createElement('div')
  el.className = 'fatal'
  el.textContent = message
  document.body.appendChild(el)
}
