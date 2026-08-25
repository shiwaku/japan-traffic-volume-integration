import maplibregl from 'maplibre-gl'

import type { Frames } from '../dataset'

/**
 * 観測点のポップアップ。
 * その時刻の値だけでなく、24時間ぶんのスパークラインを出す
 * （単発の値が妥当かは日変動の形を見ないと判断できないため）。
 */

const SOURCE_LABEL: Record<string, string> = {
  police: '警察 車両感知器',
  mlit_tracan: '国交省 常設トラカン',
  mlit_cctv: '国交省 CCTVトラカン',
}

function sourceKey(props: Record<string, unknown>): string {
  if (props.source === 'police') return 'police'
  return props.observer_type === 'cctv' ? 'mlit_cctv' : 'mlit_tracan'
}

/** 直近24ステップの値を拾ってミニ折れ線を描く。 */
function sparkline(values: (number | null)[], width = 200, height = 40): string {
  const nums = values.filter((v): v is number => v !== null)
  if (nums.length < 2) return ''
  const max = Math.max(...nums, 1)
  const step = width / (values.length - 1)
  let d = ''
  let started = false
  values.forEach((v, i) => {
    if (v === null) { started = false; return }
    const x = (i * step).toFixed(1)
    const y = (height - (v / max) * (height - 4) - 2).toFixed(1)
    d += `${started ? 'L' : 'M'}${x} ${y}`
    started = true
  })
  return `<svg class="spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
    <path d="${d}" fill="none" stroke="currentColor" stroke-width="1.5"/>
  </svg><div class="spark-note">前後24ステップ（最大 ${max.toLocaleString()}）</div>`
}

export function showStationPopup(
  map: maplibregl.Map,
  lngLat: maplibregl.LngLatLike,
  feature: maplibregl.MapGeoJSONFeature,
  frames: Frames,
  steps: string[],
  index: number,
  unit: string,
  isZeroStation: boolean,
): void {
  const p = feature.properties as Record<string, unknown>
  const uid = String(p.station_uid ?? '')
  const key = sourceKey(p)
  const now = frames[steps[index]]?.[uid]

  // 前後を含む24ステップ分を拾う
  const from = Math.max(0, index - 12)
  const window = steps.slice(from, from + 24)
  const series = window.map((s) => {
    const v = frames[s]?.[uid]
    return v === undefined ? null : v
  })

  const rows: string[] = []
  rows.push(`<div class="pp-src">${SOURCE_LABEL[key] ?? key}</div>`)
  if (p.name) rows.push(`<div class="pp-name">${String(p.name)}</div>`)
  rows.push(
    `<div class="pp-val">${now === undefined ? '—' : now.toLocaleString()}<span>${unit}</span></div>`,
  )
  if (now === undefined) {
    rows.push('<div class="pp-warn">この時刻は欠測（または12スロット揃わず）</div>')
  }
  if (isZeroStation) {
    rows.push('<div class="pp-warn">月間ずっと0：感知器の故障・休止の疑い</div>')
  }
  rows.push(sparkline(series))
  const meta: string[] = [`<code>${uid}</code>`]
  if (p.direction_hint) meta.push(`方向 ${String(p.direction_hint)}`)
  rows.push(`<div class="pp-meta">${meta.join(' / ')}</div>`)

  new maplibregl.Popup({ closeButton: true, maxWidth: '280px', className: 'station-popup' })
    .setLngLat(lngLat)
    .setHTML(rows.join(''))
    .addTo(map)
}
