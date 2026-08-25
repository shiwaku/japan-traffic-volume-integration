/**
 * データの読み込み。
 *
 * 出力は run.py --step export-viewer が public/data/ に置く。
 * TMT座標（譲渡禁止）を含むためコミット・公開しない。ローカル閲覧専用。
 */

const DATA = `${import.meta.env.BASE_URL}data/`

export type Meta = {
  target_month: string
  target_month_label: string
  /** 1時間モードの時刻コード（YYYYMMDDhhmm）。昇順。 */
  hours: string[]
  /** 5分モードで取得できる日（YYYYMMDD）。 */
  days_5m: string[]
  stations_by_source: Record<string, { stations: number }>
  unified_stations_by_source: Record<string, number>
  /** 月間ずっと0だった地点。感知器の故障・休止の疑いがあるので隠せるようにする。 */
  zero_stations: string[]
  /** 色スケールの上限（上位1%点）。外れ値で潰れないようにする。 */
  scale_max_1h: number
  /** 5分値用の上限。1時間値と桁が違うのでモードごとに持つ。 */
  scale_max_5m: number
  attribution: string[]
}

/** {時刻コード: {station_uid: 交通量}} */
export type Frames = Record<string, Record<string, number>>

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(DATA + path)
  if (!res.ok) throw new Error(`${path} を読めません (HTTP ${res.status})`)
  return (await res.json()) as T
}

export const loadMeta = (): Promise<Meta> => getJSON<Meta>('meta.json')

export const loadStations = (): Promise<GeoJSON.FeatureCollection> =>
  getJSON<GeoJSON.FeatureCollection>('stations.geojson')

/**
 * gzip 済みJSONを読む。`.json.gz` は Content-Encoding が付かないため、
 * ブラウザの自動展開に頼らず DecompressionStream で明示的に展開する。
 */
async function getGzipJSON<T>(path: string): Promise<T> {
  const res = await fetch(DATA + path)
  if (!res.ok) throw new Error(`${path} を読めません (HTTP ${res.status})`)
  // Vite dev サーバは .gz に Content-Encoding: gzip を付けて返すことがある。
  // その場合 body は既に展開済みなので、二重展開しないよう分岐する。
  const enc = res.headers.get('content-encoding')
  if (enc?.includes('gzip') || !('DecompressionStream' in window)) {
    return (await res.json()) as T
  }
  const ds = new DecompressionStream('gzip')
  const stream = res.body!.pipeThrough(ds)
  const text = await new Response(stream).text()
  return JSON.parse(text) as T
}

export const load1h = (): Promise<Frames> => getGzipJSON<Frames>('traffic_1h.json.gz')

export const load5m = (ymd: string): Promise<Frames> =>
  getGzipJSON<Frames>(`traffic_5m/${ymd}.json.gz`)
