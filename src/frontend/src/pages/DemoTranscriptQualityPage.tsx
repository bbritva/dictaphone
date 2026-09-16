/**
 * Demo page: drop a transcript, a glossary and a calendar, see what the two
 * transcript-quality stages do to the transcript.
 *
 * This page deliberately bypasses transcription. Dictaphone's normal path is
 * audio -> transcript -> correction; here the transcript is dropped in
 * directly, so the demo shows the correction stages and nothing else. The
 * bypass lives entirely behind `/api/v1.0/demo/transcript-quality/`, which
 * creates no File and no AiFileJob.
 *
 * Everything the page shows is measured on the run that just happened. Nothing
 * is precomputed, and a stage that produced nothing says so.
 */
import { useState } from 'react'
import { Button } from '@gouvfr-lasuite/cunningham-react'
import { BaseLayout } from '@/layout/BaseLayout'
import { DemoDropZone } from '@/features/demo/DemoDropZone'
import { DemoReportView } from '@/features/demo/DemoReport'
import {
  DemoPublished,
  DemoReport,
  SAMPLES,
  loadSample,
  publishDemo,
  runDemo,
} from '@/features/demo/api'

export default function DemoTranscriptQualityPage() {
  const [transcript, setTranscript] = useState<File | null>(null)
  const [glossary, setGlossary] = useState<File | null>(null)
  const [calendar, setCalendar] = useState<File | null>(null)

  const [report, setReport] = useState<DemoReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const [published, setPublished] = useState<DemoPublished | null>(null)
  const [publishError, setPublishError] = useState<string | null>(null)
  const [isPublishing, setIsPublishing] = useState(false)

  const loadSamples = async () => {
    setError(null)
    try {
      const [sampleTranscript, sampleGlossary, sampleCalendar] =
        await Promise.all([
          loadSample(SAMPLES.transcript, 'transcript-whisperx.json'),
          loadSample(SAMPLES.glossary, 'glossary.txt'),
          loadSample(SAMPLES.calendar, 'attendees.ics'),
        ])
      setTranscript(sampleTranscript)
      setGlossary(sampleGlossary)
      setCalendar(sampleCalendar)
    } catch (exception) {
      setError((exception as Error).message)
    }
  }

  const run = async () => {
    if (!transcript) {
      return
    }
    setIsRunning(true)
    setError(null)
    setReport(null)
    setPublished(null)
    setPublishError(null)
    try {
      setReport(await runDemo({ transcript, glossary, calendar }))
    } catch (exception) {
      setError((exception as Error).message)
    } finally {
      setIsRunning(false)
    }
  }

  const publish = async () => {
    if (!report) {
      return
    }
    setIsPublishing(true)
    setPublishError(null)
    try {
      setPublished(await publishDemo(report.run_id, 'after'))
    } catch (exception) {
      setPublishError((exception as Error).message)
    } finally {
      setIsPublishing(false)
    }
  }

  return (
    <BaseLayout
      showShowcaseAssistant={false}
      className="demo-page"
      pageTitle="Démo — qualité du transcript"
      heading="Démo — qualité du transcript"
    >
      <section className="demo-warning">
        <strong>Données fictives.</strong> Le transcript et le fichier
        d’agenda fournis en exemple sont des maquettes écrites pour cette
        démonstration : aucune réunion réelle n’est passée dans ce flux. La
        page saute volontairement l’étape de transcription — le transcript est
        déposé tel quel — pour ne montrer que les deux étapes de correction.
        Les chiffres affichés plus bas sont mesurés sur l’exécution qui vient
        d’avoir lieu.
      </section>

      <section className="demo-drops">
        <DemoDropZone
          title="Transcript brut"
          hint="JSON WhisperX (segments + words)."
          accept={{ 'application/json': ['.json'] }}
          file={transcript}
          onFile={setTranscript}
          onClear={() => setTranscript(null)}
          disabled={isRunning}
        />
        <DemoDropZone
          title="Glossaire"
          hint="Texte brut : .txt, .csv, ou sans extension. Séparateurs = ; :"
          file={glossary}
          onFile={setGlossary}
          onClear={() => setGlossary(null)}
          disabled={isRunning}
        />
        <DemoDropZone
          title="Agenda"
          hint="Fichier .ics — les participants servent d’indices de nom."
          accept={{ 'text/calendar': ['.ics'] }}
          file={calendar}
          onFile={setCalendar}
          onClear={() => setCalendar(null)}
          disabled={isRunning}
        />
      </section>

      <section className="demo-actions">
        <Button color="brand" onClick={run} disabled={!transcript || isRunning}>
          {isRunning ? 'Correction en cours…' : 'Lancer la correction'}
        </Button>
        <Button color="neutral" onClick={loadSamples} disabled={isRunning}>
          Charger les fichiers d’exemple
        </Button>
        {!transcript && (
          <span className="demo-actions__note">
            Le transcript est obligatoire ; le glossaire et l’agenda sont
            facultatifs, pour voir ce que chacun apporte.
          </span>
        )}
      </section>

      {error && (
        <section className="demo-error" role="alert">
          {error}
        </section>
      )}

      {report && (
        <>
          <DemoReportView report={report} />

          <section className="demo-actions">
            <Button
              color="neutral"
              onClick={publish}
              disabled={isPublishing}
            >
              {isPublishing
                ? 'Publication en cours…'
                : 'Publier dans Docs (transcript corrigé)'}
            </Button>
            <span className="demo-actions__note">
              Rien n’est publié automatiquement : un document n’est créé que
              lorsque ce bouton est utilisé.
            </span>
          </section>

          {publishError && (
            <section className="demo-error" role="alert">
              {publishError}
            </section>
          )}
          {published && (
            <section className="demo-published">
              Document créé :{' '}
              <a href={published.url} target="_blank" rel="noreferrer">
                {published.url}
              </a>
            </section>
          )}
        </>
      )}
    </BaseLayout>
  )
}
