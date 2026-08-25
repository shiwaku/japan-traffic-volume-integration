/**
 * 表示状態を URL hash に持たせる（リロード・共有で復元できるように）。
 * 位置は MapLibre が `map=` に書くので、それ以外のキーだけをここで扱う。
 */
import type { ModeKey, SourceKey } from './config'

export const MAP_HASH_KEY = 'map'

export type State = {
  sources?: Set<SourceKey>
  mode?: ModeKey
  /** 時刻インデックス（1時間モードは hours[], 5分モードは日内の288ステップ） */
  t?: number
  /** 5分モードで見ている日（YYYYMMDD） */
  day?: string
  /** 常時ゼロ地点を隠すか */
  hideZero?: boolean
  base?: string
}

function params(): URLSearchParams {
  return new URLSearchParams(location.hash.replace(/^#/, ''))
}

export function readState(): State {
  const p = params()
  const s: State = {}
  const src = p.get('src')
  if (src) s.sources = new Set(src.split(',') as SourceKey[])
  const mode = p.get('mode')
  if (mode === '1h' || mode === '5m') s.mode = mode
  const t = p.get('t')
  if (t !== null && /^\d+$/.test(t)) s.t = parseInt(t, 10)
  const day = p.get('day')
  if (day && /^\d{8}$/.test(day)) s.day = day
  if (p.get('zero') === '0') s.hideZero = true
  const base = p.get('base')
  if (base) s.base = base
  return s
}

export function writeState(s: Required<Omit<State, 'day'>> & { day?: string }): void {
  const p = params()
  p.set('src', [...s.sources].join(','))
  p.set('mode', s.mode)
  p.set('t', String(s.t))
  if (s.day) p.set('day', s.day)
  else p.delete('day')
  if (s.hideZero) p.set('zero', '0')
  else p.delete('zero')
  p.set('base', s.base)
  // MapLibre が書く map= を消さないよう、既存のパラメータを保ったまま置き換える
  history.replaceState(null, '', `#${p.toString()}`)
}
