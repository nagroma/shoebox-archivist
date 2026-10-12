import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, faceThumb, type BranchPlan, type Tree, type TreeNode } from '../api'
import { PersonPicker } from '../components/PersonPicker'
import { useAction, useApp } from '../state'

const NODE_W = 128
const NODE_H = 104
const GAP_X = 28
const GAP_Y = 64
const PAD = 24

interface Placed extends TreeNode { x: number; y: number }

/** Rows by generation; partners sit side by side; children are centred under their parents. */
function layout(tree: Tree): { nodes: Placed[]; width: number; height: number } {
  const byId = new Map(tree.nodes.map(n => [n.id, n]))
  const parentsOf = new Map<number, number[]>()
  const partnersOf = new Map<number, number[]>()
  for (const e of tree.edges) {
    const [m, k] = e.kind === 'parent' ? [parentsOf, e.b] : [partnersOf, e.b]
    m.set(k, [...(m.get(k) ?? []), e.a])
    if (e.kind === 'partner') partnersOf.set(e.a, [...(partnersOf.get(e.a) ?? []), e.b])
  }

  const gens = [...new Set(tree.nodes.map(n => n.gen))].sort((a, b) => a - b)
  const cx = new Map<number, number>()   // centre x of every placed node
  const rows: { x: number; n: TreeNode }[][] = []

  for (const g of gens) {
    const inRow = tree.nodes.filter(n => n.gen === g)
    // glue partners into units
    const seen = new Set<number>()
    const units: TreeNode[][] = []
    for (const n of [...inRow].sort((a, b) => a.name.localeCompare(b.name))) {
      if (seen.has(n.id)) continue
      const unit: TreeNode[] = []
      const stack = [n.id]
      while (stack.length) {
        const id = stack.pop()!
        if (seen.has(id) || !byId.has(id) || byId.get(id)!.gen !== g) continue
        seen.add(id)
        unit.push(byId.get(id)!)
        stack.push(...(partnersOf.get(id) ?? []))
      }
      units.push(unit)
    }
    // ideal x of a unit: mean of its members' parents (already placed in an earlier row)
    const ideal = (u: TreeNode[]) => {
      const xs = u.flatMap(m => (parentsOf.get(m.id) ?? []).map(p => cx.get(p))).filter((x): x is number => x !== undefined)
      return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null
    }
    const keyed = units.map((u, i) => ({ u, k: ideal(u), i }))
    keyed.sort((a, b) => (a.k ?? 1e9) - (b.k ?? 1e9) || a.i - b.i)
    const placed: { x: number; n: TreeNode }[] = []
    let cursor = 0
    for (const { u, k } of keyed) {
      const w = u.length * NODE_W + (u.length - 1) * GAP_X
      const left = Math.max(cursor, k === null ? cursor : k - w / 2)
      u.forEach((n, j) => {
        const x = left + j * (NODE_W + GAP_X) + NODE_W / 2
        placed.push({ x, n })
        cx.set(n.id, x)
      })
      cursor = left + w + GAP_X
    }
    rows.push(placed)
  }

  const minX = Math.min(...rows.flat().map(p => p.x - NODE_W / 2))
  const maxX = Math.max(...rows.flat().map(p => p.x + NODE_W / 2))
  const nodes: Placed[] = rows.flatMap((row, r) =>
    row.map(p => ({ ...p.n, x: p.x - NODE_W / 2 - minX + PAD, y: PAD + r * (NODE_H + GAP_Y) })))
  return { nodes, width: maxX - minX + PAD * 2, height: PAD * 2 + rows.length * NODE_H + (rows.length - 1) * GAP_Y }
}

/** Writes Family|<Branch> keywords to the photos so a family can be searched in Bridge too. */
function BranchCard() {
  const run = useAction()
  const [plan, setPlan] = useState<BranchPlan | null>(null)
  const load = () => api.branches().then(setPlan).catch(() => setPlan(null))
  useEffect(() => { load() }, [])
  if (!plan || (plan.photos === 0 && plan.remove === 0)) return null
  const names = Object.entries(plan.branches).sort((a, b) => b[1] - a[1])
  return (
    <section className="card">
      <h2>Branch keywords</h2>
      <p className="muted small">
        Each photo gets <code>{plan.category}|&lt;Branch&gt;</code> for every family branch of the people in it
        (descendants of someone with no recorded parents, named by surname), so you can search a family in Bridge.
        They are written to the photo files as added keywords and can be removed with <code>pm strip</code>.
      </p>
      <div className="kw-found">
        {names.map(([b, n]) => <span key={b} className="kw other">{b} <span className="muted small">{n}</span></span>)}
      </div>
      <p className="small">
        {plan.add > 0 || plan.remove > 0
          ? <>Will add <b>{plan.add}</b> keyword{plan.add === 1 ? '' : 's'}{plan.remove > 0 && <> and remove <b>{plan.remove}</b></>} across {plan.photos} photos.</>
          : <>All {plan.photos} photos are up to date.</>}
      </p>
      <button className="primary" disabled={plan.add === 0 && plan.remove === 0}
        onClick={async () => {
          if (!confirm(`Write branch keywords to ${plan.add} photo keyword slots in your photo files?`)) return
          const r = await run(() => api.applyBranches(), 'Branch keywords written')
          if (r) load()
        }}>Write branch keywords to photos</button>
    </section>
  )
}

export function TreePage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { people } = useApp()
  const [generations, setGenerations] = useState(2)
  const [tree, setTree] = useState<Tree | null>(null)
  const [error, setError] = useState('')

  // Which person: the URL, else the curator, else whoever has the most family links.
  const focus = useMemo(() => {
    if (id) return Number(id)
    return people.find(p => p.relation === 'You')?.id ?? people.find(p => p.relation)?.id ?? null
  }, [id, people])

  useEffect(() => {
    if (focus === null) { setTree(null); return }
    setError('')
    api.tree(focus, generations).then(setTree).catch(e => setError((e as Error).message))
  }, [focus, generations])

  const placed = useMemo(() => (tree ? layout(tree) : null), [tree])
  const pos = useMemo(() => new Map(placed?.nodes.map(n => [n.id, n])), [placed])
  const person = people.find(p => p.id === focus)

  return (
    <div className="page">
      <header className="page-head">
        <h1>Family tree{person && <span className="muted"> · {person.name}</span>}</h1>
        <div className="row">
          <PersonPicker buttonLabel="Show" placeholder="Show a person's family…" allowNew={false} clearOnPick
            onPick={who => { if ('person_id' in who) navigate(`/tree/${who.person_id}`) }} />
          <label className="small">Generations{' '}
            <select value={generations} onChange={e => setGenerations(Number(e.target.value))}>
              {[1, 2, 3, 4].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          {focus !== null && (
            <Link to={`/photos?family=${focus}&generations=${generations}`}><button>Photos of this family</button></Link>
          )}
        </div>
      </header>

      {error && <p className="hint error">{error}</p>}
      {focus === null && (
        <p className="empty">
          No family links yet. Open a person on the <Link to="/people">People</Link> page and add their
          parents, partners and children in the Family card. Set the curator on the{' '}
          <Link to="/library">Library</Link> page so the tree starts from you.
        </p>
      )}
      {tree && tree.nodes.length === 1 && (
        <p className="empty">
          {person?.name} has no family links yet. Add them on <Link to={`/people/${focus}`}>their page</Link>.
        </p>
      )}

      {placed && tree && tree.nodes.length > 1 && (
        <div className="tree-scroll">
          <div className="tree" style={{ width: placed.width, height: placed.height }}>
            <svg width={placed.width} height={placed.height}>
              {tree.edges.map((e, i) => {
                const a = pos.get(e.a), b = pos.get(e.b)
                if (!a || !b) return null
                if (e.kind === 'partner') {
                  const y = a.y + NODE_H / 2
                  const [l, r] = a.x < b.x ? [a, b] : [b, a]
                  return <line key={i} className="tree-partner" x1={l.x + NODE_W} y1={y} x2={r.x} y2={y} />
                }
                const x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H
                const x2 = b.x + NODE_W / 2, y2 = b.y
                const my = (y1 + y2) / 2
                return <path key={i} className="tree-parent" d={`M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`} />
              })}
            </svg>
            {placed.nodes.map(n => (
              <Link key={n.id} to={`/tree/${n.id}`} title="Centre the tree on this person"
                className={`tree-node${n.id === tree.focus ? ' focus' : ''}`}
                style={{ left: n.x, top: n.y, width: NODE_W, height: NODE_H }}>
                {n.cover ? <img src={faceThumb(n.cover)} alt="" /> : <div className="noface">?</div>}
                <div className="name">{n.name}</div>
                <div className="muted small">
                  {n.relation && n.relation !== 'You' ? n.relation : n.relation === 'You' ? 'You' : ''}
                  {(n.birth_year || n.death_year) && ` ${n.birth_year ?? '?'}–${n.death_year ?? ''}`}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
      <BranchCard />
      {tree && tree.nodes.length > 1 && (
        <p className="muted small">
          Click a person to centre the tree on them. Parents are above, children below, partners side by side;
          siblings are shown with the person's own parents. <Link to={`/people/${focus}`}>Open {person?.name}'s page</Link>
        </p>
      )}
    </div>
  )
}
