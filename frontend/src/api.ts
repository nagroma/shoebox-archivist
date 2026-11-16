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
  people_keywords?: string[]
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

export interface Alias { name: string; kind: string; from_year: number | null }

export interface PersonSummary {
  keyword_paths: string[]
  aliases: Alias[]
  /** the name in use now (latest 'used from' year) */
  display_name: string
  name_from_year: number | null
  /** relationship to the curator, e.g. 'Parent' */
  relation: string | null
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
  keyword_ids: number[]
  aliases: Alias[]
  display_name: string
  name_from_year: number | null
  relation: string | null
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

export interface Relative { id: number; name: string; relation: string | null }
export interface Relatives {
  relation: string | null
  curator: { id: number; name: string } | null
  parents: Relative[]
  partners: Relative[]
  children: Relative[]
  siblings: Relative[]
}

export interface TreeNode {
  id: number; name: string; birth_year: number | null; death_year: number | null
  cover: number | null; gen: number; relation: string | null
}
export interface Tree {
  focus: number
  nodes: TreeNode[]
  edges: { a: number; b: number; kind: 'parent' | 'partner' }[]
  curator: number | null
}

export interface BranchPlan {
  category: string
  branches: Record<string, number>
  photos: number
  add: number
  remove: number
  applied: boolean
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

export interface KeywordScope { mode: 'all' | 'fronts' | 'backs' | 'current' | 'ask' | 'selected' | 'one'; suffixes: string[] }
export interface VariationType { suffix: string; label: string; role: 'front' | 'back' | 'other' }
export interface FaceViewPreference { preferred: string | null; also_show: string[] }
export interface FaceReview {
  view: FaceViewPreference & { effective: string; default_preferred: string; front_types: VariationType[];
    available: (VariationType & { files: number })[]; fallback: number; unscanned: number }
  clusters: Cluster[]; candidates: Candidates; ignored: Face[]
}
export interface VariationConfig {
  enabled: boolean; pattern: 'suffix' | 'serial'; preferred: string; recognition: string
  types: VariationType[]; overrides?: Record<number, string>
}
export interface SharingRule { target: 'hierarchy' | 'keyword'; path: string; scope: KeywordScope }
export interface SharingSettings { rules: SharingRule[] }
export interface GroupPreview {
  token: string; files: number; config: VariationConfig
  groups: { key: string; primary_id: number; recognition_id: number | null; issues: string[]; metadata_conflicts: string[]
    members: { id: number; path: string; label: string; suffix: string; role: string; photo_id: number }[] }[]
}
export interface KeywordDifference {
  id: string; photo_id: number; image_id: number; keyword_id: number; keyword: string; path: string
  reason?: string; variation: string; source: 'file' | 'app' | null; inherited: string; present: boolean; expected: boolean; action: 'add' | 'remove'
}
export interface ExclusiveConflict {
  id: string; photo_id: number; keyword_id: number; keyword: string; blocked: boolean
  variants: { image_id: number; path: string; variation: string; present: boolean; exception: boolean }[]
}
export interface KeywordReview {
  photos_checked?: number
  conflicts: ExclusiveConflict[]
  grouping_issues: { image_id: number; path: string; suffix: string; issue: string }[]
  differences: KeywordDifference[]; exceptions: KeywordDifference[]
  choices: { photo_id: number; keyword_id: number; keyword: string; path: string }[]
  errors: { image_id: number; path: string; error: string }[]
}

export interface ImageInfo {
  variation: string; variation_label: string; is_primary: number; recognition_enabled: number
  keyword_sources: Record<number, 'file' | 'app'>
  keyword_ids: number[]; exceptions: { keyword_id: number; present: number }[]
  id: number
  role: 'front' | 'back' | 'other'
  path: string
  width: number | null
  height: number | null
  is_bw: number | null
}

export interface PhotoDetail {
  keyword_scopes: Record<string, { scope: KeywordScope; inherited: string; library_mode: KeywordScope['mode'] }>
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
export interface PhotoKeyword extends Keyword {
  source: 'file' | 'app'
  /** a person's name as of the photo's date */
  display?: string | null
}

/** 'JohnSmith' -> 'John Smith' */
export const displayName = (name: string) =>
  name.includes(' ') ? name : name.replace(/(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])/g, ' ')

export interface IngestState {
  running: boolean
  rescan_folder?: string
  stage?: string
  done?: number
  total?: number
  error?: string | null
  result?: { added: number; duplicates: number; dated: number; scanned: number; faces: number;
             suggestions: number; clusters: number; keyword_differences?: number; keyword_choices?: number; keyword_errors?: number; variation_issues?: number } | null
}

export function scanProgressText({ stage = 'Scanning', done = 0, total }: IngestState) {
  if (!total) return `${stage}…`
  if (stage === 'Finding faces') return `Finding faces in ${done} of ${total} ${total === 1 ? 'photo' : 'photos'}`
  return `${stage} · ${done} / ${total}`
}

export function faceRescanSummary(folder: string, { scanned, faces }: NonNullable<IngestState['result']>) {
  return `Face re-scan complete for ${folder}. Checked ${scanned} ${scanned === 1 ? 'photo' : 'photos'} and found ${faces} new ${faces === 1 ? 'face' : 'faces'}.`
}

export interface Stats {
  can_show_in_finder?: boolean
  keyword_differences: number
  library_root: string | null
  db_token: string | null
  candidates: number
  photos: number
  people: number
  faces: Partial<Record<FaceStatus, number>>
  clusters: number
  undated: number
}

export interface Facet { name: string; kind: string }
export interface ProposedFacet extends Facet { found: number; from_files: boolean }
export interface Preset { label: string; help: string; facets: Facet[] }

export interface LibraryInfo {
  open: boolean
  presets: Record<string, Preset>
  kinds: string[]
  root?: string | null
  data_dir?: string | null
  /** data lives in <photo folder>/.shoebox, so the library can be reset */
  managed?: boolean
  folder_scoped?: boolean
  facets?: (Facet & { keywords: number })[]
  /** the person the library is organised around */
  curator?: { id: number; name: string } | null
}

export interface FolderListing {
  path: string
  parent: string | null
  dirs: { name: string; path: string }[]
  images: number
  has_library: boolean
  home: string
  icloud?: string
}

export type FolderFlag = 'learn' | 'identify'

export interface FolderEntry {
  path: string
  name: string
  learn: boolean
  identify: boolean
  indexed: number
  fronts: number
  scanned: number
}

export interface FolderTree {
  folders: FolderEntry[]
  keyword_file: boolean
  scoped: boolean
}

export interface ScanState {
  staged?: boolean
  keyword_file?: boolean
  running: boolean
  existing?: boolean
  folder?: string
  done?: number
  total?: number
  error?: string | null
  facets?: ProposedFacet[]
  result?: { folder: string; images: number; with_keywords: number; paths: Record<string, number>
             n_paths: number; flat: Record<string, number>; n_flat: number } | null
}

export class NoLibraryError extends Error {}

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
    if (res.status === 409 && msg === 'no_library') throw new NoLibraryError(msg)
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
  facesReview: () => get<FaceReview>('/api/faces/review'),
  saveFacesView: (preference: FaceViewPreference) => req<FaceReview>('PUT', '/api/faces/review', preference),
  recluster: (min_size?: number) => post<{ clusters: number; suggestions: number }>('/api/recluster', { min_size }),

  variations: () => get<VariationConfig>('/api/variations'),
  pauseVariations: () => post<VariationConfig>('/api/variations/pause', {}),
  previewVariations: (config: VariationConfig, overrides: Record<number, string>) =>
    post<GroupPreview>('/api/variations/preview', { config, overrides }),
  applyVariations: (config: VariationConfig, token: string, overrides: Record<number, string>) =>
    post<{ groups: number; files: number; backup: string }>('/api/variations/apply', { config, token, overrides }),
  sharing: () => get<SharingSettings>('/api/sharing'),
  saveSharing: ({ rules }: SharingSettings) =>
    req<SharingSettings>('PUT', '/api/sharing', { rules, check_on_save: false }), // Older servers still accept this option.
  keywordReview: (photo_id?: number) => get<KeywordReview>('/api/sharing/review' + (photo_id ? `?photo_id=${photo_id}` : '')),
  keepKeywordOnOneVariant: (conflict_id: string, keep_image_id: number) =>
    post<KeywordReview>('/api/sharing/keep-one', { conflict_id, keep_image_id, confirm_removals: true }),
  applyKeywordReview: (selections: { id: string; allow_owner_removal?: boolean }[]) =>
    post<{ completed: string[]; errors: { id: string; error: string }[]; review: KeywordReview }>('/api/sharing/apply', { selections }),
  photoKeywordScope: (pid: number, kid: number, scope: KeywordScope | null) =>
    req<KeywordReview>('PUT', `/api/photos/${pid}/keywords/${kid}/scope`, { scope }),
  keywordException: (image: number, kid: number, present: boolean | null) =>
    req<KeywordReview>('PUT', `/api/images/${image}/keywords/${kid}/exception`, { present }),
  assign: (face_ids: number[], who: PersonRef) =>
    post<{ person_id: number }>('/api/faces/assign', { face_ids, ...who }),
  acceptGuesses: (guesses: { face_id: number; person_id: number }[]) =>
    post<{ accepted: number }>('/api/faces/accept-guesses', { guesses }),
  reject: (face_ids: number[]) => post('/api/faces/reject', { face_ids }),
  ignore: (face_ids: number[]) => post('/api/faces/ignore', { face_ids }),
  repairFace: (faceId: number, rotate: boolean) =>
    post<{ face_id: number; revision: string }>(`/api/faces/${faceId}/repair`, { rotate }),
  unignore: (face_ids: number[]) => post('/api/faces/unignore', { face_ids }),
  removeFromCluster: (face_ids: number[]) => post('/api/faces/remove-from-cluster', { face_ids }),
  ignored: () => get<Face[]>('/api/faces/ignored'),
  candidates: () => get<Candidates>('/api/faces/candidates'),
  settings: () => get<SettingsData>('/api/settings'),
  saveSettings: (changes: Partial<Settings>) => req<SettingsData>('PUT', '/api/settings', changes),
  verify: (face_ids: number[]) => post('/api/faces/verify', { face_ids }),

  people: () => get<PersonSummary[]>('/api/people'),
  person: (id: number) => get<PersonDetail>(`/api/people/${id}`),
  createPerson: (name: string, keyword_category?: string, keyword_name?: string) =>
    post<PersonDetail>('/api/people', { name, keyword_category, keyword_name }),
  savePersonKeywords: (id: number, keyword_ids: number[], category?: string, name?: string) =>
    req<PersonDetail>('PUT', `/api/people/${id}/keywords`, { keyword_ids, category, name }),
  updatePerson: (id: number, fields: Partial<PersonDetail>) =>
    req<PersonDetail>('PATCH', `/api/people/${id}`, fields),
  saveAliases: (id: number, aliases: Alias[]) => req<Alias[]>('PUT', `/api/people/${id}/aliases`, aliases),
  relatives: (id: number) => get<Relatives>(`/api/people/${id}/relatives`),
  addRelative: (id: number, relation: 'parent' | 'child' | 'partner', who: PersonRef) =>
    post<Relatives>(`/api/people/${id}/relatives`, { relation, ...who }),
  removeRelative: (id: number, relation: 'parent' | 'child' | 'partner', other: number) =>
    req<Relatives>('DELETE', `/api/people/${id}/relatives/${relation}/${other}`),
  tree: (id: number, generations: number) => get<Tree>(`/api/family/${id}?generations=${generations}`),
  branches: () => get<BranchPlan>('/api/family-branches'),
  applyBranches: () => post<BranchPlan>('/api/family-branches'),
  mergePerson: (id: number, into: number) => post(`/api/people/${id}/merge`, { into }),
  deletePerson: (id: number) => req('DELETE', `/api/people/${id}`),

  photos: (params: { filter?: string; person_id?: number; keyword_id?: number; q?: string;
                    family_id?: number; generations?: number }) => {
    const qs = new URLSearchParams()
    if (params.filter) qs.set('filter', params.filter)
    if (params.person_id !== undefined) qs.set('person_id', String(params.person_id))
    if (params.keyword_id !== undefined) qs.set('keyword_id', String(params.keyword_id))
    if (params.q) qs.set('q', params.q)
    if (params.family_id !== undefined) {
      qs.set('family_id', String(params.family_id))
      qs.set('generations', String(params.generations ?? 1))
    }
    return get<PhotoSummary[]>(`/api/photos?${qs}`)
  },
  photo: (id: number) => get<PhotoDetail>(`/api/photos/${id}`),
  refreshPreview: (imageId: number) => post<{ revision: string }>(`/api/images/${imageId}/refresh-preview`),
  showInFinder: (imageId: number) => post<{ ok: boolean }>(`/api/images/${imageId}/show-in-finder`),
  fileMetadata: (id: number, image_id?: number) => get<{ warning: string | null; tags: Record<string, Record<string, unknown>>
                                      app: Record<string, 'app' | 'changed' | 'managed'> }>(`/api/photos/${id}/file-metadata${image_id ? `?image_id=${image_id}` : ''}`),
  updatePhoto: (id: number, fields: Partial<Pick<PhotoDetail, 'date_text' | 'location' | 'caption' | 'back_text' | 'notes'>>) =>
    req<PhotoDetail>('PATCH', `/api/photos/${id}`, fields),
  keywords: (vocabularyOnly = false) => get<Keyword[]>(`/api/keywords?vocabulary_only=${vocabularyOnly}`),
  addKeyword: (photoId: number, kw: ({ keyword_id: number } | { category: string; name: string }) & { image_id?: number; scope?: KeywordScope }) =>
    post<PhotoKeyword[]>(`/api/photos/${photoId}/keywords`, kw),
  removeKeyword: (photoId: number, keywordId: number) =>
    req<PhotoKeyword[]>('DELETE', `/api/photos/${photoId}/keywords/${keywordId}`),
  deleteKeyword: (id: number) => req('DELETE', `/api/keywords/${id}`),
  createKeyword: (kw: { category: string; name: string }) => post<Keyword>('/api/keywords', kw),
  batchGet: (photo_ids: number[]) => post<BatchPhoto[]>('/api/photos/batch-get', { photo_ids }),
  batchEdit: (body: { photo_ids: number[]; fields?: Partial<Record<'date_text' | 'location' | 'caption', string>>
                      add_keyword_ids?: number[]; remove_keyword_ids?: number[] }) =>
    post<{ photos: number; keywords_added: number; keywords_removed: number }>('/api/photos/batch-edit', body),
  ingest: () => post<IngestState>('/api/ingest'),
  rescanFolderFaces: (path: string) => post<IngestState>('/api/folders/rescan-faces', { path }),
  ingestStatus: () => get<IngestState>('/api/ingest/status'),
  upload: async (files: File[]) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    const res = await fetch('/api/upload', { method: 'POST', body: fd })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText)
    return res.json() as Promise<{ saved: number; skipped: string[]; folder: string }>
  },
  library: () => get<LibraryInfo>('/api/library'),
  listFolder: (path = '') => get<FolderListing>(`/api/fs/list?path=${encodeURIComponent(path)}`),
  inspectFolder: (folder: string, staged: boolean, preset: string) => post<ScanState>('/api/library/inspect', { folder, staged, preset }),
  folders: () => get<FolderTree>('/api/folders'),
  chooseFolder: (path: string, flag: FolderFlag, enabled: boolean) =>
    req<FolderTree>('PUT', '/api/folders', { path, flag, enabled }),
  inspectStatus: (preset: string) => get<ScanState>(`/api/library/inspect/status?preset=${preset}`),
  createLibrary: (folder: string, facets: Facet[], import_keywords: boolean, curator = '', staged = false) =>
    post<LibraryInfo>('/api/library/create', { folder, facets, import_keywords, curator, staged }),
  setCurator: (name: string) => req<{ id: number; name: string } | null>('PUT', '/api/library/curator', { name }),
  openLibrary: (folder: string) => post<LibraryInfo>('/api/library/open', { folder }),
  closeLibrary: () => post<LibraryInfo>('/api/library/close'),
  resetLibrary: (confirm: string) => post<LibraryInfo>('/api/library/reset', { confirm }),
  saveFacets: (facets: Facet[]) => req<(Facet & { keywords: number })[]>('PUT', '/api/facets', facets),
  parseDate: (text: string) => get<{ text: string; date: ParsedDate | null }>(
    `/api/dates/parse?text=${encodeURIComponent(text)}`),
}

/** Per-database token in image URLs: ids restart after a DB reset, so without it the
 *  browser would keep showing cached pictures from the previous library. */
let cacheKey = ''
const faceThumbRevisions = new Map<number, string>()
export const setCacheKey = (k: string | null | undefined) => {
  if (cacheKey !== (k ?? '')) faceThumbRevisions.clear()
  cacheKey = k ?? ''
}
export const setFaceThumbRevision = (id: number, revision: string) => { faceThumbRevisions.set(id, revision) }
export const faceThumb = (id: number) => `/api/faces/${id}/thumb?v=${cacheKey}&preview=${faceThumbRevisions.get(id) ?? '2'}`
export const imageUrl = (id: number, size: 'thumb' | 'large' = 'large', revision = '2') =>
  `/api/images/${id}?size=${size}&v=${cacheKey}&preview=${revision}`
