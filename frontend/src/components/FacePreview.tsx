import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { imageUrl, type Face } from '../api'

/** The whole photo a face came from, with that face outlined. Esc or click outside closes. */
export function FacePreview({ face, onClose }: { face: Face; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const [x1, y1, x2, y2] = face.bbox
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="face-preview" onClick={e => e.stopPropagation()}>
        <div className="frame">
          <img src={imageUrl(face.image_id)} alt="" />
          <span className="box" style={{
            left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%`,
          }} />
        </div>
        <div className="row">
          <span className="muted small grow">
            {face.person_name
              ? <>{face.person_name}{face.status === 'suggested' && '?'} · </>
              : null}
            {face.path}
          </span>
          <Link to={`/photos/${face.photo_id}?face=${face.id}`}>Open photo page ↗</Link>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  )
}
