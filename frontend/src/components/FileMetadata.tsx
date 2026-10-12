import { useEffect, useState } from 'react'
import { api } from '../api'

type Meta = Awaited<ReturnType<typeof api.fileMetadata>>

/** What each tag family is and who usually writes it. Key = 'group.namespace'. */
const NAMESPACES: Record<string, string> = {
  'exif.Image': 'EXIF: written by the camera/scanner (size, orientation, software)',
  'exif.Photo': 'EXIF: capture details (date taken, exposure, lens, focal length)',
  'exif.GPSInfo': 'EXIF: GPS position',
  'exif.Thumbnail': 'EXIF: embedded preview image',
  'iptc.Envelope': 'IPTC-IIM: legacy record header',
  'iptc.Application2': 'IPTC-IIM: legacy copy of keywords / caption / date, kept by Bridge and Photoshop',
  'xmp.dc': 'XMP Dublin Core: flat keywords (subject), caption (description)',
  'xmp.lr': 'XMP Lightroom: hierarchical keywords (Category|Name)',
  'xmp.photoshop': 'XMP Photoshop: date created and other IPTC-style fields',
  'xmp.iptc': 'XMP IPTC Core: location and other IPTC fields',
  'xmp.xmp': 'XMP basic: creator tool, create/modify dates, rating',
  'xmp.xmpMM': 'XMP Media Management: Adobe document IDs and edit history',
  'xmp.crs': 'XMP Camera Raw: develop settings',
  'xmp.tiff': 'XMP copy of EXIF image fields',
  'xmp.exif': 'XMP copy of EXIF capture fields',
  'xmp.ff': 'XMP FastFoto: written by the Epson FastFoto scanner',
  'xmp.kbrg': 'XMP Bridge: Adobe Bridge private data',
  'xmp.pm': 'XMP Shoebox Archivist (pm:): written by THIS app (what it added, original values)',
}

const BADGE = {
  app: ['app', 'Written by this app'],
  changed: ['changed', 'This app has changed it (the original value is saved in pm:Original…)'],
  managed: ['managed', 'This app updates it when you edit keywords, caption, date or location'],
} as const

const show = (v: unknown) => typeof v === 'string' ? v : JSON.stringify(v)

/** Every EXIF / IPTC / XMP tag in the front image, read-only (for debugging). */
export function FileMetadata({ photoId }: { photoId: number }) {
  const [data, setData] = useState<Meta | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.fileMetadata(photoId).then(setData, e => setError((e as Error).message))
  }, [photoId])

  return (
    <section className="card">
      <h2>File metadata <span className="muted small">(read-only)</span></h2>
      {error && <p className="muted small">{error}</p>}
      {!data && !error && <p className="muted small">Loading…</p>}
      {data && <p className="muted small">
        Tags come from several programs (camera, scanner, Bridge, Lightroom…).
        Marked <span className="tag-badge app">app</span> / <span className="tag-badge changed">changed</span> /{' '}
        <span className="tag-badge managed">managed</span> = written by this app, changed by it, or updated by it when you edit.
      </p>}
      {data?.warning && <p className="hint error">{data.warning}</p>}
      {data && Object.entries(data.tags).map(([group, tags]) => {
        const byNs = new Map<string, [string, unknown][]>()
        for (const [k, v] of Object.entries(tags)) {
          const ns = k.split('.')[1]
          byNs.set(ns, [...(byNs.get(ns) ?? []), [k, v]])
        }
        return (
          <details key={group} open>
            <summary>{group.toUpperCase()} <span className="muted">({Object.keys(tags).length})</span></summary>
            <table className="meta-table">
              {[...byNs.entries()].map(([ns, rows]) => (
                <tbody key={ns}>
                  <tr className="ns"><td colSpan={2}>
                    <b>{ns}</b> <span className="muted">{NAMESPACES[`${group}.${ns}`] ?? ''}</span>
                  </td></tr>
                  {rows.map(([k, v]) => {
                    const mark = data.app[k]
                    return (
                      <tr key={k} className={mark ? 'app-tag' : ''}>
                        <td>
                          {k.split('.').slice(2).join('.')}
                          {mark && <span className={`tag-badge ${mark}`} title={BADGE[mark][1]}>{BADGE[mark][0]}</span>}
                        </td>
                        <td>{show(v)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              ))}
            </table>
          </details>
        )
      })}
    </section>
  )
}
