# japan-traffic-volume-integration

一般道路の「断面交通量情報」（都道府県警察の車両感知器・JARTIC typeB）と
「交通量データ（国土交通省）」（直轄国道・JARTIC 交通量API）を統合し、
共通スキーマの観測点マスタ＋交通量時系列データセットを作成するプロジェクト。

設計の全容は [DESIGN.md](DESIGN.md) を参照。
Phase 1（札幌方面・2026年6月分）のパイプラインが動作済み。検証結果は [reports/](reports/) を参照。

## Phase 1 の検証結果（2026年6月・札幌方面）

| 指標 | 結果 |
|---|---|
| 警察 断面交通量 | 1,910地点 / 1,476万レコード（5分値） |
| 国交省 交通量データ | 431地点 / 181万レコード（1時間値・方向別車種別） |
| TMT座標の結合率 | **1,910 / 1,910 地点（100%）** |
| 警察×国交省の近接ペア相関 | 17ペア検出、**相関中央値 0.967**（15件中14件が r≥0.9） |
| 常時ゼロ地点（感知器故障の疑い） | 警察 88地点（4.7%）— 分析時は除外候補 |

異なる機関・異なる機器が同一断面で 0.97 の相関を示しており、座標結合の正しさが独立に裏付けられている。

## 使い方

```bash
pip install -r requirements.txt

# 全ステップ実行（例: 札幌方面・2026年6月）
python run.py --step all --regions sapporo --month 2026-06

# 個別ステップ
python run.py --step fetch-police,parse-police --regions sapporo --month 2026-06
python run.py --step fetch-mlit,ingest-mlit    --regions sapporo --month 2026-06
python run.py --step stations,unify,export,verify --regions sapporo --month 2026-06
```

| ステップ | 処理 |
|---|---|
| fetch-police | JARTICカタログ（opendata.json）からtypeB月次ZIPを取得 |
| parse-police | SJIS CSV → counts / stations Parquet（DuckDB） |
| fetch-mlit | 交通量APIから1時間値（様式2/4）を地域BBOX・日別に取得 |
| ingest-mlit | 取得CSV → counts / stations Parquet（方向×車種のlong format） |
| stations | 統合観測点マスタ生成。`data/private/tmt/*.csv` があれば警察地点に座標結合 |
| unify | counts統合＋断面1時間合計へ正規化（counts_unified_1h） |
| export | 観測点を**ライセンスの出所別に分割**して出力（PMTilesはtippecanoe導入後） |
| verify | 検証レポートJSONを `reports/` に出力（コミット対象） |

### 成果物（`output/{YYYYMM}/`）

2026年6月・札幌方面の実績。**生データ1.3GB相当が22MBに収まる**（Parquet + zstd）。

```
counts/                          交通量 long format（1行 = 地点×時刻×方向×車種）
  source=police/       17.0 MB   1,476万行・5分値・断面合計
  source=mlit_tracan/   0.9 MB      93万行・1時間値・方向別車種別
  source=mlit_cctv/     0.6 MB      88万行・同上（AI画像認識）
counts_unified_1h/               断面1時間合計に正規化（両者を同一スキーマに）
  source=police/        3.0 MB   126万 station-hour
  source=mlit_tracan/   0.4 MB    15万 station-hour
  source=mlit_cctv/     0.3 MB    15万 station-hour
stations_open.{parquet,geojson}       国交省 431地点          → 公開可
stations_all_restricted.parquet       全 2,341地点（属性のみ）→ 公開不可
stations_all_restricted.geojson       同上（QGIS用）          → 公開不可
stations_all_restricted_geo.parquet   同上（GeoParquet 1.1）  → 公開不可
```

**国交省と警察を含めた全地点データは `stations_all_restricted.*`**（2,341地点＝警察1,910＋国交省431）。
TMT座標を含むため公開はできないが、内部での分析・突合にはこれを使う。

> **QGISで開くときは `.geojson` か `_geo.parquet` を使うこと。**
> `stations_all_restricted.parquet` は素のParquetで `lon`/`lat` が単なる数値列のため、
> QGISはジオメトリと認識せず地図に表示されない（属性テーブルとしては開ける）。
> `_geo.parquet` は WKB ジオメトリ列 + GeoParquet メタデータを持つので直接描画できる
> （QGIS 3.28+ / GDAL 3.5+）。DuckDB での集計は素の `.parquet` の方が扱いやすい。

原本を含む `data/` 全体は約291MB（うち警察のZIP原本が221MB）。

#### `counts/` — 生に近い long format

```
station_uid       ts                interval direction vehicle_class volume quality   source
police:3001:1124  2026-06-01 05:50  5m       section   all           20     ok        police
mlit:1310050      2026-06-24 18:00  1h       down      large         11     sensor_ng mlit_tracan
```

警察側は方向・車種の内訳を持たないため `direction=section` / `vehicle_class=all` に固定される。
国交省側は方向×車種に分かれ、機器異常フラグ（`sensor_ng` 等）も保持する。

#### `counts_unified_1h/` — 両者を同じ土俵に乗せた層

```
station_uid       ts_hour           volume_1h n_obs quality source
mlit:1310080      2026-06-03 08:00  2300      6     ok      mlit_tracan
police:3001:1610  2026-06-03 08:00  1110      12    ok      police
```

`n_obs` に両者の性格が出る。国交省の `6` は「上下線×3車種の6系列を合算」、
警察の `12` は「5分値12スロットを1時間に集計」の意味で、この値で品質を判定する
（12個揃わなければ `partial`）。上例は同一断面の近接ペア（71.5m）だが、
**測り方が違うため絶対値は約2倍ずれる**（§2.4 参照）。

#### `stations_*` — 観測点マスタ

| | 列 | 備考 |
|---|---|---|
| `stations_open` | `station_uid, source, pref_code, road_class, observer_type, lon, lat, location_source` | 国交省431地点。`observer_type` は `tracan` / `cctv` |
| `stations_all_restricted` | 上記 + `name, direction_hint, drm_*` | 警察地点を含む。`name` は現地の交差点名と方向（例「厚別中央　２−４北北」）でネットワーク突合に有用 |

> `stations_all_restricted` の座標は TMT 由来のため、**値をドキュメントや issue に貼らないこと**
> （それ自体が規約の禁じる「譲渡」に当たる）。

#### まだ無いもの

PMTiles（tippecanoe 未導入）、ビューワ、7月以降の月次データ、
`dedup_rank`（同一断面の重複除去）。

**2つの軸で分割している**（詳細は [DESIGN.md §3.5(c)](DESIGN.md)）。

- `source=` の Hive パーティション … 警察と国交省は**別系統の機器**であり、
  同一列に並べたままだと誤って合算されうるため物理分割する
  （同一断面に併設されていれば二重計上になる）。横断クエリは
  `read_parquet('counts/**/*.parquet', hive_partitioning=true)` で可能
- `stations_open` / `stations_all_restricted` … TMT座標（譲渡禁止）と
  国交省API座標（CC BY互換）を混ぜると、本来公開できる国交省地点まで
  TMTの制約に巻き込まれるため

`counts` 系は座標列を持たないため、**警察分を含めてそのまま公開できる**。

### 利用例

```python
import duckdb

con = duckdb.connect()
base = "output/202606"

# 両ソース横断（Hiveパーティションを跨いで読む）
con.sql(f"""
    SELECT source, count(*) FROM read_parquet(
        '{base}/counts_unified_1h/**/*.parquet', hive_partitioning=true)
    GROUP BY source
""").show()

# 片方だけ読む（パーティション指定でI/Oが減る）
con.sql(f"SELECT * FROM '{base}/counts_unified_1h/source=police/*.parquet'").show()
```

**ミクロ交通シミュレーションのキャリブレーションに使う場合**の流れ:

1. `counts_unified_1h/source=police/` を主軸にする（都心部は警察地点の方が高密度。
   札幌都心の対象区域内に293地点ある一方、国交省地点はほぼ無い）
2. `stations_all_restricted.parquet` から座標と `name` を引いてネットワークに紐づける
   （QGISで目視確認する場合は `.geojson` か `_geo.parquet` を開く）
3. `reports/{YYYYMM}_verify.json` の `常時ゼロ地点_uid` を**除外する**
   （感知器故障が0台として紛れ込むため。202606では警察の4.7%が該当）
4. 同一断面に国交省地点も存在する場合は**合算しない**（二重計上になる。§2.4 参照）

## データソース

| ソース | 提供形態 | 対象 | 粒度 |
|---|---|---|---|
| 断面交通量情報（都道府県警察） | JARTIC 月次ZIP（typeB） | 一般道路 | 5分・断面合計 |
| 交通量データ（国土交通省） | JARTIC 交通量API（WFS） | 直轄国道 約2,060地点 | 5分/1時間・方向別車種別 |
| 計測地点位置情報 | （公財）日本交通管理技術協会（有償CSV） | 警察計測地点 | 点座標 |

## 関連リポジトリ

- [japan-jartic-traffic-data](../japan-jartic-traffic-data) — 国交省交通量APIの日次アーカイブ（本プロジェクトの入力）
- [jartic-archive](../jartic-archive) — JARTIC月次オープンデータのアーカイブ運用
- [mlit-road-traffic-census-converter](../mlit-road-traffic-census-converter) — 道路交通センサス変換（検証用の突合先）

## 利用条件

扱うデータは**2系統で条件が正反対**なので注意（詳細は [DESIGN.md §3.5](DESIGN.md)）。

**JARTICオープンデータ（警察 断面交通量・国交省 交通量API）** — [オープンデータ利用規約](https://www.jartic.or.jp/d/opendata/riyou_kiyaku.pdf)は
**CC BY 4.0互換**で、出典表記のうえ複製・公衆送信・商用利用が可能。ただしデータは
**参考値**であり正式な交通量調査結果ではないため、その旨の明示が必要。

**TMT断面交通量計測地点位置情報（有償・詳細版）** — **提供を受けた法人・個人のみが使用可、
他者への譲渡は有償無償を問わず禁止**。座標を用いた新たな著作物の作成には、事前に
TMTへ「2次的著作物作成計画書」を提出し承認を得る必要がある。
本リポジトリでは `data/private/` に隔離し、座標を含む成果物は一切コミットしない。
