import { useRef, useState } from 'react'
import { faceThumb, type Face } from '../api'
import { FacePreview } from './FacePreview'

interface Props {
  faces: Face[]
  selected: Set<number>
  onSelect: (next: Set<number>) => void
  /** Show the suggested/confirmed name under each face. */
  showNames?: boolean
  size?: number
  /** Extra label in the corner of a face (e.g. 'likely face'). */
  badge?: (f: Face) => React.ReactNode
}

/**
 * Click to select, Shift+click to select a range, double-click (or the magnifier) to see the whole photo.
 */
export function FaceGrid({ faces, selected, onSelect, showNames = true, size = 112, badge }: Props) {
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
      {faces.map((f, i) => (
        <figure
          key={f.id}
          className={`face ${f.status} ${selected.has(f.id) ? 'selected' : ''}`}
          style={{ width: size }}
          title={`${f.path}\nface #${f.id} · detection ${f.det_score.toFixed(2)}`}
          onClick={e => click(e, i)}
          onDoubleClick={() => setPreview(f)}
        >
          <img src={faceThumb(f.id)} loading="lazy" width={size} height={size} alt="" draggable={false} />
          <button
            className="open"
            title="See the whole photo"
            onClick={e => { e.stopPropagation(); setPreview(f) }}
          >🔍</button>
          {selected.has(f.id) && <span className="check">✓</span>}
          {badge?.(f)}
          {showNames && (
            <figcaption>
              {f.status === 'suggested' && <>{f.person_name}? <span className="muted">{f.confidence?.toFixed(2)}</span></>}
              {f.status === 'confirmed' && f.person_name}
              {f.status === 'unknown' && <span className="muted">#{f.id}</span>}
              {f.status === 'ignored' && <span className="muted">ignored</span>}
            </figcaption>
          )}
        </figure>
      ))}
      {preview && <FacePreview face={preview} onClose={() => setPreview(null)} />}
    </div>
  )
}
