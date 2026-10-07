import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppProvider } from '../context/AppContext'
import { DataModeProvider } from '../context/DataModeContext'
import { RegionProvider } from '../context/RegionContext'
import { AppShell } from '../components/layout/AppShell'
import { CommandCentre } from '../pages/CommandCentre'
import { Events } from '../pages/Events'
import { Forecast } from '../pages/Forecast'
import { Evidence } from '../pages/Evidence'
import { Sources } from '../pages/Sources'
import { Copilot } from '../pages/Copilot'
import { CitizenReports } from '../pages/CitizenReports'
import { Models } from '../pages/Models'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
    },
  },
})

/** Old paths keep working and keep their `?region=`. */
function Redirect({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={`${to}${search}`} replace />
}

export function AppRouter() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <DataModeProvider>
          <RegionProvider>
            <AppProvider>
              <Routes>
                <Route element={<AppShell />}>
                  <Route index element={<CommandCentre />} />
                  <Route path="map" element={<Redirect to="/" />} />
                  <Route path="risk" element={<Redirect to="/forecast" />} />
                  <Route path="events" element={<Events />} />
                  <Route path="events/:eventId" element={<Events />} />
                  <Route path="forecast" element={<Forecast />} />
                  <Route path="evidence" element={<Evidence />} />
                  <Route path="sources" element={<Sources />} />
                  <Route path="copilot" element={<Copilot />} />
                  <Route path="citizen" element={<CitizenReports />} />
                  <Route path="models" element={<Models />} />
                  <Route path="ml" element={<Redirect to="/models" />} />
                  <Route path="*" element={<Redirect to="/" />} />
                </Route>
              </Routes>
            </AppProvider>
          </RegionProvider>
        </DataModeProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
