import { useEffect, useState, type FormEvent } from 'react'
import { Camera } from 'lucide-react'
import { ApiError } from '../../api/client'
import { submitCitizenReport } from '../../api/regions'
import type { CitizenCreated, CitizenUploaded, Region } from '../../api/regionTypes'
import { useDataMode } from '../../context/DataModeContext'
import { resolve } from '../../services/resolve'

const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp']
const MAX_BYTES = 5 * 1024 * 1024
const TYPES = ['photo', 'smoke', 'fire', 'haze', 'dust']

/**
 * Report a photo for the selected region. The point defaults to the region's
 * map centre from its pack; the API rejects a point outside the region. Key it
 * by region so switching region resets the point.
 */
export function CitizenUploadForm({
  region,
  onSubmitted,
}: {
  region: Region
  onSubmitted: (reportId: string) => void
}) {
  const { mode } = useDataMode()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [observationType, setObservationType] = useState('photo')
  const [lat, setLat] = useState(region.map_view.lat)
  const [lon, setLon] = useState(region.map_view.lon)
  const [accuracy, setAccuracy] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ created: CitizenCreated; uploaded: CitizenUploaded | null } | null>(null)

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview)
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
        setAccuracy(Math.round(pos.coords.accuracy))
        setError(null)
      },
      () => setError(`Location permission denied; the point stays at ${region.display_name}'s map centre.`),
    )
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!file) return setError('Choose a JPEG, PNG or WebP photo.')
    if (!ACCEPTED.includes(file.type)) return setError('Photo must be JPEG, PNG or WebP.')
    if (file.size > MAX_BYTES) return setError('Photo must be 5 MB or smaller.')
    setBusy(true)
    setError(null)
    try {
      const done = await resolve('citizen-upload', region.region_id, (t) =>
        submitCitizenReport(
          t,
          {
            lat,
            lon,
            regionId: region.region_id,
            observationType,
            notes,
            contentType: file.type,
            deviceAccuracyM: accuracy,
          },
          file,
        ),
      )
      setResult(done)
      onSubmitted(done.created.report.report_id)
      onFile(null)
      setNotes('')
    } catch (err) {
      setError(err instanceof ApiError ? err.reason : err instanceof Error ? err.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  const field = 'mt-1 w-full rounded-md border border-border bg-black/40 px-2 py-1.5 text-sm text-text-primary'

  return (
    <form onSubmit={(e) => void onSubmit(e)} className="rounded-lg border border-border bg-bg-panel/80 p-4">
      <div className="flex items-center gap-2">
        <Camera className="h-4 w-4 text-intel" />
        <h2 className="text-sm font-medium">Report a photo in {region.display_name}</h2>
      </div>
      <p className="mt-1 text-[11px] text-text-muted">
        {mode === 'demo'
          ? 'Demo replays recorded reads only; switch to Live to upload. The recorded report below went through the real pipeline.'
          : 'The API stores the photo, a vision model describes it (an AI observation), and deterministic checks corroborate it against stations, fires and wind.'}
      </p>

      <div className="mt-3 grid gap-3 lg:grid-cols-[160px_minmax(0,1fr)]">
        <label className="flex h-32 cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-border bg-black/40 text-xs text-text-muted hover:border-intel/40">
          {preview ? (
            <img src={preview} alt="Selected photo" className="h-full w-full rounded-md object-cover" />
          ) : (
            <span>Choose photo</span>
          )}
          <input
            type="file"
            accept={ACCEPTED.join(',')}
            className="sr-only"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <div className="space-y-2">
          <label className="block text-[11px] text-text-muted">
            Notes
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} maxLength={1000} className={field} />
          </label>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <label className="text-[11px] text-text-muted">
              Type
              <select value={observationType} onChange={(e) => setObservationType(e.target.value)} className={field}>
                {TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[11px] text-text-muted">
              Lat
              <input type="number" step="0.0001" value={lat} onChange={(e) => setLat(Number(e.target.value))} className={`${field} font-mono`} />
            </label>
            <label className="text-[11px] text-text-muted">
              Lon
              <input type="number" step="0.0001" value={lon} onChange={(e) => setLon(Number(e.target.value))} className={`${field} font-mono`} />
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

      {error && <p className="mt-2 text-xs text-amber-300">{error}</p>}
      {result && (
        <p className="mt-2 text-xs text-emerald-300">
          Report {result.created.report.report_id} created
          {result.uploaded ? ` · photo ${result.uploaded.status} · analysis ${result.uploaded.analysis}` : ' · photo sent to storage'}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || mode === 'demo'}
        className="mt-3 rounded-md border border-intel/30 bg-intel/10 px-3 py-1.5 text-xs text-intel hover:bg-intel/20 disabled:opacity-50"
      >
        {busy ? 'Uploading…' : 'Submit report'}
      </button>
    </form>
  )
}
