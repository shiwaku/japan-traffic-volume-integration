import type maplibregl from 'maplibre-gl'

import { BASEMAPS, type Basemap } from '../basemap'

/** 背景地図の切替（地図右下）。 */
export class BasemapControl implements maplibregl.IControl {
  private container!: HTMLDivElement

  constructor(
    private get: () => Basemap,
    private set: (b: Basemap) => void,
  ) {}

  onAdd(): HTMLElement {
    this.container = document.createElement('div')
    this.container.className = 'maplibregl-ctrl maplibregl-ctrl-group basemap-ctrl'
    for (const { key, label } of BASEMAPS) {
      const b = document.createElement('button')
      b.type = 'button'
      b.textContent = label
      b.dataset.key = key
      b.addEventListener('click', () => this.set(key))
      this.container.appendChild(b)
    }
    this.sync()
    return this.container
  }

  onRemove(): void {
    this.container.remove()
  }

  sync(): void {
    const cur = this.get()
    for (const b of this.container.querySelectorAll('button')) {
      b.classList.toggle('active', (b as HTMLButtonElement).dataset.key === cur)
    }
  }
}
