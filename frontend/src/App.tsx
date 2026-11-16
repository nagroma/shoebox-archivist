import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api, type LibraryInfo } from './api'
import { KeywordReviewPage } from './pages/KeywordReview'
import { LibraryPage } from './pages/Library'
import { KeywordsPage } from './pages/Keywords'
import { ClustersPage } from './pages/Clusters'
import { TreePage } from './pages/Tree'
import { PeoplePage, PersonPage } from './pages/People'
import { PhotoDetailPage } from './pages/PhotoDetail'
import { PhotosPage } from './pages/Photos'
import { SettingsPage } from './pages/Settings'
import { AppProvider, useApp } from './state'
import { AddPhotosButton } from './components/AddPhotos'

function Nav({ scoped }: { scoped: boolean }) {
  const { stats } = useApp()
  const unnamed = (stats?.faces.unknown ?? 0) + (stats?.faces.suggested ?? 0)
  return (
    <nav className="nav">
      <span className="brand">Shoebox Archivist</span>
      <NavLink to="/photos">Photos {stats && <span className="count muted-count">{stats.photos}</span>}</NavLink>
      <NavLink to="/people">People {stats && <span className="count muted-count">{stats.people}</span>}</NavLink>
      <NavLink to="/tree">Tree</NavLink>
      <NavLink to="/faces">Faces {unnamed > 0 && <span className="count">{unnamed}</span>}</NavLink>
      <span className="grow" />
      {stats && <span className="muted small" title={stats.library_root ?? ''}>
        {stats.faces.confirmed ?? 0} named · {stats.undated} undated
      </span>}
      <AddPhotosButton scoped={scoped} />
      <NavLink to="/library">Library</NavLink>
      <NavLink to="/keywords">Keywords{(stats?.keyword_differences ?? 0) > 0 && <span className="count">{stats?.keyword_differences}</span>}</NavLink>
      <NavLink to="/settings" title="Settings">⚙ Settings</NavLink>
    </nav>
  )
}

export default function App() {
  const [info, setInfo] = useState<LibraryInfo | null>(null)
  const load = useCallback(() => { api.library().then(setInfo) }, [])
  useEffect(load, [load])

  if (!info) return <p className="muted pad">Loading…</p>
  if (!info.open) {  // nothing to show until a library is created or opened
    return (
      <>
        <nav className="nav"><span className="brand">Shoebox Archivist</span></nav>
        <main><LibraryPage info={info} reload={load} /></main>
      </>
    )
  }
  return (
    <BrowserRouter>
      <AppProvider>
        <Nav scoped={info.folder_scoped ?? false} />
        <main>
          <Routes>
            <Route path="/" element={<Navigate to="/photos" replace />} />
            <Route path="/faces" element={<ClustersPage />} />
            <Route path="/people" element={<PeoplePage />} />
            <Route path="/people/:id" element={<PersonPage />} />
            <Route path="/tree" element={<TreePage />} />
            <Route path="/tree/:id" element={<TreePage />} />
            <Route path="/photos" element={<PhotosPage />} />
            <Route path="/photos/:id" element={<PhotoDetailPage />} />
            <Route path="/library" element={<LibraryPage info={info} reload={load} />} />
            <Route path="/keywords" element={<KeywordsPage info={info} reload={load} />} />
            <Route path="/keywords/review" element={<KeywordReviewPage />} />
            <Route path="/keyword-review" element={<Navigate to="/keywords/review" replace />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </AppProvider>
    </BrowserRouter>
  )
}
