import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import '../i18n'
import ClipTriage from './ClipTriage'
import * as triageApi from '../services/clipTriageApi'
import type { ClipCandidate, ClipTriageSummary, TriageDiver } from '../services/clipTriageApi'

vi.mock('../navigation/mobileShellActions', () => ({
  MobileShellActions: () => null,
}))

vi.mock('../components/session-video/playability', () => ({
  canDecode: async () => true,
  framesRendered: () => true,
}))

const sampleSummary: ClipTriageSummary = {
  can_manage: true,
  pending_count: 2,
  incomplete_count: 1,
  extracting_count: 0,
  published_count: 0,
  rejected_count: 0,
  sessions: [
    { session_id: 118, date: '2026-11-25', title: 'Entraînement mer. 18h', pending: 2, incomplete: 1, extracting: 0, published: 0, rejected: 0 },
  ],
}

const sampleDivers: TriageDiver[] = [
  { id: 1, display_name: 'Maxime', is_own: true, has_account: true, suggested: true },
  { id: 2, display_name: 'Léo', is_own: false, has_account: true, suggested: true },
]

function makeCandidate(id: number, start_s: number, overrides: Partial<ClipCandidate> = {}): ClipCandidate {
  return {
    id,
    session_video_id: 42,
    session_id: 118,
    session_date: '2026-11-25',
    session_title: 'Entraînement mer. 18h',
    video_filename: 'IMG_2651.MOV',
    video_duration_seconds: 1800,
    video_codec_string: 'hvc1.2.4.L123.B0',
    video_audio_codec_string: 'mp4a.40.2',
    video_color_transfer: 'bt709',
    video_play_url: '/api/v1/session-videos/42/play',
    video_download_url: '/api/v1/session-videos/42/download',
    video_poster_url: '/api/v1/session-videos/42/images/poster',
    start_s,
    end_s: start_s + 12,
    trimmed_start_s: null,
    trimmed_end_s: null,
    effective_start_s: start_s,
    effective_end_s: start_s + 12,
    duration_s: 12,
    confidence: 0.94,
    detector_label: null,
    detector_name: 'core_detection',
    detector_version: 'v1.4',
    triage_status: 'pending',
    reject_reason: null,
    skipped_at: null,
    diver_id: null,
    diver_name: null,
    dive_code: null,
    height: null,
    performance: null,
    phase1_performance: null,
    phase2_performance: null,
    notes: null,
    visibility: 'private',
    metadata_complete: false,
    publish_requested: false,
    extraction_status: 'none',
    extraction_error: null,
    cut_revision: 1,
    dive_id: null,
    published_at: null,
    updated_at: '2026-11-25T18:10:00Z',
    ...overrides,
  }
}

describe('ClipTriage fast workflow', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(triageApi, 'getClipTriageSummary').mockResolvedValue(sampleSummary)
    vi.spyOn(triageApi, 'listClipTriageCandidates').mockResolvedValue({
      items: [makeCandidate(10, 120), makeCandidate(11, 240)],
      has_more: false,
      next_offset: null,
      divers: sampleDivers,
    })
  })

  it('autoadvances on reject with serialized undo and supports 1-tap express keep without fabricating height', async () => {
    const order: string[] = []
    let resolveReject!: (val: ClipCandidate) => void
    const patchSpy = vi.spyOn(triageApi, 'patchClipCandidate').mockImplementation((id, patch) => {
      if (id === 10 && patch.triage_status === 'rejected') {
        order.push('reject-start')
        return new Promise<ClipCandidate>((res) => {
          resolveReject = (v) => {
            order.push('reject-end')
            res(v)
          }
        })
      }
      order.push(`patch-${id}-${patch.triage_status ?? 'draft'}`)
      return Promise.resolve({
        ...makeCandidate(id, id === 10 ? 120 : 240),
        triage_status: (patch.triage_status ?? 'pending') as ClipCandidate['triage_status'],
        diver_id: patch.diver_id ?? null,
      })
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/triage']}>
        <ClipTriage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/02:00–02:12/)).toBeInTheDocument()

    // Reject starts (held in flight); immediately clicking Undo must wait for reject to finish first!
    await user.click(screen.getByRole('button', { name: /Rejeter|Reject/i }))
    expect(await screen.findByText(/04:00–04:12/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Annuler|Undo/i }))
    expect(order).toEqual(['reject-start'])

    resolveReject(makeCandidate(10, 120, { triage_status: 'rejected' }))
    await waitFor(() => {
      expect(order).toEqual(['reject-start', 'reject-end', 'patch-10-pending'])
    })
    expect(await screen.findByText(/02:00–02:12/)).toBeInTheDocument()

    // Turn on 1-tap express mode -> single click on Léo keeps without fabricating 3m height or trimmed bounds!
    await user.click(screen.getByRole('button', { name: /1-tap/i }))
    await user.click(screen.getByRole('button', { name: /Léo/i }))
    expect(await screen.findByText(/04:00–04:12/)).toBeInTheDocument()
    const keepCall = patchSpy.mock.calls.find((c) => c[0] === 10 && c[1].triage_status === 'kept')
    expect(keepCall).toBeTruthy()
    expect(keepCall?.[1].diver_id).toBe(2)
    expect(keepCall?.[1].height).toBeUndefined()
    expect(keepCall?.[1].trimmed_start_s).toBeUndefined()
    expect(keepCall?.[1].confirm_publish).toBeUndefined()
  })

  it('merges rapid autosave edits into one patch and sets confirm_publish only on explicit keep & publish', async () => {
    const patchSpy = vi.spyOn(triageApi, 'patchClipCandidate').mockImplementation(async (id, patch) => ({
      ...makeCandidate(id, 120),
      ...patch,
    } as ClipCandidate))

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/triage']}>
        <ClipTriage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/02:00–02:12/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Maxime/i }))
    await user.click(screen.getByRole('button', { name: '5m' }))
    await user.click(screen.getByRole('button', { name: 'G' }))

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledTimes(1)
    }, { timeout: 1500 })
    expect(patchSpy).toHaveBeenCalledWith(
      10,
      expect.objectContaining({ diver_id: 1, height: '5m', performance: 'G' }),
    )
    expect(patchSpy.mock.calls[0][1].confirm_publish).toBeUndefined()

    const codeInput = screen.getByPlaceholderText('103B')
    await user.type(codeInput, '103B')
    await user.click(screen.getByRole('button', { name: /Garder & publier|Keep & publish/i }))

    await waitFor(() => {
      const publishCall = patchSpy.mock.calls.find((c) => c[1].confirm_publish === true)
      expect(publishCall).toBeTruthy()
      expect(publishCall?.[1]).toMatchObject({
        triage_status: 'kept',
        diver_id: 1,
        dive_code: '103B',
        height: '5m',
        performance: 'G',
        confirm_publish: true,
      })
    })
  })

  it('uses keyset cursor for pending refill and ignores shortcuts on focused buttons/repeat', async () => {
    const listSpy = vi.spyOn(triageApi, 'listClipTriageCandidates')
      .mockResolvedValueOnce({
        items: [makeCandidate(10, 120)],
        has_more: true,
        next_offset: 50,
        next_cursor: 'cur-page-2',
        divers: sampleDivers,
      })
      .mockResolvedValueOnce({
        items: [makeCandidate(51, 600)],
        has_more: false,
        next_offset: null,
        next_cursor: null,
        divers: sampleDivers,
      })
    const patchSpy = vi.spyOn(triageApi, 'patchClipCandidate').mockResolvedValue(makeCandidate(10, 120))

    render(
      <MemoryRouter initialEntries={['/triage']}>
        <ClipTriage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/02:00–02:12/)).toBeInTheDocument()
    // Pending refill MUST use keyset cursor (never drifting offset or capped exclude_ids!)
    await waitFor(() => {
      expect(listSpy).toHaveBeenCalledWith(
        expect.objectContaining({ tab: 'pending', cursor: 'cur-page-2' }),
        expect.any(AbortSignal),
      )
    })

    const rejectBtn = screen.getByRole('button', { name: /Rejeter|Reject/i })
    rejectBtn.focus()
    fireEvent.keyDown(rejectBtn, { key: 'x' })
    fireEvent.keyDown(window, { key: 'x', repeat: true })
    expect(patchSpy).not.toHaveBeenCalled()
  })

  it('rolls back cleanly when keep fails on server', async () => {
    vi.spyOn(triageApi, 'patchClipCandidate').mockRejectedValueOnce(new Error('network error'))

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/triage']}>
        <ClipTriage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/02:00–02:12/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /1-tap/i }))
    await user.click(screen.getByRole('button', { name: /Maxime/i }))

    // Rolls back to clip #10, shows alert, and clears stale Undo toast
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/02:00–02:12/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Annuler|Undo/i })).not.toBeInTheDocument()
  })

  it('sends confirm_publish: false on Undo from incomplete tab and fetches direct clip when beyond page 1', async () => {
    const keptDraft = makeCandidate(99, 300, {
      triage_status: 'kept',
      diver_id: 1,
      diver_name: 'Maxime',
      dive_code: '103B',
      height: '3m',
      performance: 'G',
      metadata_complete: true,
      publish_requested: false,
      extraction_status: 'extracting',
    })
    vi.spyOn(triageApi, 'listClipTriageCandidates').mockResolvedValue({
      items: [],
      has_more: false,
      next_offset: null,
      divers: sampleDivers,
    })
    vi.spyOn(triageApi, 'getClipTriageCandidate').mockResolvedValue(keptDraft)
    const patchSpy = vi.spyOn(triageApi, 'patchClipCandidate').mockResolvedValue(keptDraft)

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/triage?tab=incomplete&clip=99']}>
        <ClipTriage />
      </MemoryRouter>,
    )

    // Loaded directly even though page 1 list was empty!
    expect(await screen.findByRole('button', { name: /Retour à la liste|Back to list/i })).toBeInTheDocument()
    expect(screen.getByText(/05:00–05:12/)).toBeInTheDocument()

    // Click Publish -> then Undo -> MUST send confirm_publish: false to revoke publish confirmation!
    await user.click(screen.getByRole('button', { name: /Publier|Publish/i }))
    const undoBtn = await screen.findByRole('button', { name: /Annuler|Undo/i })
    await user.click(undoBtn)

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith(99, { triage_status: 'kept', confirm_publish: false })
    })
  })

  it('triggers pending refill when skipping leaves <= 5 unskipped clips even if total list is > 5', async () => {
    const sixClips = [1, 2, 3, 4, 5, 6].map((id) => makeCandidate(id, id * 30))
    const listSpy = vi.spyOn(triageApi, 'listClipTriageCandidates')
      .mockResolvedValueOnce({
        items: sixClips,
        has_more: true,
        next_offset: 50,
        next_cursor: 'cur-skip-2',
        divers: sampleDivers,
      })
      .mockResolvedValueOnce({
        items: [makeCandidate(7, 300)],
        has_more: false,
        next_offset: null,
        next_cursor: null,
        divers: sampleDivers,
      })
    vi.spyOn(triageApi, 'patchClipCandidate').mockResolvedValue(sixClips[0])

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/triage']}>
        <ClipTriage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/00:30–00:42/)).toBeInTheDocument()
    // 6 unskipped clips initially -> no refill yet
    expect(listSpy).toHaveBeenCalledTimes(1)

    // Skip 1 clip -> unskipped drops to 5 (even though items.length is still 6!) -> triggers refill!
    await user.click(screen.getByRole('button', { name: /Passer|Skip/i }))
    await waitFor(() => {
      expect(listSpy).toHaveBeenCalledTimes(2)
    })
  })

  it('clears Undo toast on tab switch so a pending reject can never open in incomplete', async () => {
    vi.spyOn(triageApi, 'patchClipCandidate').mockResolvedValue(
      makeCandidate(10, 120, { triage_status: 'rejected' }),
    )
    vi.spyOn(triageApi, 'listClipTriageCandidates').mockImplementation(async (params) => {
      if (params.tab === 'incomplete') {
        return {
          items: [
            makeCandidate(80, 500, {
              triage_status: 'kept',
              diver_id: 1,
              diver_name: 'Maxime',
              extraction_status: 'ready',
            }),
          ],
          has_more: false,
          next_offset: null,
          next_cursor: null,
          divers: sampleDivers,
        }
      }
      return {
        items: [makeCandidate(10, 120), makeCandidate(11, 240)],
        has_more: false,
        next_offset: null,
        next_cursor: null,
        divers: sampleDivers,
      }
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/triage']}>
        <ClipTriage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/02:00–02:12/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Rejeter|Reject/i }))
    expect(await screen.findByRole('button', { name: /Annuler|Undo/i })).toBeInTheDocument()

    // Switch to Incomplete tab -> Undo toast MUST disappear immediately!
    const incompleteTab = screen.getAllByRole('tab')[1]
    await user.click(incompleteTab)
    expect(await screen.findByText(/08:20–08:32/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Annuler|Undo/i })).not.toBeInTheDocument()
  })

  it('paginates incomplete beyond 100 clips using keyset cursors and offers completion on ready recent clips', async () => {
    const listSpy = vi.spyOn(triageApi, 'listClipTriageCandidates').mockImplementation(async (params) => {
      if (params.tab === 'recent') {
        return {
          items: [
            makeCandidate(300, 900, {
              triage_status: 'kept',
              diver_id: 1,
              diver_name: 'Maxime',
              dive_code: '103B',
              height: '3m',
              performance: 'G',
              metadata_complete: true,
              publish_requested: true,
              extraction_status: 'ready',
              dive_id: null,
            }),
          ],
          has_more: false,
          next_offset: null,
          next_cursor: null,
          divers: sampleDivers,
        }
      }
      if (!params.cursor) {
        return {
          items: [makeCandidate(101, 60, { triage_status: 'kept', diver_id: 1, diver_name: 'Maxime' })],
          has_more: true,
          next_offset: 50,
          next_cursor: 'inc-cur-2',
          divers: sampleDivers,
        }
      }
      if (params.cursor === 'inc-cur-2') {
        return {
          items: [makeCandidate(151, 300, { triage_status: 'kept', diver_id: 2, diver_name: 'Léo' })],
          has_more: false,
          next_offset: null,
          next_cursor: null,
          divers: sampleDivers,
        }
      }
      return { items: [], has_more: false, next_offset: null, next_cursor: null, divers: sampleDivers }
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/triage?tab=incomplete']}>
        <ClipTriage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/01:00–01:12/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Charger plus|Load more/i }))
    expect(await screen.findByText(/05:00–05:12/)).toBeInTheDocument()
    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ tab: 'incomplete', cursor: 'inc-cur-2' }),
      expect.any(AbortSignal),
    )

    // Switch to Recent -> ready unpublished clip MUST still offer Complete action!
    const recentTab = screen.getAllByRole('tab')[2]
    await user.click(recentTab)
    expect(await screen.findByRole('button', { name: /Compléter|Complete/i })).toBeInTheDocument()
  })

  it('resets loadingMore across tab switch during pending refill and guards delayed restore on Recent', async () => {
    let resolvePendingRefill!: (val: Awaited<ReturnType<typeof triageApi.listClipTriageCandidates>>) => void
    let resolveRestore!: (val: ClipCandidate) => void

    vi.spyOn(triageApi, 'listClipTriageCandidates').mockImplementation((params) => {
      if (params.tab === 'pending' && !params.cursor) {
        return Promise.resolve({
          items: [makeCandidate(10, 60)],
          has_more: true,
          next_offset: 50,
          next_cursor: 'pending-cur-2',
          divers: sampleDivers,
        })
      }
      if (params.tab === 'pending' && params.cursor === 'pending-cur-2') {
        return new Promise((res) => {
          resolvePendingRefill = res
        })
      }
      if (params.tab === 'incomplete' && !params.cursor) {
        return Promise.resolve({
          items: [makeCandidate(200, 120, { triage_status: 'kept', diver_id: 1, diver_name: 'Maxime' })],
          has_more: true,
          next_offset: 50,
          next_cursor: 'inc-cur-2',
          divers: sampleDivers,
        })
      }
      if (params.tab === 'incomplete' && params.cursor === 'inc-cur-2') {
        return Promise.resolve({
          items: [makeCandidate(201, 240, { triage_status: 'kept', diver_id: 2, diver_name: 'Léo' })],
          has_more: false,
          next_offset: null,
          next_cursor: null,
          divers: sampleDivers,
        })
      }
      return Promise.resolve({
        items: [makeCandidate(300, 480, { triage_status: 'rejected' })],
        has_more: false,
        next_offset: null,
        next_cursor: null,
        divers: sampleDivers,
      })
    })
    vi.spyOn(triageApi, 'patchClipCandidate').mockImplementation(
      () => new Promise<ClipCandidate>((res) => { resolveRestore = res }),
    )

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/triage']}>
        <ClipTriage />
      </MemoryRouter>,
    )

    // Pending loads 1 clip and triggers auto-refill (still in flight). Switch to Incomplete!
    expect(await screen.findByText(/01:00–01:12/)).toBeInTheDocument()
    await user.click(screen.getAllByRole('tab')[1])

    // Incomplete's Load more button MUST be enabled and load page 2 cleanly!
    expect(await screen.findByText(/02:00–02:12/)).toBeInTheDocument()
    const loadMoreBtn = screen.getByRole('button', { name: /Charger plus|Load more/i })
    expect(loadMoreBtn).not.toBeDisabled()

    // Even when the stale pending refill resolves late, Load more remains usable.
    resolvePendingRefill({
      items: [makeCandidate(11, 90)],
      has_more: false,
      next_offset: null,
      next_cursor: null,
      divers: sampleDivers,
    })
    await user.click(loadMoreBtn)
    expect(await screen.findByText(/04:00–04:12/)).toBeInTheDocument()

    // Switch to Recent, click Restore (delayed), then immediately switch back to Incomplete!
    await user.click(screen.getAllByRole('tab')[2])
    const restoreBtn = await screen.findByRole('button', { name: /Remettre en tri|Move back to triage/i })
    await user.click(restoreBtn)
    await user.click(screen.getAllByRole('tab')[1])
    expect(await screen.findByText(/02:00–02:12/)).toBeInTheDocument()

    // Delayed restore settles -> MUST NOT overwrite Incomplete with Recent items!
    resolveRestore(makeCandidate(300, 480, { triage_status: 'pending' }))
    await waitFor(() => {
      expect(screen.getByText(/02:00–02:12/)).toBeInTheDocument()
      expect(screen.queryByText(/08:00–08:12/)).not.toBeInTheDocument()
    })
  })
})
