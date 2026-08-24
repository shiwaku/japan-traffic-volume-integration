# 統合交通量データ 設計書

一般道路の「断面交通量情報」（都道府県警察の車両感知器）と「交通量データ（国土交通省）」
（直轄国道の常設トラカン・CCTVトラカン）を統合し、共通スキーマの観測点マスタ＋交通量
時系列データセットを作成する。

- 作成日: 2026-08-25
- ステータス: 承認済み（Phase 1 = 札幌方面、TMT詳細版A 1地域購入。残る確認事項は §9 参照）

---

## 1. 目的・背景

- 警察の断面交通量は**一般道（都道府県道・市町村道を含む）を広くカバー**するが、
  座標が直接付与されておらず、単位も「断面合計・台/5分」のみ。
- 国交省の交通量データは**直轄国道約2,060地点に限られる**が、座標付き・方向別・車種別で
  リッチ。ただし API の保持期間が短い（5分値=1ヶ月、1時間値=3ヶ月）。
- 両者を統合すれば、都市内の一般道から幹線国道までを1つの観測点マスタ・1つの時系列
  スキーマで扱える。用途例:
  - `sapporo-micro-traffic-sim` の需要キャリブレーション・冬季検証（コードン断面の実測値）
  - 交通量ビューワでの全国可視化（既存 `japan-jartic-traffic-data` ビューワの拡張）
  - 道路交通センサス（`mlit-road-traffic-census-converter`）との突合・経年比較

## 2. データソース

### 2.1 断面交通量情報（都道府県警察） — JARTIC typeB

| 項目 | 内容 |
|---|---|
| 提供元 | JARTIC オープンデータ（月次ZIP一括） |
| カタログ | `https://www.jartic.or.jp/d/opendata/opendata.json`（機械可読。typeB/C/D/M の最新リンク一覧） |
| URL形式 | `https://www.jartic.or.jp/d/opendata/{公開タイムスタンプ}/typeB_{地域ローマ字}_{YYYY_MM}.zip` |
| 地域数 | 51（47都道府県。北海道は方面本部別に5分割: sapporo/hakodate/asahikawa/kushiro/kitami） |
| 公開ラグ | **約2ヶ月**（例: 2026年6月分 → 2026-08-01 公開） |
| 文字コード | Shift_JIS |
| 粒度 | 5分値・断面合計（方向・車種の内訳なし。ただし計測地点は進行方向別に存在） |

CSVスキーマ（実データで確認済み・2026年6月 札幌方面）:

```
時刻, 情報源コード, 計測地点番号, 計測地点名称, 2次メッシュコード,
リンク区分, リンク番号, 断面交通量, リンク終端からの距離（×10m）, リンクバージョン
```

- `時刻`: `YYYY/MM/DD hh:mm`（5分刻み）
- `情報源コード`: 都道府県警察（方面本部）コード。例 3001=北海道警（札幌方面）。
  既存マスタ `GIS/JARTIC/情報源コード.csv` あり
- `計測地点番号`: 情報源コード内で一意。**地点の一意キーは (情報源コード, 計測地点番号)**
- `計測地点名称`: 例「樽）勝納１０番地東西」— 末尾2文字が進行方向を示唆（東西/西東/南北…）
- 位置参照: **座標なし**。DRM（デジタル道路地図）の
  `2次メッシュコード + リンク区分 + リンク番号 + リンク終端からの距離(×10m) + リンクバージョン`
  で表現される（§3.1 の位置特定戦略を参照）

実測規模（typeB_sapporo_2026_06、1ヶ月分）:

| 指標 | 値 |
|---|---|
| ZIP → CSV | 約1.1GB（1ファイル） |
| レコード数 | 14,763,911 |
| 計測地点数 | 1,910 |
| 期間 | 2026/06/01 00:00 〜 2026/06/30 23:55（5分値） |
| 断面交通量が空欄の行 | 0（欠測地点は行ごと出力されない可能性あり。要確認 §9） |

全国概算: 札幌方面が全体の約1/25〜1/30と仮定すると、**全国で月4〜5億レコード・raw 30GB級**。
列指向フォーマット（Parquet+zstd）とDuckDBでの処理を前提にする。

### 2.2 交通量データ（国土交通省） — JARTIC typeM（WFS API）

| 項目 | 内容 |
|---|---|
| 提供元 | JARTIC 交通量API `https://api.jartic-open-traffic.org/geoserver`（WFS 2.0.0） |
| 対象 | 全国の直轄国道（道路種別=3のみ）約2,060地点 |
| 座標 | GeoJSON/CSVに WGS84 座標付き（MULTIPOINT） |
| 提供タイミング | 観測の約20分後 |
| 保持期間 | 5分値=過去1ヶ月、1時間値=過去3ヶ月 → **継続アーカイブが必須** |

4様式（typeNames）:

| 様式 | typeNames | 観測機器 | 間隔 |
|---|---|---|---|
| 1 | `t_travospublic_measure_5m` | 常設トラカン | 5分 |
| 2 | `t_travospublic_measure_1h` | 常設トラカン | 1時間 |
| 3 | `t_travospublic_measure_5m_img` | CCTVトラカン(AI画像認識) | 5分 |
| 4 | `t_travospublic_measure_1h_img` | CCTVトラカン(AI画像認識) | 1時間 |

主要カラム: `常時観測点コード`（一意キー）, 観測年月日, 時間帯, 時間コード,
上り/下り × 小型/大型/車種判別不能 交通量, 機器品質フラグ（停電・ループ異常・欠測等。
様式3/4はカメラ品質フラグ群）, 道路種別, ジオメトリ。

> **既存資産**: `GIS/japan-jartic-traffic-data` に全926リクエスト/日次の取得パイプライン
> （GitHub Actionsで毎日 11:00 JST 実行、S3配信）が稼働済み。本プロジェクトは
> ここで蓄積した `data/shoshiki{1..4}/*.csv` を入力として再利用する（再取得しない）。
> API利用上の注意（cql_filter のフィールド名はクォート不可、レスポンス約6MB上限、
> CSVのエスケープ仕様）は同リポジトリ CLAUDE.md に記載済み。

### 2.3 警察計測地点の位置情報 — 交通管理技術協会（TMT）

- 提供ページ: `https://www.tmt.or.jp/research/index9.html`（断面交通量計測地点位置情報）
- **概要版**: PDF地図のみ・無償（座標データなし）
- **詳細版A**: PDF地図 + **CSV（緯度経度）**。1地域 3,300円 / 全国 33,000円（税込）
- **詳細版B**: 詳細版A + Shapefile。1地域 5,500円 / 全国 55,000円（税込）
- キーは (情報源コード, 計測地点番号) と想定（typeC 交差点位置情報
  `index10.html` と同様の構成。`jartic-archive` で結合率 97.34% の実績あり）

## 3. 主要な設計課題と方針

### 3.1 課題1: 警察データの位置特定

| 案 | 方法 | 精度 | コスト | 備考 |
|---|---|---|---|---|
| **A（推奨）** | TMT詳細版A/BのCSV座標を購入して結合 | 点位置そのもの | 3,300円/地域〜 | typeCでの結合実績と同じパターン。まず1地域で検証 |
| B | DRMリンクデータでリンク番号→線形上の位置を解決 | 高（リンク上の正確な位置） | DRMライセンス（高額・契約） | 汎用性は高いが個人/小規模では非現実的 |
| C | 2次メッシュ重心への近似配置 | 約10km四方 → 可視化にも不足 | 無料 | 位置未購入地域のフォールバック表示のみ |

方針: **案A**。座標CSVは有償データのため `data/private/` に置き、**リポジトリ・成果物の
再配布対象から除外**する（§3.5）。購入前でもパイプラインは位置なし（geometry=NULL）で
動く設計とし、位置結合は独立ステップにする。

### 3.2 課題2: スキーマの非対称性

警察=断面合計のみ、国交省=方向別×車種別。統合は**「共通最小分母への正規化」と
「ソース固有詳細の保持」の2層**で行う。

- 共通層（統合ビュー）: `台/5分・断面合計`。国交省側は 上り+下り、小型+大型+判別不能 を合算
- 詳細層: ソース別 long format をそのまま保持（direction / vehicle_class 付き）

### 3.3 課題3: 時間軸の非対称性

- 警察: 月次バッチ（約2ヶ月遅れ）。過去分はアーカイブされない可能性が高い
  → **毎月1日過ぎに opendata.json を見て新月分を取得・アーカイブ**（`jartic-archive` と同じ運用）
- 国交省: 準リアルタイムだが保持1〜3ヶ月 → 既存の日次アーカイブを継続利用
- 統合データセットの単位は**「年月」パーティション**とし、両ソースが揃った月から生成する

### 3.4 課題4: 重複観測（クロスバリデーション）

直轄国道上では警察感知器と国交省トラカンが併存しうる。

- 統合観測点マスタで **近接マッチ（例: 同一路線・半径100m以内）** の対応表
  `station_pairs` を作る（位置情報取得後）
- 対応ペアは月次で相関・比率をレポートし、機器異常や単位系の齟齬の検知に使う
- 統合ビューでは両方を残す（機械的に片方を捨てない）。重複を除きたい用途向けに
  `dedup_rank` 列（同一断面での優先順位）を付与

### 3.5 課題5: ライセンス・再配布

- JARTIC/国交省とも「**参考値**」明示が必須。APIレスポンス等の**そのまま再公開は制限**
- TMT詳細版（有償）の座標データは購入者の利用範囲内 → **座標付き成果物の公開可否は要確認**。
  当面、成果物は自己利用・内部共有に留める（S3の Referer 制限配信は既存運用に準拠）
- 出典表記例:
  `出典：JARTIC交通量オープンデータ（都道府県警察 断面交通量情報・国土交通省 交通量データ）（参考値）、計測地点位置情報：（公財）日本交通管理技術協会`

## 4. 統合データモデル

### 4.1 stations（統合観測点マスタ / GeoParquet + PMTiles）

| 列 | 型 | 説明 |
|---|---|---|
| station_uid | str | `police:{情報源コード}:{計測地点番号}` / `mlit:{常時観測点コード}` |
| source | str | `police` / `mlit` |
| name | str | 計測地点名称（警察）/ 観測点名（国交省は空） |
| pref_code | str | 都道府県コード（警察は情報源コード→変換、国交省は開発建設部／都道府県コード） |
| direction_hint | str | 警察: 名称末尾から抽出した方向（東西/南北等）。国交省: NULL（up/downは計測値側） |
| road_class | str | 国交省: 道路種別（3=一般国道）。警察: NULL（DRMリンク区分を保持） |
| drm_mesh / drm_link_kind / drm_link_no / drm_dist_from_end / drm_version | str/int | 警察のみ。DRM位置参照の原値 |
| observer_type | str | 警察: `loop` 等不明→NULL / 国交省: `tracan` / `cctv` |
| geometry | Point | WGS84。警察は TMT結合後に付与（未結合は NULL） |
| location_source | str | `tmt_csv` / `mlit_api` / `mesh_approx` / `none` |

### 4.2 counts（交通量 long format / Parquet、`year_month` × `source` パーティション）

| 列 | 型 | 説明 |
|---|---|---|
| station_uid | str | ↑参照 |
| ts | timestamp(JST) | 期間開始時刻 |
| interval | str | `5m` / `1h` |
| direction | str | `up` / `down` / `section`（警察は常に `section`） |
| vehicle_class | str | `small` / `large` / `unknown` / `all`（警察は常に `all`） |
| volume | int | 台数。欠測は NULL |
| quality | str | 品質フラグを圧縮した文字列（例 `ok`, `missing`, `power_outage`, `camera_ng`） |
| source | str | `police` / `mlit_tracan` / `mlit_cctv` |

### 4.3 counts_unified（統合ビュー / DuckDB VIEW または派生Parquet）

`断面5分合計` に正規化: 警察はそのまま、国交省は direction/vehicle_class を合算
（いずれかが欠測なら quality に反映）。列: `station_uid, ts, volume_total_5m, quality, source`。

## 5. パイプライン

`mlit-road-traffic-census-converter` と同じ **`run.py --step` + `configs/*.yaml`** 構成を踏襲。

```
japan-traffic-volume-integration/
├── DESIGN.md
├── README.md
├── configs/
│   ├── regions.yaml        # 対象地域（typeB地域ローマ字⇔情報源コード⇔都道府県）
│   └── pipeline.yaml       # パス・期間・並列数
├── integrator/
│   ├── catalog.py          # opendata.json の取得・差分検知
│   ├── fetch_police.py     # typeB zip 取得（レジューム対応）
│   ├── parse_police.py     # SJIS CSV → counts parquet + 地点抽出
│   ├── ingest_mlit.py      # japan-jartic-traffic-data の CSV → counts parquet
│   ├── stations.py         # 観測点マスタ生成・TMT座標結合・近接ペア検出
│   ├── unify.py            # counts_unified 生成（DuckDB）
│   ├── export.py           # GeoParquet / PMTiles / 時刻別JSON
│   └── verify.py           # 結合率・欠測率・ペア相関レポート（reports/ にJSONコミット）
├── scripts/                # 薄いラッパー（単体実行用）
├── data/                   # .gitignore 対象
│   ├── police/{region}/{YYYYMM}/   # raw zip + parquet
│   ├── mlit/                        # japan-jartic-traffic-data からのシンボリックリンク or コピー
│   ├── private/tmt/                 # 購入した位置情報CSV（再配布禁止）
│   └── output/{YYYYMM}/
└── reports/                # 検証レポートJSON（コミット対象）
```

ステップ実行例:

```bash
python run.py --step fetch-police --regions sapporo --month 2026-06
python run.py --step parse-police --regions sapporo --month 2026-06
python run.py --step ingest-mlit  --month 2026-06
python run.py --step stations     # TMT CSV があれば座標結合
python run.py --step unify --month 2026-06
python run.py --step export --formats parquet,pmtiles,json
python run.py --step verify
```

技術選定:

- **DuckDB** を集計エンジンに採用（月5億レコード級でもローカル処理可能、
  Parquet直読み・空間拡張あり）
- 変換は Python 標準 + duckdb + pyarrow。GDAL/tippecanoe はエクスポートのみ
- 5分値→1時間値の再集計は unify 内で実施（警察5分値から1h集計を作り
  国交省1h値と揃える）

## 6. 検証（verify ステップで毎月レポート化）

1. **地点数の推移**: 地域×月ごとの計測地点数（センサ増減の検知）
2. **TMT結合率**: 座標が付いた警察地点の割合（typeC実績: 97.3%）
3. **欠測率**: source×地域×月ごと
4. **ペア相関**: station_pairs の日交通量相関係数・比率分布（≥0.9 を健全の目安に）
5. **既知値との突合**: 道路交通センサス（R03）の平日24h交通量と、
   統合データの平日平均24h断面交通量の比較（オーダー検証）

## 7. フェーズ計画

| フェーズ | 範囲 | 内容 |
|---|---|---|
| **Phase 1** | 札幌方面（typeB_sapporo）+ 国交省北海道分 | パイプライン一式・TMT詳細版A（1地域）で位置結合検証・sapporo-micro-traffic-sim への供給 |
| Phase 2 | 全国 | 地域ループ化・月次自動実行（GitHub Actions）・容量最適化 |
| Phase 3 | 可視化・公開 | ビューワ統合（既存 japan-jartic-traffic-data ビューワの2ソース対応）※ライセンス確認後 |

## 8. 既存資産の再利用マップ

| 資産 | 再利用内容 |
|---|---|
| `japan-jartic-traffic-data` | 国交省API取得済みCSV（毎日自動更新）、API仕様ノウハウ（CLAUDE.md）、ビューワ設計 |
| `jartic-archive` | opendata.json カタログ取得・月次アーカイブ運用、TMT位置結合の実装パターン（typeC 結合率97.34%） |
| `GIS/JARTIC/情報源コード.csv` | 情報源コード→都道府県警察のマスタ |
| `mlit-road-traffic-census-converter` | run.py --step / configs/yaml のパイプライン構成、verify/レポート方式、センサス突合データ |
| `sapporo-micro-traffic-sim` | Phase 1 の主要ユーザー。コードン断面の需要キャリブレーション入力 |

## 9. 決定事項と残る確認事項

### 決定済み（2026-08-25）

1. **スコープ**: Phase 1 は**札幌方面（typeB_sapporo）**から開始
2. **位置情報**: **TMT詳細版A を1地域（北海道・札幌方面）購入**（3,300円）。
   結合検証後に全国版購入を判断。購入手続きは
   `https://www.tmt.or.jp/research/index9.html`（支払後5営業日以内にDL用URL送付）

### 残る確認事項

1. **購入データの共有範囲**: TMT座標を使った成果物の社内共有/公開の可否（TMTの利用条件を確認）
2. **対象期間**: 何ヶ月分を遡って整備するか（警察typeBは公開中の月しか取れない
   可能性が高い → 早期に月次アーカイブ開始すべき）
3. **欠測の表現**: typeB で感知器停止時に「行が無い」のか「0が入る」のかの実データ確認
   （0と欠測の区別は品質上重要）
4. **リンク区分の意味**: typeB `リンク区分`（1/2…）のコード表の入手（DRM仕様）
5. **国交省1時間値と警察5分値集計の整合**: 端数・集計境界の扱い
