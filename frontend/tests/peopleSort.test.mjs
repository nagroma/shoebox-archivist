import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/peopleSort.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
const { PEOPLE_SORT_OPTIONS, parsePeopleSort, sortPeople, loadPeopleSort, rememberPeopleSort } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

const person = (id, display_name, photos, confirmed, suggested, name = display_name) =>
  ({ id, display_name, name, photos, confirmed, suggested })
const people = [
  person(1, 'Zane Adams', 5, 1, 7),
  person(5, '', 3, 0, 0),
  person(3, 'Ben Young', 5, 3, 2),
  person(4, 'Cher', 0, 1, 0),
  person(2, 'Amy Young', 3, 9, 7),
  person(6, ' ', 2, 5, 1, 'Cal West'),
]

for (const [key, asc, desc] of [
  ['photos',     [4, 6, 2, 5, 3, 1], [3, 1, 2, 5, 6, 4]],
  ['faces',      [5, 4, 1, 3, 6, 2], [2, 6, 3, 4, 1, 5]],
  ['review',     [4, 5, 6, 3, 2, 1], [2, 1, 3, 6, 4, 5]],
  ['firstName',  [2, 3, 6, 4, 1, 5], [1, 4, 6, 3, 2, 5]],
  ['lastName',   [1, 6, 2, 3, 4, 5], [2, 3, 6, 1, 4, 5]],
]) {
  test(`sort by ${key} in both directions, with alphabetical ties`, () => {
    for (const [direction, expected] of [['asc', asc], ['desc', desc]]) {
      assert.deepEqual(sortPeople(people, { key, direction }).map(p => p.id), expected)
    }
    assert.deepEqual(people.map(p => p.id), [1, 5, 3, 4, 2, 6])
  })
}

test('initial sort and per-option directions match the controls', () => {
  assert.deepEqual(parsePeopleSort(null), { key: 'review', direction: 'desc' })
  assert.deepEqual(Object.values(PEOPLE_SORT_OPTIONS).map(option => option.direction),
    ['desc', 'desc', 'desc', 'asc', 'asc'])
  for (const invalid of ['{', '{"key":"toString","direction":"asc"}', '{"key":"photos","direction":"sideways"}']) {
    assert.deepEqual(parsePeopleSort(invalid), { key: 'review', direction: 'desc' })
  }
})

test('saved preference is restored and a new choice survives navigation', () => {
  const storage = new Map([['shoebox.people.sort', '{"key":"lastName","direction":"desc"}']])
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => storage.get(key),
    setItem: (key, value) => storage.set(key, value),
  } })
  try {
    assert.deepEqual(loadPeopleSort(), { key: 'lastName', direction: 'desc' })
    rememberPeopleSort({ key: 'photos', direction: 'asc' })
    assert.deepEqual(loadPeopleSort(), { key: 'photos', direction: 'asc' })
    assert.deepEqual(JSON.parse(storage.get('shoebox.people.sort')), { key: 'photos', direction: 'asc' })
  } finally {
    if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor)
    else delete globalThis.localStorage
  }
})
