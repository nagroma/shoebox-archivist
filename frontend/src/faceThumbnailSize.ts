import { useState } from 'react'

const STORAGE_KEY = 'shoebox.faces.thumbnailSize'
export const FACE_THUMBNAIL_SIZE = { min: 64, max: 192, step: 8, default: 112 }

function loadThumbnailSize() {
  const { min, max, step } = FACE_THUMBNAIL_SIZE
  try {
    const saved = Number(localStorage.getItem(STORAGE_KEY))
    if (saved >= min && saved <= max && (saved - min) % step === 0) return saved
  } catch { /* Browser storage can be unavailable. */ }
  return FACE_THUMBNAIL_SIZE.default
}

export function useFaceThumbnailSize() {
  const [size, setSize] = useState(loadThumbnailSize)

  function updateSize(next: number) {
    setSize(next)
    try { localStorage.setItem(STORAGE_KEY, String(next)) } catch { /* Keep the in-page setting. */ }
  }

  return [size, updateSize] as const
}
