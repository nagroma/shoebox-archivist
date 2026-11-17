import { useRef, useState } from 'react'
import { displayName, faceThumb, imageUrl, type Face, type PhotoSummary } from '../api'
import { FACE_THUMBNAIL_SIZE } from '../faceThumbnailSize'
import { FacePreview } from './FacePreview'

export function FaceThumbnailSizeSlider({ size, onChange }: { size: number; onChange: (size: number) => void }) {
  const { min, max, step } = FACE_THUMBNAIL_SIZE
  return (
    <label className="row muted">Thumbnail size
      <input className="face-thumbnail-size" type="range" min={min} max={max} step={step} value={size}
        aria-valuetext={`${size} pixels`} onChange={e => onChange(Number(e.target.value))} />
      <span aria-hidden="true">{size} px</span>
    </label>
  )
}

export function PeopleKeywordsCheckbox({ checked, onChange }: { checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="row small">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      Show People keywords on each photo
    </label>
  )
}

interface Props {
  faces: Face[]
  selected: Set<number>
  onSelect: (next: Set<number>) => void
  /** Show the suggested/confirmed name under each face. */
  showNames?: boolean
  showPeopleKeywords?: boolean
  /** Whole photos to show when a face crop is on a different scan variant. */
  alternateImages?: ReadonlyMap<number, PhotoSummary>
  size?: number
  /** Extra label in the corner of a face (e.g. 'likely face'). */
  badge?: (f: Face) => React.ReactNode
}

/**
 * Click to select, Shift+click to select a range, double-click (or the magnifier) to see the whole photo.
 */
export function FaceGrid({
  faces, selected, onSelect, showNames = true, showPeopleKeywords = false,
  alternateImages, size = FACE_THUMBNAIL_SIZE.default, badge,
}: Props) {
  const last = useRef<number | null>(null)
  const [preview, setPreview] = useState<Face | null>(null)

  function click(e: React.MouseEvent, idx: number) {
    const next = new Set(selected)
    if (e.shiftKey && last.current !== null) {
      const [a, b] = [last.current, idx].sort((x, y) => x - y)
      const add = !selected.has(faces[idx].id)
      for (let i = a; i <= b; i++) {
        if (add) next.add(faces[i].id); else next.delete(faces[i].id)
      }
    } else if (next.has(faces[idx].id)) {
      next.delete(faces[idx].id)
    } else {
      next.add(faces[idx].id)
    }
    last.current = idx
    onSelect(next)
  }

  return (
    <div className="face-grid">
      {faces.map((f, i) => {
        const alternateImage = alternateImages?.get(f.id)
        const taggedPeople = showPeopleKeywords && f.status === 'suggested' && f.people_keywords
          ? [...new Set(f.people_keywords.map(path => displayName(path.slice(path.lastIndexOf('|') + 1))))]
          : []
        return (
          <figure
            key={f.id}
            className={`face ${f.status} ${selected.has(f.id) ? 'selected' : ''}`}
            style={{ width: size }}
            title={alternateImage?.path ?? `${f.path}\nface #${f.id} · detection ${f.det_score?.toFixed(2) ?? '—'}`}
            onClick={e => click(e, i)}
            onDoubleClick={() => setPreview(f)}
          >
            <img className={alternateImage ? 'whole-photo' : undefined}
              src={alternateImage ? imageUrl(alternateImage.front_id, 'thumb') : faceThumb(f.id)}
              loading="lazy" width={size} height={size} alt="" draggable={false} />
            <button
              className="open"
              title="See the whole photo"
              onClick={e => { e.stopPropagation(); setPreview(f) }}
            >🔍</button>
            {selected.has(f.id) && <span className="check">✓</span>}
            {badge?.(f)}
            {(showNames || taggedPeople.length > 0) && (
              <figcaption>
                {showNames && <div className="face-name">
                  {f.status === 'suggested' && <>{f.person_name}? <span className="muted">{f.confidence?.toFixed(2)}</span></>}
                  {f.status === 'confirmed' && f.person_name}
                  {f.status === 'unknown' && <span className="muted">#{f.id}</span>}
                  {f.status === 'ignored' && <span className="muted">ignored</span>}
                </div>}
                {taggedPeople.length > 0 && <ul className="face-people-keywords muted" aria-label="People tagged in this photo">
                  {taggedPeople.map(name => <li key={name}>{name}</li>)}
                </ul>}
              </figcaption>
            )}
          </figure>
        )
      })}
      {preview && <FacePreview face={preview} alternateImage={alternateImages?.get(preview.id)}
        onClose={() => setPreview(null)} />}
    </div>
  )
}
