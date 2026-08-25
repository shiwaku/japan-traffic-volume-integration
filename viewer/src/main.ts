import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

import { getBasemapStyle, type Basemap } from './basemap'
import {
  HOKKAIDO_BOUNDS,
  MODES,
  SAPPORO_CORDON,
  SOURCES,
  type ModeKey,
  type SourceKey,
} from './config'
import { load1h, load5m, loadMeta, loadStations, type Frames } from './dataset'
import { addStationLayers, applyFrame, buildFilter, CIRCLE_ID, RING_ID } from './stations'
import { applyThemeAttr, initialTheme, type Theme } from './theme'
import { BasemapControl } from './ui/basemapControl'
import { $, fatal } from './ui/dom'
import { renderLegend } from './ui/legend'
import { showStationPopup } from './ui/popup'
import { Timeline } from './ui/timeline'
import { MAP_HASH_KEY, readState, writeState } from './urlstate'
import './style.css'

/**
 * 画面の組み立て。配線だけを持ち、設定は config.ts、データは dataset.ts、
 * レイヤーは stations.ts、部品は ui/ に置く。
 *
 * このビューワはローカル閲覧専用。警察地点の座標はTMT由来（譲渡禁止）のため、
 * public/data/ ごと .gitignore 対象にしている。
 */

// ---- データ読み込み --------------------------------------------------------
// meta.json が時刻ステップと色スケールの情報源なので、地図を作る前に解決する。

const [meta, stationsGeoJSON] = await Promise.all([loadMeta(), loadStations()]).catch(
  (e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e)
    fatal(
      `${msg}\n\nビューワ用データが見つかりません。\n` +
        'リポジトリ直下で次を実行してください:\n\n' +
        'python run.py --step export-viewer --regions sapporo --month 2026-06',
    )
    throw e
  },
)

// ---- 表示状態 --------------------------------------------------------------

const saved = readState()
let theme: Theme = initialTheme()
let base: Basemap = (saved.base as Basemap) ?? 'pale'
let mode: ModeKey = saved.mode ?? '1h'
let hideZero = saved.hideZero ?? false
let day = saved.day && meta.days_5m.includes(saved.day) ? saved.day : meta.days_5m[0]
const visible = new Set<SourceKey>(saved.sources ?? SOURCES.map((s) => s.key))
applyThemeAttr(theme)

const zeroSet = new Set(meta.zero_stations)
/** 現在のモードのフレーム群と時刻ステップ列。 */
let frames: Frames = {}
let steps: string[] = []
/** station_uid → MapLibre の feature id。feature-state の更新に使う。 */
const uidToFid = new Map<string, number>()
/** 前フレームで値を入れた uid（今フレームに無ければ null に戻すため）。 */
let prevKeys = new Set<string>()

const isMobile = window.matchMedia('(max-width: 640px)').matches

// ---- 地図 ------------------------------------------------------------------

const map = new maplibregl.Map({
  container: 'map',
  style: await getBasemapStyle(base, theme),
  bounds: SAPPORO_CORDON,
  fitBoundsOptions: { padding: 40 },
  minZoom: 4,
  maxZoom: 19,
  hash: MAP_HASH_KEY,
  attributionControl: false,
  maxTileCacheSize: isMobile ? 24 : undefined,
})

map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
map.addControl(new maplibregl.ScaleControl({ maxWidth: 160, unit: 'metric' }), 'bottom-left')
map.addControl(
  new maplibregl.AttributionControl({
    compact: true,
    customAttribution:
      '出典：「断面交通量情報」（JARTIC）／交通量API（国土交通省）（参考値）を加工／計測地点位置情報：（公財）日本交通管理技術協会',
  }),
)

const persist = (): void =>
  writeState({ sources: visible, mode, t: timeline.current, day, hideZero, base })

// ---- レイヤー投入 ----------------------------------------------------------
// 背景スタイルを差し替えると全レイヤーが消えるため、切替のたびに貼り直す。

/** 背景の注記（symbol）より下に観測点を差し込むためのアンカーを探す。 */
function labelAnchor(): string | undefined {
  const layers = map.getStyle().layers
  let lastShape = -1
  for (let i = 0; i < layers.length; i++) {
    const t = layers[i].type
    if (t === 'line' || t === 'fill') lastShape = i
  }
  for (let i = lastShape + 1; i < layers.length; i++) {
    if (layers[i].type === 'symbol') return layers[i].id
  }
  return undefined
}

function currentFilter(): unknown[] {
  return buildFilter(visible, hideZero, meta.zero_stations)
}

function addLayers(): void {
  addStationLayers(map, stationsGeoJSON, meta.scale_max_1h, currentFilter(), labelAnchor())
  // 貼り直し後は feature-state が失われるので、現在フレームを再投入する
  prevKeys = new Set()
  render(timeline.current)
}

async function reloadStyle(): Promise<void> {
  map.setStyle(await getBasemapStyle(base, theme), { diff: false })
  map.once('idle', addLayers)
}

// ---- feature id の対応表 ---------------------------------------------------
// generateId で振られる id は投入順（0..n-1）なので、GeoJSON の並びから引ける。

stationsGeoJSON.features.forEach((f: GeoJSON.Feature, i: number) => {
  const uid = (f.properties as { station_uid?: string } | null)?.station_uid
  if (uid) uidToFid.set(uid, i)
})

// ---- 描画 ------------------------------------------------------------------

function render(index: number): void {
  if (!map.getLayer(CIRCLE_ID)) return
  prevKeys = applyFrame(map, frames[steps[index]], uidToFid, prevKeys)
}

const timeline = new Timeline(
  $<HTMLInputElement>('time-slider'),
  $('time-label'),
  $<HTMLButtonElement>('play-btn'),
  { onIndex: (i) => { render(i); persist() } },
)

// ---- モード切替（1時間 / 5分） ---------------------------------------------

const loadingEl = $('loading')
const daySelect = $<HTMLSelectElement>('day-select')

const setLoading = (on: boolean): void => {
  loadingEl.hidden = !on
}

async function loadMode(next: ModeKey, keepIndex = false): Promise<void> {
  timeline.stop()
  mode = next
  const prevIndex = keepIndex ? timeline.current : 0
  setLoading(true)
  try {
    if (mode === '1h') {
      frames = await load1h()
      steps = meta.hours
      daySelect.hidden = true
    } else {
      frames = await load5m(day)
      steps = Object.keys(frames).sort()
      daySelect.hidden = false
    }
  } catch (e: unknown) {
    setLoading(false)
    fatal(e instanceof Error ? e.message : String(e))
    return
  }
  setLoading(false)
  renderModeButtons()
  prevKeys = new Set()
  timeline.setSteps(steps, Math.min(prevIndex, steps.length - 1))
  renderLegend($('legend'), meta.scale_max_1h, mode === '1h' ? '台/h' : '台/5分')
  persist()
}

const modesEl = $('modes')
function renderModeButtons(): void {
  modesEl.innerHTML = ''
  for (const m of MODES) {
    const b = document.createElement('button')
    b.type = 'button'
    b.textContent = m.label
    b.title = m.note
    b.classList.toggle('active', m.key === mode)
    b.addEventListener('click', () => {
      if (m.key !== mode) void loadMode(m.key)
    })
    modesEl.appendChild(b)
  }
}

for (const d of meta.days_5m) {
  const o = document.createElement('option')
  o.value = d
  o.textContent = `${d.slice(4, 6)}/${d.slice(6, 8)}`
  daySelect.appendChild(o)
}
daySelect.value = day
daySelect.addEventListener('change', () => {
  day = daySelect.value
  void loadMode('5m', true)
})

// ---- ソース・品質フィルタ --------------------------------------------------

function applyFilter(): void {
  const f = currentFilter() as never
  for (const id of [CIRCLE_ID, RING_ID]) {
    if (map.getLayer(id)) map.setFilter(id, f)
  }
}

const sourcesEl = $('sources')
for (const s of SOURCES) {
  const n = meta.unified_stations_by_source[s.key] ?? 0
  const label = document.createElement('label')
  label.className = 'chk'
  const cb = document.createElement('input')
  cb.type = 'checkbox'
  cb.checked = visible.has(s.key)
  cb.addEventListener('change', () => {
    if (cb.checked) visible.add(s.key)
    else visible.delete(s.key)
    applyFilter()
    persist()
  })
  const span = document.createElement('span')
  span.innerHTML = `${s.label}<em>${s.note} / ${n.toLocaleString()}地点</em>`
  label.append(cb, span)
  sourcesEl.appendChild(label)
}

const hideZeroCb = $<HTMLInputElement>('hide-zero')
hideZeroCb.checked = hideZero
$('zero-count').textContent = `${meta.zero_stations.length}地点が該当`
hideZeroCb.addEventListener('change', () => {
  hideZero = hideZeroCb.checked
  applyFilter()
  persist()
})

// ---- テーマ・パネル開閉 ----------------------------------------------------

const themeBtn = $<HTMLButtonElement>('theme-btn')
const renderThemeBtn = (): void => {
  themeBtn.textContent = theme === 'dark' ? '☀️' : '🌙'
}
themeBtn.addEventListener('click', () => {
  theme = theme === 'dark' ? 'light' : 'dark'
  applyThemeAttr(theme)
  renderThemeBtn()
  void reloadStyle()
})

const panel = $('panel')
const collapseBtn = $<HTMLButtonElement>('collapse-btn')
const renderCollapseBtn = (): void => {
  collapseBtn.textContent = panel.classList.contains('collapsed') ? '▾' : '▴'
}
collapseBtn.addEventListener('click', () => {
  panel.classList.toggle('collapsed')
  renderCollapseBtn()
})

// ---- 背景地図スイッチャー --------------------------------------------------

const basemapCtrl = new BasemapControl(
  () => base,
  (next) => {
    if (next === base) return
    base = next
    basemapCtrl.sync()
    persist()
    void reloadStyle()
  },
)
map.addControl(basemapCtrl, 'bottom-right')

// ---- 表示範囲ボタン --------------------------------------------------------

$('fit-cordon').addEventListener('click', () =>
  map.fitBounds(SAPPORO_CORDON, { padding: 40 }),
)
$('fit-all').addEventListener('click', () => map.fitBounds(HOKKAIDO_BOUNDS, { padding: 24 }))

// ---- クリックでポップアップ ------------------------------------------------

map.on('click', (e) => {
  if (!map.getLayer(CIRCLE_ID)) return
  const hits = map.queryRenderedFeatures(e.point, { layers: [CIRCLE_ID] })
  if (!hits.length) return
  const uid = String((hits[0].properties as { station_uid?: string }).station_uid ?? '')
  showStationPopup(
    map,
    e.lngLat,
    hits[0],
    frames,
    steps,
    timeline.current,
    mode === '1h' ? '台/h' : '台/5分',
    zeroSet.has(uid),
  )
})

let hoverQueued = false
map.on('mousemove', (e) => {
  if (hoverQueued || !map.getLayer(CIRCLE_ID)) return
  hoverQueued = true
  requestAnimationFrame(() => {
    hoverQueued = false
    const hit = map.queryRenderedFeatures(e.point, { layers: [CIRCLE_ID] }).length > 0
    map.getCanvas().style.cursor = hit ? 'pointer' : ''
  })
})

// ---- 初期化 ----------------------------------------------------------------

$('subtitle').textContent = meta.target_month_label
$('build-ver').textContent = `build: ${__BUILD_TIME__}`
$('attribution').innerHTML = meta.attribution.join('<br>')
const totalStations = Object.values(meta.stations_by_source).reduce(
  (a: number, b) => a + b.stations,
  0,
)
$('stats').textContent = `全 ${totalStations.toLocaleString()} 地点 / ${meta.hours.length} 時刻ステップ`
renderThemeBtn()
if (isMobile) panel.classList.add('collapsed')
renderCollapseBtn()

map.on('load', () => {
  addLayers()
  void loadMode(mode).then(() => {
    if (saved.t !== undefined) timeline.setSteps(steps, saved.t)
  })
})

// WebGL コンテキスト消失からの復帰（モバイルでメモリ逼迫時に起きる）
const canvas = map.getCanvas()
canvas.addEventListener('webglcontextlost', (ev) => ev.preventDefault(), false)
canvas.addEventListener(
  'webglcontextrestored',
  () => {
    if (map.isStyleLoaded()) addLayers()
    else map.once('idle', addLayers)
  },
  false,
)

// デバッグ用
;(window as unknown as { __map: maplibregl.Map }).__map = map
