/** ビューワの表示設定。データ側の定義は meta.json が単一の情報源。 */

/** 観測点のソース。別系統の機器なので混ぜて見せない（DESIGN.md §2.4）。 */
export type SourceKey = 'police' | 'mlit_tracan' | 'mlit_cctv'

export const SOURCES: { key: SourceKey; label: string; note: string }[] = [
  { key: 'police', label: '警察 車両感知器', note: '一般道路・断面合計' },
  { key: 'mlit_tracan', label: '国交省 常設トラカン', note: '直轄国道・方向別車種別' },
  { key: 'mlit_cctv', label: '国交省 CCTVトラカン', note: '直轄国道・AI画像認識' },
]

/**
 * 観測点の source 列（police / mlit）と observer_type（tracan / cctv）から
 * 表示用のソースキーを引くための MapLibre 式。
 */
export const SOURCE_KEY_EXPR = [
  'case',
  ['==', ['get', 'source'], 'police'],
  'police',
  ['==', ['get', 'observer_type'], 'cctv'],
  'mlit_cctv',
  'mlit_tracan',
]

/**
 * 交通量→色。上限は meta.scale_max_* （上位1%点）で正規化した比率に当てる。
 *
 * ストップを低い側に寄せているのは、実際の分布が下に偏っているため。
 * 都心部の1時間値は中央値231・90%点772・99%点1408（202606実測）で、
 * 等間隔に配色すると大半が最初の1/6に固まって色差が出ない。
 * 深夜33〜朝468という14倍の変化を見せるには、低い値域を細かく刻む必要がある。
 */
export const RAMP: [number, string][] = [
  [0.0, '#2c3e94'], // 深夜（濃紺）
  [0.06, '#4a6fd0'],
  [0.14, '#7fa3e8'],
  [0.26, '#c2d3ef'], // 朝の立ち上がり
  [0.42, '#f4cdb0'],
  [0.62, '#e8785d'], // ピーク帯
  [1.0, '#a8121f'], // 最混雑（赤）
]

/** 値が無い（欠測・partial・その時刻に観測なし）ときの色。 */
export const NODATA_COLOR = '#8b8f96'

/** 札幌都心（sapporo-micro-traffic-sim のコードン区域）。初期表示に使う。 */
export const SAPPORO_CORDON: [number, number, number, number] = [
  141.3305, 43.0468, 141.3595, 43.0692,
]

/** 全体表示（札幌方面本部の管内＋北海道の国交省地点）。 */
export const HOKKAIDO_BOUNDS: [number, number, number, number] = [139.6, 41.3, 145.7, 45.6]

export const MODES = [
  { key: '1h' as const, label: '1時間', note: '1ヶ月を通しでスクラブ' },
  { key: '5m' as const, label: '5分', note: '警察のみ・日別' },
]
export type ModeKey = (typeof MODES)[number]['key']
