import type { Face, PhotoSummary } from './api'

export function confirmedFacesForDisplay(faces: Face[], photos: PhotoSummary[]) {
  const displayByPhoto = new Map(photos.map(photo => [photo.id, photo]))
  const withDisplayFace = new Set(faces.filter(face =>
    displayByPhoto.get(face.photo_id)?.front_id === face.image_id).map(face => face.photo_id))
  const shownFallbacks = new Set<number>()
  const alternateImages = new Map<number, PhotoSummary>()

  const visible = faces.filter(face => {
    const display = displayByPhoto.get(face.photo_id)
    if (!display || display.front_id === face.image_id) return true
    if (withDisplayFace.has(face.photo_id) || shownFallbacks.has(face.photo_id)) return false

    // Keep a confirmation visible when its face crop belongs to a different scan.
    shownFallbacks.add(face.photo_id)
    alternateImages.set(face.id, display)
    return true
  })
  return { faces: visible, alternateImages }
}
