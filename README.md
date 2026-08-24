# japan-traffic-volume-integration

一般道路の「断面交通量情報」（都道府県警察の車両感知器・JARTIC typeB）と
「交通量データ（国土交通省）」（直轄国道・JARTIC 交通量API）を統合し、
共通スキーマの観測点マスタ＋交通量時系列データセットを作成するプロジェクト。

**現在は設計フェーズ。** 設計の全容は [DESIGN.md](DESIGN.md) を参照。

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
