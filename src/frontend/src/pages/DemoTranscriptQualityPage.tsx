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
import { marked } from 'marked'
import { Button } from '@gouvfr-lasuite/cunningham-react'
import { BaseLayout } from '@/layout/BaseLayout'
import { DemoDropZone } from '@/features/demo/DemoDropZone'
import {
  DemoPublished,
  DemoReport,
  SAMPLES,
  loadSample,
  publishDemo,
  runDemo,
} from '@/features/demo/api'

const renderMarkdown = (markdown: string) =>
  marked.parse(markdown, { async: false })

function Measure({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="demo-measure">
      <span className="demo-measure__value">{value}</span>
      <span className="demo-measure__label">{label}</span>
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="demo-empty">{children}</p>
}

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

  const applied = report?.corrections.filter((row) => row.applied).length ?? 0

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
          <section className="demo-measures">
            <Measure label="segments" value={report.transcript.segments} />
            <Measure label="mots" value={report.transcript.words} />
            <Measure
              label="entrées de glossaire"
              value={report.glossary.count}
            />
            <Measure label="participants" value={report.attendees.count} />
            <Measure
              label="corrections appliquées"
              value={`${applied} / ${report.corrections.length}`}
            />
            <Measure
              label="locuteurs nommés"
              value={report.speakers.length}
            />
            <Measure
              label="cache modèle (hits / miss)"
              value={`${report.stats.hits} / ${report.stats.misses}`}
            />
          </section>

          <p className="demo-note">
            Modèle : <code>{report.model}</code> — seuil de confiance
            d’application : <code>{report.min_confidence}</code>. Un
            « miss » de cache signifie que le modèle a réellement été appelé
            pour cette exécution.
          </p>

          {report.warnings.length > 0 && (
            <section className="demo-warnings">
              <h3>Avertissements pendant l’exécution</h3>
              <ul>
                {report.warnings.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </section>
          )}

          <section className="demo-inputs-read">
            <div>
              <h3>Glossaire lu — {report.glossary.count} entrée(s)</h3>
              {report.glossary.count === 0 ? (
                <Empty>
                  Aucune entrée lue. Aucun glossaire n’a donc été transmis à
                  l’étape de correction : le résultat ci-dessous est celui du
                  glossaire livré avec le service, seul.
                </Empty>
              ) : (
                <ul className="demo-list">
                  {report.glossary.entries.map((entry) => (
                    <li key={entry.acronym}>
                      <code>{entry.acronym}</code> — {entry.expansion}
                    </li>
                  ))}
                </ul>
              )}
              {report.glossary.skipped.length > 0 && (
                <>
                  <h4>Lignes ignorées</h4>
                  <ul className="demo-list demo-list--muted">
                    {report.glossary.skipped.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
            <div>
              <h3>Participants lus — {report.attendees.count}</h3>
              {report.attendees.count === 0 ? (
                <Empty>
                  Aucun participant lu dans l’agenda. L’étape de résolution des
                  locuteurs n’a donc pas pu s’exécuter : les étiquettes
                  <code> SPEAKER_XX</code> restent telles quelles.
                </Empty>
              ) : (
                <ul className="demo-list">
                  {report.attendees.list.map((attendee) => (
                    <li key={attendee.email || attendee.name}>
                      {attendee.name}{' '}
                      <span className="demo-muted">{attendee.email}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section className="demo-compare">
            <div className="demo-compare__side">
              <h3>Avant — aucune fonctionnalité</h3>
              <p className="demo-muted">
                Ce que le service produit aujourd’hui pour Dictaphone : les deux
                étapes sont désactivées.
              </p>
              <div
                className="demo-markdown"
                dangerouslySetInnerHTML={{
                  __html: renderMarkdown(report.before.markdown),
                }}
              />
            </div>
            <div className="demo-compare__side">
              <h3>Après — locuteurs + acronymes</h3>
              <p className="demo-muted">
                Les deux étapes activées, avec le glossaire déposé et les
                participants de l’agenda.
              </p>
              <div
                className="demo-markdown"
                dangerouslySetInnerHTML={{
                  __html: renderMarkdown(report.after.markdown),
                }}
              />
            </div>
          </section>

          <section className="demo-evidence">
            <h3>Corrections d’acronymes</h3>
            {report.corrections.length === 0 ? (
              <Empty>
                Aucune correction produite.{' '}
                {report.flagged_spans.length === 0
                  ? 'L’étape 1 n’a signalé aucun passage suspect : il n’y avait donc rien à corriger, avec ou sans glossaire.'
                  : `L’étape 1 a signalé ${report.flagged_spans.length} passage(s) suspect(s), mais le modèle n’a retenu aucun acronyme.`}
              </Empty>
            ) : (
              <table className="demo-table">
                <thead>
                  <tr>
                    <th>Ce que Whisper a écrit</th>
                    <th>Acronyme retenu</th>
                    <th>Confiance</th>
                    <th>Appliquée</th>
                    <th>Source</th>
                    <th>Segment</th>
                  </tr>
                </thead>
                <tbody>
                  {report.corrections.map((row) => (
                    <tr
                      key={`${row.segment_index}-${row.word_index}-${row.correct}`}
                      className={row.applied ? '' : 'demo-table__row--blocked'}
                    >
                      <td>« {row.wrong} »</td>
                      <td>
                        <strong>{row.correct}</strong>
                      </td>
                      <td>{row.confidence.toFixed(2)}</td>
                      <td>
                        {row.applied
                          ? 'oui'
                          : `non — sous le seuil ${report.min_confidence}`}
                      </td>
                      <td>
                        {row.from_user_glossary
                          ? 'glossaire déposé'
                          : 'glossaire du service'}
                      </td>
                      <td title={row.sentence}>
                        #{row.segment_index}, mot {row.word_index}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {report.flagged_spans.length > 0 && (
              <p className="demo-note">
                Passages signalés à l’étape 1 :{' '}
                {report.flagged_spans.map((span) => (
                  <code key={span}>{span}</code>
                ))}
              </p>
            )}

            <h3>Locuteurs identifiés</h3>
            {report.speakers.length === 0 ? (
              <Empty>
                Aucun locuteur nommé. Soit aucun participant n’a été lu dans
                l’agenda, soit aucun indice de nom n’a été trouvé dans le
                transcript : les étiquettes <code>SPEAKER_XX</code> sont
                conservées.
              </Empty>
            ) : (
              <table className="demo-table">
                <thead>
                  <tr>
                    <th>Nom</th>
                    <th>Étiquette</th>
                    <th>Indice</th>
                    <th>Confiance</th>
                    <th>Citation</th>
                    <th>Segment</th>
                  </tr>
                </thead>
                <tbody>
                  {report.speakers.map((row) => (
                    <tr key={row.name}>
                      <td>
                        <strong>{row.name}</strong>
                      </td>
                      <td>
                        <code>{row.label}</code>
                      </td>
                      <td>{row.kind}</td>
                      <td>{row.score.toFixed(2)}</td>
                      <td className="demo-quote">« {row.quote} »</td>
                      <td>#{row.segment_index}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

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
