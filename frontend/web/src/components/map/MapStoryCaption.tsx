export function MapStoryCaption({ caption }: { caption: string | null }) {
  if (!caption) return null
  return (
    <div className="pointer-events-none absolute inset-x-0 top-[7.5rem] z-[26] flex justify-center px-4">
      <p
        className="max-w-2xl rounded-full border border-cyan-500/30 bg-black/75 px-4 py-1.5 text-center font-mono text-[11px] text-cyan-100/95 backdrop-blur"
      >
        {caption}
      </p>
    </div>
  )
}
