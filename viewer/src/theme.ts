export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'traffic-volume-viewer-theme'

/**
 * 既定はダーク。観測点を発色の強い円で描くので、暗い背景の方が値の差を読みやすい。
 * 端末の設定には従わず、一度切り替えた選択を localStorage に残す。
 */
const DEFAULT_THEME: Theme = 'dark'

export function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    // プライベートウィンドウ等で localStorage が使えない場合は既定値
  }
  return DEFAULT_THEME
}

export function applyThemeAttr(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // 保存できなくても表示は続ける
  }
}
