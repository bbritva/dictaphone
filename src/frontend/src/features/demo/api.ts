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
  after: { markdown: string }
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
    throw new Error(`Exemple « ${name} » introuvable (HTTP ${response.status}).`)
  }
  return new File([await response.blob()], name)
}
