import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { ClustersPage } from './pages/Clusters'
import { PeoplePage, PersonPage } from './pages/People'
import { PhotoDetailPage } from './pages/PhotoDetail'
import { PhotosPage } from './pages/Photos'
import { SettingsPage } from './pages/Settings'
import { AppProvider, useApp } from './state'
import { AddPhotosButton } from './components/AddPhotos'

function Nav() {
  const { stats } = useApp()
  const unnamed = (stats?.faces.unknown ?? 0) + (stats?.faces.suggested ?? 0)
  return (
    <nav className="nav">
      <span className="brand">Shoebox Archivist</span>
      <NavLink to="/photos">Photos {stats && <span className="count muted-count">{stats.photos}</span>}</NavLink>
      <NavLink to="/people">People {stats && <span className="count muted-count">{stats.people}</span>}</NavLink>
      <NavLink to="/faces">Faces {unnamed > 0 && <span className="count">{unnamed}</span>}</NavLink>
      <span className="grow" />
      {stats && <span className="muted small" title={stats.library_root ?? ''}>
        {stats.faces.confirmed ?? 0} named · {stats.undated} undated
      </span>}
      <AddPhotosButton />
      <NavLink to="/settings" title="Settings">⚙ Settings</NavLink>
    </nav>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <Nav />
        <main>
          <Routes>
            <Route path="/" element={<Navigate to="/photos" replace />} />
            <Route path="/faces" element={<ClustersPage />} />
            <Route path="/people" element={<PeoplePage />} />
            <Route path="/people/:id" element={<PersonPage />} />
            <Route path="/photos" element={<PhotosPage />} />
            <Route path="/photos/:id" element={<PhotoDetailPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </AppProvider>
    </BrowserRouter>
  )
}
