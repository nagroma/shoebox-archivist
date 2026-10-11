export type FaceStatus = 'unknown' | 'suggested' | 'confirmed' | 'ignored'

export interface Face {
  id: number
  image_id: number
  photo_id: number
  path: string
  bbox: [number, number, number, number]
  det_score: number
  status: FaceStatus
  person_id: number | null
  person_name: string | null
  confidence: number | null
  cluster_id: number | null
  /** user | keyword (only face in a photo keyworded with one person) | keyword_match | elimination | match */
  label_source: string | null
}

export interface Candidate extends Face {
  /** + looks like a face, - looks like earlier 'not a face' picks */
  score: number
  likely: 'face' | 'not_face' | null
}

export interface Candidates {
  faces: Candidate[]
  learning: { faces: number; non_faces: number; active: boolean }
  preselect: boolean
}

export interface Settings {
  detection_mode: 'thorough' | 'fast'
  pass_contrast: boolean
  pass_enlarged: boolean
  pass_rotated: boolean
  suggest_threshold: number
  keyword_autoconfirm: boolean
  min_cluster_size: number
  preselect_non_faces: boolean
}

export interface SettingsData {
  values: Settings
  defaults: Settings
  help: Record<keyof Settings, string>
  info: { library_root: string | null; data_dir: string; provider: string }
}

export interface Cluster {
  cluster_id: number
  faces: Face[]
}

export interface PersonSummary {
  id: number
  name: string
  birth_year: number | null
  death_year: number | null
  notes: string | null
  confirmed: number
  suggested: number
  cover: number | null
  /** photos whose keywords name this person */
  photos: number
  groups: string | null
}

export interface PersonDetail {
  id: number
  name: string
  birth_year: number | null
  death_year: number | null
  notes: string | null
  cover_face_id: number | null
  keywords: { id: number; category: string; name: string; photos: number }[]
  confirmed: Face[]
  suggested: Face[]
}

export interface ParsedDate {
  edtf: string
  display: string
  min: string
  max: string
  precision: string
}

export interface PhotoSummary {
  id: number
  date_text: string | null
  date: ParsedDate | null
  location: string | null
  front_id: number
  path: string
  faces: number
  named: number
}

export interface ImageInfo {
  id: number
  role: 'front' | 'back' | 'other'
  path: string
  width: number | null
  height: number | null
  is_bw: number | null
}

export interface PhotoDetail {
  id: number
  date_text: string | null
  date: ParsedDate | null
  location: string | null
  caption: string | null
  back_text: string | null
  notes: string | null
  date_source: 'xmp' | 'exif' | 'user' | 'back_ocr' | null
  date_original: string | null
  taken_at: string | null
  gps_lat: number | null
  gps_lon: number | null
  location_source: 'gps' | 'user' | null
  images: ImageInfo[]
  faces: Face[]
  keywords: PhotoKeyword[]
}

export interface Keyword {
  id: number
  category: string
  name: string
  kind: string
  person_id: number | null
  in_vocab?: number
  photos?: number
}

export interface BatchPhoto {
  id: number
  date_text: string | null
  date: ParsedDate | null
  location: string | null
  caption: string | null
  keywords: PhotoKeyword[]
}

/** source: 'file' = already in the file (the owner's), 'app' = written by this app */
export interface PhotoKeyword extends Keyword { source: 'file' | 'app' }

/** 'JohnSmith' -> 'John Smith' */
export const displayName = (name: string) =>
  name.includes(' ') ? name : name.replace(/(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])/g, ' ')

export interface IngestState {
  running: boolean
  stage?: string
  done?: number
  total?: number
  error?: string | null
  result?: { added: number; duplicates: number; dated: number; scanned: number; faces: number;
             suggestions: number; clusters: number } | null
}

export interface Stats {
  library_root: string | null
  db_token: string | null
  candidates: number
  photos: number
  people: number
  faces: Partial<Record<FaceStatus, number>>
  clusters: number
  undated: number
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* not json */ }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

const get = <T,>(url: string) => req<T>('GET', url)
const post = <T,>(url: string, body: unknown = {}) => req<T>('POST', url, body)

/** Who to assign faces to: an existing person id, or a (possibly new) name. */
export type PersonRef = { person_id: number } | { name: string }

export const api = {
  stats: () => get<Stats>('/api/stats'),
  clusters: () => get<Cluster[]>('/api/clusters'),
  recluster: (min_size?: number) => post<{ clusters: number; suggestions: number }>('/api/recluster', { min_size }),

  assign: (face_ids: number[], who: PersonRef) =>
    post<{ person_id: number }>('/api/faces/assign', { face_ids, ...who }),
  reject: (face_ids: number[]) => post('/api/faces/reject', { face_ids }),
  ignore: (face_ids: number[]) => post('/api/faces/ignore', { face_ids }),
  unignore: (face_ids: number[]) => post('/api/faces/unignore', { face_ids }),
  removeFromCluster: (face_ids: number[]) => post('/api/faces/remove-from-cluster', { face_ids }),
  ignored: () => get<Face[]>('/api/faces/ignored'),
  candidates: () => get<Candidates>('/api/faces/candidates'),
  settings: () => get<SettingsData>('/api/settings'),
  saveSettings: (changes: Partial<Settings>) => req<SettingsData>('PUT', '/api/settings', changes),
  verify: (face_ids: number[]) => post('/api/faces/verify', { face_ids }),

  people: () => get<PersonSummary[]>('/api/people'),
  person: (id: number) => get<PersonDetail>(`/api/people/${id}`),
  createPerson: (name: string) => post<PersonDetail>('/api/people', { name }),
  updatePerson: (id: number, fields: Partial<PersonDetail>) =>
    req<PersonDetail>('PATCH', `/api/people/${id}`, fields),
  mergePerson: (id: number, into: number) => post(`/api/people/${id}/merge`, { into }),
  deletePerson: (id: number) => req('DELETE', `/api/people/${id}`),

  photos: (params: { filter?: string; person_id?: number; keyword_id?: number; q?: string }) => {
    const qs = new URLSearchParams()
    if (params.filter) qs.set('filter', params.filter)
    if (params.person_id !== undefined) qs.set('person_id', String(params.person_id))
    if (params.keyword_id !== undefined) qs.set('keyword_id', String(params.keyword_id))
    if (params.q) qs.set('q', params.q)
    return get<PhotoSummary[]>(`/api/photos?${qs}`)
  },
  photo: (id: number) => get<PhotoDetail>(`/api/photos/${id}`),
  fileMetadata: (id: number) => get<{ tags: Record<string, Record<string, unknown>>
                                      app: Record<string, 'app' | 'changed' | 'managed'> }>(`/api/photos/${id}/file-metadata`),
  updatePhoto: (id: number, fields: Partial<Pick<PhotoDetail, 'date_text' | 'location' | 'caption' | 'back_text' | 'notes'>>) =>
    req<PhotoDetail>('PATCH', `/api/photos/${id}`, fields),
  keywords: () => get<Keyword[]>('/api/keywords'),
  addKeyword: (photoId: number, kw: { keyword_id: number } | { category: string; name: string }) =>
    post<PhotoKeyword[]>(`/api/photos/${photoId}/keywords`, kw),
  removeKeyword: (photoId: number, keywordId: number) =>
    req<PhotoKeyword[]>('DELETE', `/api/photos/${photoId}/keywords/${keywordId}`),
  createKeyword: (kw: { category: string; name: string }) => post<Keyword>('/api/keywords', kw),
  batchGet: (photo_ids: number[]) => post<BatchPhoto[]>('/api/photos/batch-get', { photo_ids }),
  batchEdit: (body: { photo_ids: number[]; fields?: Partial<Record<'date_text' | 'location' | 'caption', string>>
                      add_keyword_ids?: number[]; remove_keyword_ids?: number[] }) =>
    post<{ photos: number; keywords_added: number; keywords_removed: number }>('/api/photos/batch-edit', body),
  ingest: () => post<IngestState>('/api/ingest'),
  ingestStatus: () => get<IngestState>('/api/ingest/status'),
  upload: async (files: File[]) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    const res = await fetch('/api/upload', { method: 'POST', body: fd })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText)
    return res.json() as Promise<{ saved: number; skipped: string[]; folder: string }>
  },
  parseDate: (text: string) => get<{ text: string; date: ParsedDate | null }>(
    `/api/dates/parse?text=${encodeURIComponent(text)}`),
}

/** Per-database token in image URLs: ids restart after a DB reset, so without it the
 *  browser would keep showing cached pictures from the previous library. */
let cacheKey = ''
export const setCacheKey = (k: string | null | undefined) => { cacheKey = k ?? '' }
export const faceThumb = (id: number) => `/api/faces/${id}/thumb?v=${cacheKey}`
export const imageUrl = (id: number, size: 'thumb' | 'large' = 'large') =>
  `/api/images/${id}?size=${size}&v=${cacheKey}`
