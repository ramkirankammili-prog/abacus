import { Navigate, Route, Routes } from 'react-router-dom'
import Home from './pages/Home'
import DriverHome from './pages/DriverHome'
import SignIn from './pages/SignIn'
import SignUp from './pages/SignUp'
import { ProtectedRoute, PublicOnlyRoute } from './components/RouteGuards'
import { useAuth } from './context/AuthContext'

function WorkspaceHome() {
  const { role } = useAuth()
  return role === 'driver' ? <DriverHome /> : <Home />
}

export default function App() {
  return (
    <Routes>
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<WorkspaceHome />} />
      </Route>
      <Route element={<PublicOnlyRoute />}>
        <Route path="/signin" element={<SignIn />} />
        <Route path="/signup" element={<SignUp />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
