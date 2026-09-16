/**
 * Transcript-quality panel on the recording page.
 *
 * `/demo` answers "what do the two correction stages do to a transcript?" with
 * a transcript written for the demo. This panel answers the harder version of
 * the same question: what do they do to *this* recording, the one transcribed
 * from real audio, whose transcript Dictaphone already holds.
 *
 * Collapsed by default, and closed is the whole point: a teammate opening a
 * recording sees the page they have always seen. Nothing here runs, fetches or
 * costs a model call until someone opens the panel and asks for a run.
 *
 * Read-only. The run recomputes a transcript in memory on the server and sends
 * it back; the stored transcript and its `AiFileJob` are never written to, so
 * re-running with a different glossary as many times as you like changes
 * nothing on the recording.
 */
import { useState } from 'react'
import { Button } from '@gouvfr-lasuite/cunningham-react'
import { DemoDropZone } from '@/features/demo/DemoDropZone'
import { DemoReportView } from '@/features/demo/DemoReport'
import {
  DemoReport,
  SAMPLES,
  loadSample,
  runJobDemo,
} from '@/features/demo/api'

export function RecordingQualityPanel({
  aiJobId,
  isTranscriptReady,
}: {
  aiJobId: string | null
  isTranscriptReady: boolean
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [glossary, setGlossary] = useState<File | null>(null)
  const [calendar, setCalendar] = useState<File | null>(null)
  const [report, setReport] = useState<DemoReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const canRun = isTranscriptReady && !!aiJobId

  const loadSamples = async () => {
    setError(null)
    try {
      const [sampleGlossary, sampleCalendar] = await Promise.all([
        loadSample(SAMPLES.glossary, 'glossary.txt'),
        loadSample(SAMPLES.calendar, 'attendees.ics'),
      ])
      setGlossary(sampleGlossary)
      setCalendar(sampleCalendar)
    } catch (exception) {
      setError((exception as Error).message)
    }
  }

  const run = async () => {
    if (!aiJobId) {
      return
    }
    setIsRunning(true)
    setError(null)
    setReport(null)
    try {
      setReport(await runJobDemo(aiJobId, { glossary, calendar }))
    } catch (exception) {
      setError((exception as Error).message)
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <section className="recording-quality">
      <button
        type="button"
        className="recording-quality__toggle"
        aria-expanded={isOpen}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className="recording-quality__toggle__chevron" aria-hidden="true">
          {isOpen ? '▾' : '▸'}
        </span>
        Qualité du transcript — glossaire et participants (démo)
      </button>

      {isOpen && (
        <div className="recording-quality__body">
          <p className="demo-muted">
            Rejoue les deux étapes de correction sur le transcript de cet
            enregistrement, avec le glossaire et les participants déposés
            ci-dessous. <strong>Rien n’est enregistré</strong> : le transcript
            stocké n’est pas modifié, le résultat n’existe que dans cette page.
          </p>

          {!canRun && (
            <p className="demo-empty">
              Le transcript de cet enregistrement n’est pas encore disponible :
              il n’y a rien à corriger pour l’instant.
            </p>
          )}

          <div className="demo-drops">
            <DemoDropZone
              title="Glossaire"
              hint="Texte brut : .txt, .csv, ou sans extension. Séparateurs = ; :"
              file={glossary}
              onFile={setGlossary}
              onClear={() => setGlossary(null)}
              disabled={isRunning || !canRun}
            />
            <DemoDropZone
              title="Participants"
              hint="Fichier .ics — les participants servent d’indices de nom."
              accept={{ 'text/calendar': ['.ics'] }}
              file={calendar}
              onFile={setCalendar}
              onClear={() => setCalendar(null)}
              disabled={isRunning || !canRun}
            />
          </div>

          <div className="demo-actions">
            <Button color="brand" onClick={run} disabled={!canRun || isRunning}>
              {isRunning ? 'Correction en cours…' : 'Relancer la correction'}
            </Button>
            <Button
              color="neutral"
              onClick={loadSamples}
              disabled={isRunning || !canRun}
            >
              Charger les fichiers d’exemple
            </Button>
            <span className="demo-actions__note">
              {glossary || calendar
                ? 'Les deux fichiers sont facultatifs : retirez-en un pour voir ce qu’il apportait.'
                : 'Sans fichier, la correction tourne avec le seul glossaire livré avec le service — c’est une exécution valable, pas un essai à vide.'}
            </span>
          </div>

          {isRunning && (
            <p className="demo-note">
              Les deux étapes relisent tout le transcript. Sur un enregistrement
              long, comptez une à deux minutes au premier passage.
            </p>
          )}

          {error && (
            <div className="demo-error" role="alert">
              {error}
            </div>
          )}

          {report && <DemoReportView report={report} />}
        </div>
      )}
    </section>
  )
}
