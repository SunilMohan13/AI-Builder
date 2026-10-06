import { useEffect, useState, type FormEvent } from 'react'
import { Camera } from 'lucide-react'
import { ScientificBadge } from '../common/Badge'
import { submitCitizenReport, type CitizenSubmitInput } from '../../services/citizenService'
import { useDataMode } from '../../context/DataModeContext'
import type { CitizenReport } from '../../types'

const DELHI = { lat: 28.6139, lon: 77.209 }

export function CitizenUploadForm({
  onSubmitted,
}: {
  onSubmitted: (report: CitizenReport) => void
}) {
  const { mode } = useDataMode()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [observationType, setObservationType] = useState('photo')
  const [lat, setLat] = useState(DELHI.lat)
  const [lon, setLon] = useState(DELHI.lon)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<CitizenReport | null>(null)

  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview)
    }
  }, [preview])

  const onFile = (next: File | null) => {
    if (preview) URL.revokeObjectURL(preview)
    setFile(next)
    setPreview(next ? URL.createObjectURL(next) : null)
    setResult(null)
    setError(null)
  }

  const useLocation = () => {
    if (!navigator.geolocation) {
      setError('Geolocation is not available in this browser.')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(Number(pos.coords.latitude.toFixed(5)))
        setLon(Number(pos.coords.longitude.toFixed(5)))
        setError(null)
      },
      () => setError('Location permission denied. Delhi NCR coordinates are used instead.'),
    )
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!file) {
      setError('Choose a JPEG, PNG, or WebP photo.')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      setError('Photo must be 5 MB or smaller.')
      return
    }
    setBusy(true)
    setError(null)
    const payload: CitizenSubmitInput = { file, notes, observationType, lat, lon }
    try {
      const report = await submitCitizenReport(payload)
      setResult(report)
      onSubmitted(report)
      setFile(null)
      if (preview) URL.revokeObjectURL(preview)
      setPreview(null)
      setNotes('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={(e) => void onSubmit(e)}
      className="rounded-lg border border-cyan-500/20 bg-bg-panel/80 p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Camera className="h-4 w-4 text-cyan-300" />
          <h2 className="text-sm font-medium">Upload photo</h2>
        </div>
        <ScientificBadge label="OBSERVED" />
      </div>
      <p className="mt-1 text-[11px] text-text-muted">
        {mode === 'demo'
          ? 'Demo · processed in this browser with the same keyword heuristic as the API.'
          : 'Live · POST /api/v1/citizen/reports then POST …/media. No demo list is used.'}
      </p>

      <div className="mt-3 grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)]">
        <label className="flex h-36 cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-border bg-black/40 text-xs text-text-muted hover:border-intel/40">
          {preview ? (
            <img src={preview} alt="Selected photo" className="h-full w-full rounded-md object-cover" />
          ) : (
            <span>Choose photo</span>
          )}
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
        </label>

        <div className="space-y-2">
          <label className="block text-[11px] text-text-muted">
            Notes
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="e.g. heavy haze over Delhi"
              className="mt-1 w-full rounded-md border border-border bg-black/40 px-2 py-1.5 text-sm text-text-primary"
            />
          </label>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <label className="text-[11px] text-text-muted">
              Type
              <select
                value={observationType}
                onChange={(e) => setObservationType(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-black/40 px-2 py-1.5 text-sm text-text-primary"
              >
                <option value="photo">photo</option>
                <option value="smoke">smoke</option>
                <option value="fire">fire</option>
                <option value="dust">dust</option>
                <option value="haze">haze</option>
              </select>
            </label>
            <label className="text-[11px] text-text-muted">
              Lat
              <input
                type="number"
                step="0.0001"
                value={lat}
                onChange={(e) => setLat(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-border bg-black/40 px-2 py-1.5 font-mono text-sm"
              />
            </label>
            <label className="text-[11px] text-text-muted">
              Lon
              <input
                type="number"
                step="0.0001"
                value={lon}
                onChange={(e) => setLon(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-border bg-black/40 px-2 py-1.5 font-mono text-sm"
              />
            </label>
            <button
              type="button"
              onClick={useLocation}
              className="self-end rounded-md border border-border px-2 py-1.5 text-[11px] text-text-secondary hover:text-text-primary"
            >
              Use my location
            </button>
          </div>
        </div>
      </div>

      {error ? <p className="mt-2 text-xs text-amber-300">{error}</p> : null}
      {result ? (
        <p className="mt-2 text-xs text-emerald-300">
          Processed {result.id} · class {result.classification}
          {result.mediaUri ? ` · stored ${result.mediaUri}` : ''} · not a trained CV model
        </p>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="mt-3 rounded-md border border-intel/30 bg-intel/10 px-3 py-1.5 text-xs text-intel hover:bg-intel/20 disabled:opacity-50"
      >
        {busy ? 'Processing photo…' : 'Upload and process'}
      </button>
    </form>
  )
}
