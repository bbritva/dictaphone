/**
 * Demo-only client for the transcript-quality demo page.
 *
 * Self-contained on purpose: `fetchApi` always sets a JSON content type, which
 * is exactly wrong for a multipart upload (the browser has to pick the boundary
 * itself). Rather than changing a helper every other page depends on, this
 * module does its own fetch, and nothing outside `/demo` imports it.
 */
import { apiUrl } from '@/api/apiUrl'

export interface DemoCorrection {
  wrong: string
  correct: string
  confidence: number
  applied: boolean
  from_user_glossary: boolean
  segment_index: number
  word_index: number
  sentence: string
}

export interface DemoSpeaker {
  name: string
  label: string
  score: number
  kind: string
  quote: string
  segment_index: number
}

export interface DemoReport {
  run_id: string
  transcript: {
    filename: string
    segments: number
    words: number
    language: string | null
  }
  glossary: {
    filename: string | null
    entries: { acronym: string; expansion: string }[]
    count: number
    skipped: string[]
  }
  attendees: {
    filename: string | null
    list: { name: string; email: string }[]
    count: number
  }
  before: { markdown: string }
  // `transcript` is the corrected WhisperX response itself, not its rendering.
  // Only the import flow reads it -- it is what gets stored as the new
  // recording's transcript -- so it stays optional and the pages that only
  // show markdown are unaffected.
  after: { markdown: string; transcript?: unknown }
  corrections: DemoCorrection[]
  speakers: DemoSpeaker[]
  flagged_spans: string[]
  stats: { hits: number; misses: number }
  warnings: string[]
  min_confidence: number
  model: string
}

export interface DemoPublished {
  id: string
  url: string
}

const csrfToken = () =>
  document.cookie
    .split(';')
    .filter((cookie) => cookie.trim().startsWith('csrftoken='))
    .map((cookie) => cookie.split('=')[1])
    .pop()

/**
 * Read the JSON body whatever the status, so the page can show the message the
 * pipeline produced instead of a generic failure.
 */
const readJson = async (response: Response) => {
  const body = await response.text()
  try {
    return JSON.parse(body) as Record<string, unknown>
  } catch {
    return { error: body.slice(0, 300) || `HTTP ${response.status}` }
  }
}

const post = async <T>(path: string, options: RequestInit): Promise<T> => {
  const token = csrfToken()
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    credentials: 'include',
    ...options,
    headers: {
      ...(!!token && { 'X-CSRFToken': token }),
      ...options.headers,
    },
  })
  const payload = await readJson(response)
  if (!response.ok) {
    throw new Error(
      typeof payload.error === 'string'
        ? payload.error
        : `Le serveur a répondu en HTTP ${response.status}.`
    )
  }
  return payload as T
}

export const runDemo = (files: {
  transcript: File
  glossary: File | null
  calendar: File | null
}) => {
  const form = new FormData()
  form.append('transcript', files.transcript)
  if (files.glossary) {
    form.append('glossary', files.glossary)
  }
  if (files.calendar) {
    form.append('calendar', files.calendar)
  }
  return post<DemoReport>('demo/transcript-quality/run/', { body: form })
}

/**
 * Same run, over a transcript Dictaphone already stores.
 *
 * The transcript is not sent: the server reads it from the AI job. Both side
 * files are optional -- a run with neither is a real run, showing what the
 * service's own shipped glossary does alone.
 */
export const runJobDemo = (
  aiJobId: string,
  files: { glossary: File | null; calendar: File | null }
) => {
  const form = new FormData()
  if (files.glossary) {
    form.append('glossary', files.glossary)
  }
  if (files.calendar) {
    form.append('calendar', files.calendar)
  }
  return post<DemoReport>(`demo/transcript-quality/ai-jobs/${aiJobId}/run/`, {
    body: form,
  })
}

/**
 * One document the import tried to push to Docs.
 *
 * `url` and `error` are exclusive: a stage that produced nothing carries the
 * reason instead of a link, so the modal never shows an empty success.
 */
export interface DemoDocument {
  kind: 'raw' | 'corrected' | 'summary'
  title: string
  url: string | null
  docs_app_id: string | null
  error: string | null
}

/** The report, plus the recording the import created from it. */
export interface DemoImported extends DemoReport {
  file: {
    id: string
    title: string
    duration_seconds: number
    ai_job_id: string
  }
  // The two transcript documents. The compte-rendu is not here: it is a second
  // call, because it is another minutes-long model round trip and the two
  // links must not wait for it.
  documents: DemoDocument[]
  // The Docs document the two above were filed under. Not one of `documents`:
  // it carries no result, so the modal has no row for it. It is here to be
  // handed straight back on the summarize call, which is the only way that
  // later request can put the compte-rendu in the same tree. `null` when the
  // parent could not be created and the two documents went to the root.
  parent_document_id: string | null
}

/**
 * Correct a transcript and keep the result as a recording.
 *
 * Same three files as `runDemo`, same single call to the pipeline. The
 * difference is on the server: the corrected transcript is stored as a real
 * `File` + `AiFileJob`, so the answer carries the id of a recording that now
 * exists in the list, and the report of the run that produced it.
 */
export const importTranscript = (input: {
  transcript: File
  glossary: File | null
  calendar: File | null
  title: string
}) => {
  const form = new FormData()
  form.append('transcript', input.transcript)
  if (input.glossary) {
    form.append('glossary', input.glossary)
  }
  if (input.calendar) {
    form.append('calendar', input.calendar)
  }
  if (input.title.trim()) {
    form.append('title', input.title.trim())
  }
  return post<DemoImported>('demo/transcript-quality/import/', { body: form })
}

/**
 * Summarise an imported recording and publish the compte-rendu to Docs.
 *
 * Deliberately after `importTranscript` rather than inside it: the two
 * transcript documents exist as soon as the correction is done and are shown
 * then, while this one runs behind a pending row. Called with the transcript
 * job's id, the one `importTranscript` hands back, and with the parent document
 * of that same import so the compte-rendu joins the other two in Docs' tree
 * instead of becoming a third root.
 */
export const summarizeImported = (
  aiJobId: string,
  parentDocumentId: string | null
) =>
  post<{ document: DemoDocument }>(
    `demo/transcript-quality/ai-jobs/${aiJobId}/summarize/`,
    {
      // Omitted, not sent as null, when there is no parent: the server treats a
      // missing field as "publish at the root", which is what every client did
      // before parents existed. Inventing an id here would be worse than not
      // sending one.
      body: JSON.stringify(
        parentDocumentId ? { parent_document_id: parentDocumentId } : {}
      ),
      headers: { 'Content-Type': 'application/json' },
    }
  )

export const publishDemo = (runId: string, which: 'before' | 'after') =>
  post<DemoPublished>('demo/transcript-quality/publish/', {
    body: JSON.stringify({
      run_id: runId,
      which,
      title:
        which === 'after'
          ? 'Démo — transcript corrigé (données fictives)'
          : 'Démo — transcript brut (données fictives)',
    }),
    headers: { 'Content-Type': 'application/json' },
  })

/** The bundled sample files, copied into `public/demo/` to seed the page. */
export const SAMPLES = {
  transcript: '/demo/transcript-whisperx.json',
  glossary: '/demo/glossary.txt',
  calendar: '/demo/attendees.ics',
} as const

export const loadSample = async (url: string, name: string): Promise<File> => {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(
      `Exemple « ${name} » introuvable (HTTP ${response.status}).`
    )
  }
  return new File([await response.blob()], name)
}
