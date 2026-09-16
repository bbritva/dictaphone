/**
 * One drop zone of the demo page.
 *
 * Drag-and-drop and click open the same picker and land in the same handler,
 * so neither path can work while the other is broken. `useDropzone` gives both
 * from one hook: `getRootProps` carries the drag events and the click, and
 * `getInputProps` renders the `<input type="file">` behind it.
 */
import { useDropzone } from 'react-dropzone'
import prettyBytes from 'pretty-bytes'

export function DemoDropZone({
  title,
  hint,
  accept,
  file,
  onFile,
  onClear,
  disabled,
  children,
}: {
  title: string
  hint: string
  accept?: Record<string, string[]>
  file: File | null
  onFile: (file: File) => void
  onClear: () => void
  disabled?: boolean
  children?: React.ReactNode
}) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept,
    multiple: false,
    disabled,
    // The browser File System Access API opens a picker that filters on
    // `accept` and silently refuses everything else; the demo has to accept a
    // glossary with no extension at all, so the classic input is used instead.
    useFsAccessApi: false,
    onDrop: (accepted) => {
      if (accepted.length > 0) {
        onFile(accepted[0])
      }
    },
  })

  return (
    <div className="demo-drop">
      <div className="demo-drop__title">{title}</div>
      <div
        {...getRootProps({
          className: `demo-drop__zone${isDragActive ? ' demo-drop__zone--active' : ''}${
            file ? ' demo-drop__zone--filled' : ''
          }`,
        })}
      >
        <input {...getInputProps()} data-testid={`demo-input-${title}`} />
        {file ? (
          <>
            <span className="demo-drop__filename">{file.name}</span>
            <span className="demo-drop__meta">{prettyBytes(file.size)}</span>
          </>
        ) : (
          <>
            <span className="demo-drop__filename">
              Déposez le fichier ici
            </span>
            <span className="demo-drop__meta">ou cliquez pour le choisir</span>
          </>
        )}
      </div>
      <div className="demo-drop__hint">{hint}</div>
      {file && (
        <button
          type="button"
          className="demo-drop__clear"
          onClick={onClear}
          disabled={disabled}
        >
          Retirer
        </button>
      )}
      {children}
    </div>
  )
}
