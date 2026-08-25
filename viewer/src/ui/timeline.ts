/**
 * 時刻スライダーと再生。
 *
 * スライダーは input イベントで連続的に飛んでくるので、描画は
 * requestAnimationFrame で1フレーム1回に間引く（720ステップを一気に
 * ドラッグしても追従できるように）。
 */

const WEEKDAY = ['日', '月', '火', '水', '木', '金', '土']

/** 時刻コード YYYYMMDDhhmm を「06-03(水) 08:00」形式にする。 */
export function formatStep(code: string): string {
  const y = +code.slice(0, 4)
  const mo = +code.slice(4, 6)
  const d = +code.slice(6, 8)
  const h = code.slice(8, 10)
  const mi = code.slice(10, 12)
  const w = WEEKDAY[new Date(y, mo - 1, d).getDay()]
  return `${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}(${w}) ${h}:${mi}`
}

export type TimelineHandlers = {
  onIndex: (i: number) => void
}

export class Timeline {
  private slider: HTMLInputElement
  private label: HTMLElement
  private playBtn: HTMLButtonElement
  private timer: number | null = null
  private queued = false
  private steps: string[] = []
  private index = 0

  constructor(
    slider: HTMLInputElement,
    label: HTMLElement,
    playBtn: HTMLButtonElement,
    private handlers: TimelineHandlers,
  ) {
    this.slider = slider
    this.label = label
    this.playBtn = playBtn

    this.slider.addEventListener('input', () => {
      this.index = this.slider.valueAsNumber
      this.renderLabel()
      this.emit()
    })
    this.playBtn.addEventListener('click', () => this.toggle())
    document.addEventListener('keydown', (e) => {
      if (e.target instanceof HTMLInputElement && e.target.type !== 'range') return
      if (e.key === 'ArrowRight') { this.step(1); e.preventDefault() }
      else if (e.key === 'ArrowLeft') { this.step(-1); e.preventDefault() }
      else if (e.key === ' ') { this.toggle(); e.preventDefault() }
    })
  }

  /** 描画をフレームに1回へ間引く。 */
  private emit(): void {
    if (this.queued) return
    this.queued = true
    requestAnimationFrame(() => {
      this.queued = false
      this.handlers.onIndex(this.index)
    })
  }

  private renderLabel(): void {
    const code = this.steps[this.index]
    this.label.textContent = code ? formatStep(code) : '—'
  }

  setSteps(steps: string[], index = 0): void {
    this.steps = steps
    this.index = Math.min(Math.max(index, 0), Math.max(steps.length - 1, 0))
    this.slider.min = '0'
    this.slider.max = String(Math.max(steps.length - 1, 0))
    this.slider.value = String(this.index)
    this.renderLabel()
    this.handlers.onIndex(this.index)
  }

  get current(): number {
    return this.index
  }

  step(delta: number): void {
    if (!this.steps.length) return
    this.index = (this.index + delta + this.steps.length) % this.steps.length
    this.slider.value = String(this.index)
    this.renderLabel()
    this.emit()
  }

  private toggle(): void {
    if (this.timer !== null) this.stop()
    else this.start()
  }

  private start(): void {
    if (!this.steps.length) return
    this.playBtn.textContent = '⏸'
    this.timer = window.setInterval(() => this.step(1), 200)
  }

  stop(): void {
    if (this.timer !== null) window.clearInterval(this.timer)
    this.timer = null
    this.playBtn.textContent = '▶'
  }
}
