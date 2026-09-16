/**
 * "Traiter un transcript" — the third way into the recordings list.
 *
 * The other two start from audio: record it, or upload it. This one starts
 * from a transcript that already exists, corrects it, and keeps the result as
 * an ordinary recording. Same drop zones as `/demo`, same pipeline, same
 * report; what changes is that the answer is not thrown away when the modal
 * closes.
 *
 * The report is shown before the modal is done, on purpose. A run that
 * corrected nothing has several very different causes, and the only place they
 * are told apart is `DemoReportView` — closing straight to the list would hide
 * the one explanation worth reading.
 *
 * The recording has no audio behind it and never will. That is stated here
 * rather than discovered on the recording page.
 */
import { useState } from 'react'
import {
  Button,
  Input,
  Modal,
  ModalSize,
} from '@gouvfr-lasuite/cunningham-react'
import { useQueryClient } from '@tanstack/react-query'
import { useLocation } from 'wouter'
import { keys } from '@/api/queryKeys'
import { DemoDropZone } from '@/features/demo/DemoDropZone'
import { DemoReportView } from '@/features/demo/DemoReport'
import {
  DemoImported,
  SAMPLES,
  importTranscript,
  loadSample,
} from '@/features/demo/api'

export function ImportTranscriptModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean
  onClose: () => void
}) {
  const [, navigate] = useLocation()
  const queryClient = useQueryClient()

  const [transcript, setTranscript] = useState<File | null>(null)
  const [glossary, setGlossary] = useState<File | null>(null)
  const [calendar, setCalendar] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [result, setResult] = useState<DemoImported | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const reset = () => {
    setTranscript(null)
    setGlossary(null)
    setCalendar(null)
    setTitle('')
    setResult(null)
    setError(null)
  }

  const close = () => {
    if (isRunning) {
      return
    }
    reset()
    onClose()
  }

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

  const submit = async () => {
    if (!transcript) {
      return
    }
    setIsRunning(true)
    setError(null)
    setResult(null)
    try {
      const imported = await importTranscript({
        transcript,
        glossary,
        calendar,
        title,
      })
      setResult(imported)
      // The recording exists now: the list has to be told, or it keeps showing
      // the page it fetched before the run.
      await queryClient.invalidateQueries({ queryKey: [keys.files] })
    } catch (exception) {
      setError((exception as Error).message)
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <Modal
      size={ModalSize.LARGE}
      isOpen={isOpen}
      onClose={close}
      preventClose={isRunning}
      closeOnEsc={!isRunning}
      closeOnClickOutside={!isRunning}
      title="Traiter un transcript"
      rightActions={
        result ? (
          <>
            <Button variant="bordered" color="neutral" onClick={close}>
              Fermer
            </Button>
            <Button
              onClick={() => {
                const id = result.file.id
                reset()
                onClose()
                navigate(`/recordings/${id}`)
              }}
            >
              Ouvrir l’enregistrement
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="bordered"
              color="neutral"
              onClick={close}
              disabled={isRunning}
            >
              Annuler
            </Button>
            <Button onClick={submit} disabled={!transcript || isRunning}>
              {isRunning ? 'Traitement en cours…' : 'Traiter et enregistrer'}
            </Button>
          </>
        )
      }
    >
      <div className="demo-import">
        {result ? (
          <>
            <p className="demo-note">
              <strong>« {result.file.title} » a été créé</strong> et apparaît
              dans la liste des enregistrements. Il n’a pas d’audio : il n’y en
              a jamais eu, seul le transcript a été fourni. La page de
              l’enregistrement n’affichera donc pas de lecteur.
            </p>
            <DemoReportView report={result} />
          </>
        ) : (
          <>
            <p className="demo-muted">
              Corrige un transcript déjà existant (locuteurs, puis acronymes) et
              en fait un <strong>enregistrement normal</strong> dans la liste,
              que l’on ouvre comme les autres. Aucun audio n’est envoyé et aucun
              audio ne sera attaché.
            </p>

            {/* The player captures keydown; the title field must not feed it. */}
            {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
            <div onKeyDown={(event) => event.stopPropagation()}>
              <Input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                label="Titre de l’enregistrement (facultatif)"
                disabled={isRunning}
                maxLength={255}
              />
            </div>

            <div className="demo-drops">
              <DemoDropZone
                title="Transcript"
                hint="JSON WhisperX (segments + words). Obligatoire."
                accept={{ 'application/json': ['.json'] }}
                file={transcript}
                onFile={setTranscript}
                onClear={() => setTranscript(null)}
                disabled={isRunning}
              />
              <DemoDropZone
                title="Glossaire"
                hint="Texte brut : .txt, .csv, ou sans extension. Facultatif."
                file={glossary}
                onFile={setGlossary}
                onClear={() => setGlossary(null)}
                disabled={isRunning}
              />
              <DemoDropZone
                title="Participants"
                hint="Fichier .ics — sert d’indices de nom. Facultatif."
                accept={{ 'text/calendar': ['.ics'] }}
                file={calendar}
                onFile={setCalendar}
                onClear={() => setCalendar(null)}
                disabled={isRunning}
              />
            </div>

            <div className="demo-actions">
              <Button
                color="neutral"
                onClick={loadSamples}
                disabled={isRunning}
              >
                Charger les fichiers d’exemple
              </Button>
              <span className="demo-actions__note">
                Le glossaire et les participants sont facultatifs : retirez-en
                un pour voir ce qu’il apportait.
              </span>
            </div>

            {isRunning && (
              <p className="demo-note">
                Les deux étapes relisent tout le transcript. Comptez une à deux
                minutes au premier passage.
              </p>
            )}

            {error && (
              <div className="demo-error" role="alert">
                {error}
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  )
}
