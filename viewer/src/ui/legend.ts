import { NODATA_COLOR, RAMP, SOURCES } from '../config'

/** 凡例。色スケール（交通量）と輪郭色（ソース）は意味が違うので分けて示す。 */
export function renderLegend(el: HTMLElement, scaleMax: number, unit: string): void {
  const grad = RAMP.map(([pos, c]) => `${c} ${(pos * 100).toFixed(0)}%`).join(', ')
  const ringColor: Record<string, string> = {
    police: '#ffd166',
    mlit_cctv: '#06d6a0',
    mlit_tracan: '#4cc9f0',
  }
  el.innerHTML = `
    <div class="lg-title">交通量（塗り）</div>
    <div class="lg-bar" style="background:linear-gradient(90deg,${grad})"></div>
    <div class="lg-scale"><span>0</span><span>${scaleMax.toLocaleString()} ${unit}</span></div>
    <div class="lg-row"><i class="sw" style="background:${NODATA_COLOR}"></i>欠測・観測なし</div>
    <div class="lg-title">機器（輪郭）</div>
    ${SOURCES.map(
      (s) =>
        `<div class="lg-row"><i class="sw ring" style="border-color:${ringColor[s.key]}"></i>${s.label}</div>`,
    ).join('')}
  `
}
