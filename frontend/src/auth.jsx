import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken } from './api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [me, setMe] = useState(null)
  const [loading, setLoading] = useState(Boolean(getToken()))

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setMe(null)
      setLoading(false)
      return
    }
    try {
      setMe(await api('/auth/me'))
    } catch {
      setMe(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const onLogout = () => setMe(null)
    window.addEventListener('greentrace:logout', onLogout)
    return () => window.removeEventListener('greentrace:logout', onLogout)
  }, [refresh])

  const login = async (email, password) => {
    const { access_token } = await api('/auth/login', { method: 'POST', body: { email, password } })
    setToken(access_token)
    await refresh()
  }

  // Organization sign-up: the server emails a separate password to the admin, manager and auditor.
  const registerOrg = (payload) => api('/auth/register-org', { method: 'POST', body: payload })

  const logout = () => {
    setToken(null)
    setMe(null)
  }

  return (
    <AuthContext.Provider value={{ me, loading, login, registerOrg, logout, isAdmin: me?.user.role === 'admin', canEdit: me?.user.role === 'admin' }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
