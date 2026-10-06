import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { FooterStatus } from './FooterStatus'
import { CommandPalette } from './CommandPalette'
import { NotificationDrawer } from './NotificationDrawer'
import { DemoOverlay } from './DemoOverlay'
import { JudgeTourDriver } from './JudgeTourDriver'

export function AppShell() {
  return (
    <div className="flex h-full flex-col overflow-x-hidden">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="relative flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 flex-col overflow-auto">
            <Outlet />
          </div>
          <DemoOverlay />
          <JudgeTourDriver />
        </main>
      </div>
      <FooterStatus />
      <CommandPalette />
      <NotificationDrawer />
    </div>
  )
}
