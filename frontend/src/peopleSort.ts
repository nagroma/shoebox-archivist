import type { PersonSummary } from './api'

export const PEOPLE_SORT_OPTIONS = {
  photos: { label: 'Number of photos', direction: 'desc' },
  faces: { label: 'Number of faces', direction: 'desc' },
  review: { label: 'Number to review', direction: 'desc' },
  firstName: { label: 'First name', direction: 'asc' },
  lastName: { label: 'Last name', direction: 'asc' },
} as const

export type PeopleSortKey = keyof typeof PEOPLE_SORT_OPTIONS
export type PeopleSort = { key: PeopleSortKey; direction: 'asc' | 'desc' }

const PEOPLE_SORT_STORAGE_KEY = 'shoebox.people.sort'
const DEFAULT_SORT: PeopleSort = { key: 'review', direction: 'desc' }
const alphabetical = new Intl.Collator(undefined, { sensitivity: 'base' })
let sessionSort: PeopleSort | undefined

export function parsePeopleSort(saved: string | null): PeopleSort {
  try {
    const value = JSON.parse(saved ?? 'null')
    if (typeof value?.key === 'string' && Object.prototype.hasOwnProperty.call(PEOPLE_SORT_OPTIONS, value.key)
      && (value.direction === 'asc' || value.direction === 'desc')) {
      return { key: value.key, direction: value.direction }
    }
  } catch { /* Use the default if the saved preference is invalid. */ }
  return DEFAULT_SORT
}

export function loadPeopleSort(): PeopleSort {
  if (sessionSort) return sessionSort
  try { return parsePeopleSort(localStorage.getItem(PEOPLE_SORT_STORAGE_KEY)) }
  catch { return DEFAULT_SORT }
}

export function rememberPeopleSort(sort: PeopleSort) {
  sessionSort = sort
  try { localStorage.setItem(PEOPLE_SORT_STORAGE_KEY, JSON.stringify(sort)) }
  catch { /* Keep the sort when navigating within this session. */ }
}

export function sortPeople(people: readonly PersonSummary[], { key, direction }: PeopleSort): PersonSummary[] {
  const order = direction === 'asc' ? 1 : -1
  const rows = people.map(person => {
    const fullName = person.display_name.trim() || person.name.trim()
    const words = fullName ? fullName.split(/\s+/) : []
    return {
      person, fullName,
      firstName: words[0] ?? '',
      lastName: words.length > 1 ? words[words.length - 1] : '',
      photos: person.photos, faces: person.confirmed, review: person.suggested,
    }
  })
  rows.sort((a, b) => {
    if (key === 'firstName' || key === 'lastName') {
      if (Boolean(a[key]) !== Boolean(b[key])) return a[key] ? -1 : 1
      const byName = alphabetical.compare(a[key], b[key])
      if (byName) return order * byName
    } else {
      const byCount = a[key] - b[key]
      if (byCount) return order * byCount
    }
    if (Boolean(a.fullName) !== Boolean(b.fullName)) return a.fullName ? -1 : 1
    return alphabetical.compare(a.fullName, b.fullName) || a.person.id - b.person.id
  })
  return rows.map(row => row.person)
}
