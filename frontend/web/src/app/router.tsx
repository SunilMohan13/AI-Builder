import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AppProvider } from '../context/AppContext'
import { DataModeProvider } from '../context/DataModeContext'
import { ViewLevelProvider } from '../context/ViewLevelContext'
import { AppShell } from '../components/layout/AppShell'
import { Overview } from '../pages/Overview'
import { LiveMap } from '../pages/LiveMap'
import { EventDetail, EventsIndex } from '../pages/EventDetail'
import { Forecast } from '../pages/Forecast'
import { Risk } from '../pages/Risk'
import { Evidence } from '../pages/Evidence'
import { Sources } from '../pages/Sources'
import { Copilot } from '../pages/Copilot'
import { CitizenReports } from '../pages/CitizenReports'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
    },
  },
})

export function AppRouter() {
  return (
    <QueryClientProvider client={queryClient}>
      <DataModeProvider>
        <ViewLevelProvider>
          <AppProvider>
            <BrowserRouter>
              <Routes>
                <Route element={<AppShell />}>
                  <Route index element={<Overview />} />
                  <Route path="map" element={<LiveMap />} />
                  <Route path="events" element={<EventsIndex />} />
                  <Route path="events/:eventId" element={<EventDetail />} />
                  <Route path="forecast" element={<Forecast />} />
                  <Route path="risk" element={<Risk />} />
                  <Route path="evidence" element={<Evidence />} />
                  <Route path="sources" element={<Sources />} />
                  <Route path="copilot" element={<Copilot />} />
                  <Route path="citizen" element={<CitizenReports />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Routes>
            </BrowserRouter>
          </AppProvider>
        </ViewLevelProvider>
      </DataModeProvider>
    </QueryClientProvider>
  )
}
