import { useState } from 'react'
import { api } from '../api'
import { useAction, useApp } from '../state'

export function ShowInFinderButton({ imageId }: { imageId?: number }) {
  const { stats } = useApp()
  const run = useAction()
  const [opening, setOpening] = useState(false)
  if (!stats?.can_show_in_finder) return null

  async function reveal() {
    if (imageId === undefined || opening) return
    setOpening(true)
    try {
      await run(() => api.showInFinder(imageId))
    } finally {
      setOpening(false)
    }
  }

  return <button type="button" disabled={imageId === undefined || opening} onClick={reveal}
    title={imageId === undefined ? 'Select one photo to show it in Finder' : 'Reveal this scan file in Finder'}>
    {opening ? 'Opening Finder…' : 'Show in Finder'}
  </button>
}
