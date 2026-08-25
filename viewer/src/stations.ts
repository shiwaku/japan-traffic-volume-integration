import type maplibregl from 'maplibre-gl'

import { NODATA_COLOR, RAMP, SOURCE_KEY_EXPR, type SourceKey } from './config'

/**
 * 観測点レイヤー。
 *
 * ジオメトリは一度だけ投入し、時刻が進むたびに `feature-state` の volume を
 * 書き換えて色・半径だけを更新する（GeoJSON の再設定はしない）。
 * 2,341地点を720ステップぶんスクラブしても描画が破綻しないのはこのため。
 */

export const SOURCE_ID = 'stations'
export const CIRCLE_ID = 'stations-circle'
export const RING_ID = 'stations-ring'

/** feature-state で参照する交通量。値が無ければ null。 */
const VOL = ['feature-state', 'volume']

/**
 * 交通量 → 色。scaleMax（上位1%点）で正規化した比率に RAMP を当てる。
 * feature-state が未設定の間は NODATA_COLOR。
 */
function colorExpr(scaleMax: number): unknown[] {
  const stops: unknown[] = []
  for (const [pos, color] of RAMP) {
    stops.push(pos * scaleMax, color)
  }
  return [
    'case',
    ['==', VOL, null],
    NODATA_COLOR,
    ['interpolate', ['linear'], ['to-number', VOL, 0], ...stops],
  ]
}

/**
 * 交通量 → 半径。ズームでも大きさを変える。
 * 値が無い点は小さく描いて、値がある点を邪魔しないようにする。
 *
 * `offset` はリング用の上乗せ幅。MapLibre は ['zoom'] を
 * **トップレベルの interpolate/step の入力にしか置けない**ため、
 * `['+', radiusExpr(...), 1.6]` のように外側から包むと式が不正になる
 * （"zoom expression may only be used as input to a top-level ..." で
 * レイヤーごと無視され、リングが描画されない）。各ストップの内側で足す。
 */
function radiusExpr(scaleMax: number, offset = 0): unknown[] {
  const byVolume = [
    'interpolate',
    ['linear'],
    ['to-number', VOL, 0],
    0, 3,
    scaleMax * 0.5, 6,
    scaleMax, 10,
  ]
  const at = (nodata: number, factor: number): unknown[] => [
    '+',
    ['case', ['==', VOL, null], nodata, ['*', byVolume, factor]],
    offset,
  ]
  return [
    'interpolate',
    ['linear'],
    ['zoom'],
    8, at(1.5, 0.45),
    12, at(2.5, 0.8),
    15, at(4, 1),
    18, at(6, 1.6),
  ]
}

/**
 * 表示するソースと「常時ゼロ地点を隠すか」から filter 式を作る。
 * zeroStations は uid の集合。`in` 式に配列で渡す。
 */
export function buildFilter(
  visible: Set<SourceKey>,
  hideZero: boolean,
  zeroStations: string[],
): unknown[] {
  const bySource = ['in', SOURCE_KEY_EXPR, ['literal', [...visible]]]
  if (!hideZero || zeroStations.length === 0) return bySource
  return ['all', bySource, ['!', ['in', ['get', 'station_uid'], ['literal', zeroStations]]]]
}

export function addStationLayers(
  map: maplibregl.Map,
  data: GeoJSON.FeatureCollection,
  scaleMax: number,
  filter: unknown[],
  before?: string,
): void {
  if (!map.getSource(SOURCE_ID)) {
    map.addSource(SOURCE_ID, {
      type: 'geojson',
      data,
      // feature-state を使うため id が必要。GeoJSON に id が無いので生成させる。
      generateId: true,
    })
  }

  // ソースの区別は輪郭の色でつける（塗りは交通量に使うため）。
  if (!map.getLayer(RING_ID)) {
    map.addLayer(
      {
        id: RING_ID,
        type: 'circle',
        source: SOURCE_ID,
        filter: filter as never,
        paint: {
          'circle-radius': radiusExpr(scaleMax, 1.6) as never,
          'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-width': 1.4,
          'circle-stroke-color': [
            'case',
            ['==', SOURCE_KEY_EXPR, 'police'], '#ffd166',
            ['==', SOURCE_KEY_EXPR, 'mlit_cctv'], '#06d6a0',
            '#4cc9f0',
          ] as never,
          'circle-stroke-opacity': 0.9,
        },
      },
      before,
    )
  }

  if (!map.getLayer(CIRCLE_ID)) {
    map.addLayer(
      {
        id: CIRCLE_ID,
        type: 'circle',
        source: SOURCE_ID,
        filter: filter as never,
        paint: {
          'circle-radius': radiusExpr(scaleMax) as never,
          'circle-color': colorExpr(scaleMax) as never,
          'circle-opacity': ['case', ['==', VOL, null], 0.35, 0.9] as never,
        },
      },
      before,
    )
  }
}

/**
 * 1フレーム分の値を feature-state に流し込む。
 *
 * 前フレームで値があった地点は、今フレームに無ければ null に戻す必要がある
 * （残像が出るため）。差分だけを触ることで 2,341地点でも 60fps を保てる。
 */
export function applyFrame(
  map: maplibregl.Map,
  frame: Record<string, number> | undefined,
  uidToFid: Map<string, number>,
  prevKeys: Set<string>,
): Set<string> {
  const nextKeys = new Set<string>()
  if (frame) {
    for (const uid in frame) {
      const fid = uidToFid.get(uid)
      if (fid === undefined) continue
      map.setFeatureState({ source: SOURCE_ID, id: fid }, { volume: frame[uid] })
      nextKeys.add(uid)
    }
  }
  for (const uid of prevKeys) {
    if (nextKeys.has(uid)) continue
    const fid = uidToFid.get(uid)
    if (fid === undefined) continue
    map.setFeatureState({ source: SOURCE_ID, id: fid }, { volume: null })
  }
  return nextKeys
}
