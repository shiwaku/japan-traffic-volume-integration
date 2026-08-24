# japan-traffic-volume-integration

一般道路の「断面交通量情報」（都道府県警察の車両感知器・JARTIC typeB）と
「交通量データ（国土交通省）」（直轄国道・JARTIC 交通量API）を統合し、
共通スキーマの観測点マスタ＋交通量時系列データセットを作成するプロジェクト。

設計の全容は [DESIGN.md](DESIGN.md) を参照。
Phase 1（札幌方面・2026年6月分）のパイプラインが動作済み。検証結果は [reports/](reports/) を参照。

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
| export | 座標を持つ観測点の GeoJSON 出力（PMTilesはtippecanoe導入後） |
| verify | 検証レポートJSONを `reports/` に出力（コミット対象） |

成果物は `data/output/{YYYYMM}/`（counts.parquet / counts_unified_1h.parquet /
stations.parquet / stations.geojson）。

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

本プロジェクトで扱うデータは**参考値**であり、正式な交通量調査結果ではない。
JARTIC利用規約・交通量API利用規約に基づき、取得データのそのままの再公開は行わない。
