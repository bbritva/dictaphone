/**
 * Everything the transcript-quality report renders, once.
 *
 * Extracted from `DemoTranscriptQualityPage` so the panel on the recording page
 * shows the same evidence as `/demo` rather than a second, drifting copy. The
 * output is unchanged: the page still renders exactly these sections, in this
 * order.
 *
 * Deliberately left out: the drop zones and the "publish to Docs" button. Those
 * differ between the two callers, so they stay with their caller.
 *
 * The report is always described, never summarised into a verdict. A stage that
 * produced nothing says which of its preconditions was missing, because "0
 * corrections" has several very different causes and they are not
 * interchangeable.
 */
import { marked } from 'marked'
import { DemoReport as DemoReportData } from '@/features/demo/api'

const renderMarkdown = (markdown: string) =>
  marked.parse(markdown, { async: false })

export function Measure({
  label,
  value,
}: {
  label: string
  value: string | number
}) {
  return (
    <div className="demo-measure">
      <span className="demo-measure__value">{value}</span>
      <span className="demo-measure__label">{label}</span>
    </div>
  )
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="demo-empty">{children}</p>
}

/**
 * Why the acronym stage produced no correction, in the report's own terms.
 *
 * Three causes look identical in the corrections table (it is empty in all
 * three) and mean completely different things:
 *
 *  - the transcript carries no word-level timings, so stage 2 has nothing to
 *    locate a flagged passage in and cannot apply anything, whatever the
 *    transcript says;
 *  - stage 1 flagged nothing, so there was nothing suspect to begin with;
 *  - stage 1 flagged passages but the model declined every one of them.
 *
 * Only the second is "the transcript was already correct".
 */
function NoCorrections({ report }: { report: DemoReportData }) {
  if (report.transcript.words === 0) {
    return (
      <Empty>
        Ce transcript ne contient aucun horodatage au mot (
        <code>segments[].words</code> est vide) : l’étape 2 localise les
        passages signalés dans le flux de mots, elle n’a donc rien pu corriger,
        quel que soit le contenu.{' '}
        {report.flagged_spans.length > 0 ? (
          <>
            L’étape 1 a pourtant signalé{' '}
            <strong>{report.flagged_spans.length} passage(s)</strong> : ce « 0
            correction » ne veut pas dire que le transcript était juste.
          </>
        ) : (
          <>L’étape 1 n’a signalé aucun passage.</>
        )}
      </Empty>
    )
  }
  return (
    <Empty>
      Aucune correction produite.{' '}
      {report.flagged_spans.length === 0
        ? 'L’étape 1 n’a signalé aucun passage suspect : il n’y avait donc rien à corriger, avec ou sans glossaire.'
        : `L’étape 1 a signalé ${report.flagged_spans.length} passage(s) suspect(s), mais le modèle n’a retenu aucun acronyme.`}
    </Empty>
  )
}

/**
 * One sentence saying what this run actually did, above the detail.
 *
 * Without it a run that changed nothing renders as two identical transcripts
 * and reads as a failure. It is not: it is a result, and it says so.
 */
export function DemoOutcome({ report }: { report: DemoReportData }) {
  const applied = report.corrections.filter((row) => row.applied).length
  const changedNothing = applied === 0 && report.speakers.length === 0

  return (
    <section
      className={`demo-outcome${changedNothing ? ' demo-outcome--flat' : ''}`}
    >
      {changedNothing ? (
        <>
          <strong>La correction a bien tourné, et n’a rien changé.</strong>{' '}
          Aucun acronyme corrigé, aucun locuteur nommé : le transcript « après »
          est identique au transcript « avant ». Le détail ci-dessous dit
          pourquoi, étape par étape.
        </>
      ) : (
        <>
          <strong>
            {applied} correction(s) d’acronyme appliquée(s),{' '}
            {report.speakers.length} locuteur(s) nommé(s).
          </strong>{' '}
          Les deux transcripts ci-dessous diffèrent de ces changements-là, et
          d’aucun autre.
        </>
      )}
      {report.stats.misses === 0 && report.stats.hits > 0 && (
        <>
          {' '}
          Le modèle n’a pas été appelé : ces {report.stats.hits} réponses
          viennent du cache d’une exécution précédente.
        </>
      )}
    </section>
  )
}

export function DemoReportView({ report }: { report: DemoReportData }) {
  const applied = report.corrections.filter((row) => row.applied).length

  return (
    <>
      <DemoOutcome report={report} />

      <section className="demo-measures">
        <Measure label="segments" value={report.transcript.segments} />
        <Measure label="mots" value={report.transcript.words} />
        <Measure label="entrées de glossaire" value={report.glossary.count} />
        <Measure label="participants" value={report.attendees.count} />
        <Measure
          label="corrections appliquées"
          value={`${applied} / ${report.corrections.length}`}
        />
        <Measure label="locuteurs nommés" value={report.speakers.length} />
        <Measure
          label="cache modèle (hits / miss)"
          value={`${report.stats.hits} / ${report.stats.misses}`}
        />
      </section>

      <p className="demo-note">
        Modèle : <code>{report.model}</code> — seuil de confiance d’application
        : <code>{report.min_confidence}</code>. Un « miss » de cache signifie
        que le modèle a réellement été appelé pour cette exécution.
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
              Aucune entrée lue. Aucun glossaire n’a donc été transmis à l’étape
              de correction : le résultat ci-dessous est celui du glossaire
              livré avec le service, seul.
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
          <NoCorrections report={report} />
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
            l’agenda, soit aucun indice de nom n’a été trouvé dans le transcript
            : les étiquettes <code>SPEAKER_XX</code> sont conservées.
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
    </>
  )
}
