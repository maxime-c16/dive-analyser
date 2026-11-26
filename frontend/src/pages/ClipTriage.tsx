import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  Pause,
  Play,
  RotateCcw,
  Sparkles,
  Undo2,
  Volume2,
  VolumeX,
  Zap,
} from 'lucide-react'
import PageLoading from '../components/PageLoading'
import { MobileShellActions } from '../navigation/mobileShellActions'
import { canDecode, framesRendered } from '../components/session-video/playability'
import type { SessionVideoInfo } from '../services/sessionVideosApi'
import {
  downloadVideoGroundTruth,
  formatClipTime,
  getClipTriageCandidate,
  getClipTriageSummary,
  listClipTriageCandidates,
  patchClipCandidate,
  retryClipExtraction,
  type CandidatePatch,
  type ClipCandidate,
  type ClipTriageSummary,
  type TriageDiver,
} from '../services/clipTriageApi'
import { performanceLabel } from '../utils/attemptPresentation'
import { performanceScore10 } from '../utils/performanceScoring'
import { scoreNumber } from '../components/evaluation/scoreFormatting'
import './ClipTriage.css'

const HEIGHTS = ['1m', '3m', '5m', '7.5m', '10m'] as const
const LETTERS = ['F', 'B', 'M', 'G', 'P'] as const
const SPEEDS = [1, 0.5, 1.5] as const
const CODE_RE = /^(?:[1-5][0-9]{2,3}|6[0-9]{2})[ABCD]$/
const MAX_VIDEO_RETRIES = 3
const MAX_CLIP_SPAN_S = 60

type TabKey = 'pending' | 'incomplete' | 'recent'
type UndoEntry = {
  candidate: ClipCandidate
  label: string
  previousTab: TabKey
  originGen: number
}

type Draft = {
  diver_id: number | null
  dive_code: string
  height: string
  phased: boolean
  performance: string | null
  phase1: string | null
  phase2: string | null
  notes: string
  visibility: 'private' | 'public'
  trimmed_start_s: number
  trimmed_end_s: number
}

function draftFromCandidate(c: ClipCandidate): Draft {
  const phased = Boolean(c.phase1_performance && c.phase2_performance)
  return {
    diver_id: c.diver_id,
    dive_code: c.dive_code ?? '',
    height: c.height ?? '',
    phased,
    performance: c.performance ?? null,
    phase1: c.phase1_performance ?? null,
    phase2: c.phase2_performance ?? null,
    notes: c.notes ?? '',
    visibility: c.visibility ?? 'private',
    trimmed_start_s: c.effective_start_s,
    trimmed_end_s: c.effective_end_s,
  }
}

function hapticPulse(ms = 12) {
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
      navigator.vibrate(ms)
    }
  } catch {
    // Best effort only.
  }
}

function isInteractiveTarget(target: EventTarget | null): {
  isFormControl: boolean
  isCodeInput: boolean
  isInteractive: boolean
} {
  if (!(target instanceof HTMLElement)) {
    return { isFormControl: false, isCodeInput: false, isInteractive: false }
  }
  if (target.isContentEditable) {
    return { isFormControl: true, isCodeInput: false, isInteractive: true }
  }
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
    return {
      isFormControl: true,
      isCodeInput: tag === 'INPUT' && target.dataset.triageCode === 'true',
      isInteractive: true,
    }
  }
  if (
    tag === 'BUTTON' ||
    tag === 'A' ||
    target.closest('button, a, [role="button"], [role="tab"], [role="slider"]') !== null
  ) {
    return { isFormControl: false, isCodeInput: false, isInteractive: true }
  }
  return { isFormControl: false, isCodeInput: false, isInteractive: false }
}

function withRetryParam(url: string, retry: number): string {
  if (retry <= 0) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}r=${retry}`
}

export default function ClipTriage() {
  const { t, i18n } = useTranslation()
  const [search, setSearch] = useSearchParams()
  const rawTab = search.get('tab')
  const tab: TabKey = rawTab === 'incomplete' || rawTab === 'recent' ? rawTab : 'pending'
  const sessionFilter = search.get('session') ? Number(search.get('session')) : null
  const requestedClipId = search.get('clip') ? Number(search.get('clip')) : null

  const [summary, setSummary] = useState<ClipTriageSummary | null>(null)
  const [items, setItems] = useState<ClipCandidate[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [divers, setDivers] = useState<TriageDiver[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Active clip in the fast triage stage (index 0 for pending, or selected clip in incomplete)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [expressMode, setExpressMode] = useState(false)
  const [detailsOpenMobile, setDetailsOpenMobile] = useState(false)
  const [showAllDivers, setShowAllDivers] = useState(false)
  const [triagedThisSession, setTriagedThisSession] = useState(0)
  const [flash, setFlash] = useState<{ tone: 'kept' | 'rejected' | 'skipped'; label: string } | null>(null)
  const [undoEntry, setUndoEntry] = useState<UndoEntry | null>(null)

  // Looping segment player state (reuses one <video> across clips of the same session video)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(true)
  const [speedIdx, setSpeedIdx] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [videoRetry, setVideoRetry] = useState(0)
  const [unplayable, setUnplayable] = useState(false)

  // Serialization & buffered patch refs (per-candidate timers + queue prevent race/loss)
  const autosaveTimersRef = useRef<Map<number, number>>(new Map())
  const flashTimer = useRef<number | null>(null)
  const undoTimer = useRef<number | null>(null)
  const pendingPatchesRef = useRef<Map<number, CandidatePatch>>(new Map())
  const candidateChainsRef = useRef<Map<number, Promise<unknown>>>(new Map())
  const inFlightRemovedRef = useRef<Set<number>>(new Set())
  const trimDirtyRef = useRef<Set<number>>(new Set())
  const itemsRef = useRef<ClipCandidate[]>([])
  const draftRef = useRef<Draft | null>(null)
  const activeIdRef = useRef<number | null>(null)
  const loadingMoreRef = useRef(false)
  const loadMoreControllerRef = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)
  const generation = useRef(0)
  const tabRef = useRef<TabKey>(tab)

  itemsRef.current = items
  draftRef.current = draft
  tabRef.current = tab

  const active = useMemo(() => {
    if (!items.length) return null
    if (activeId != null) {
      const found = items.find((item) => item.id === activeId)
      if (found) return found
    }
    return tab === 'pending' ? items[0] : null
  }, [items, activeId, tab])

  activeIdRef.current = active?.id ?? null

  const enqueueCandidateOp = useCallback(<T,>(candidateId: number, op: () => Promise<T>): Promise<T> => {
    const prev = candidateChainsRef.current.get(candidateId) ?? Promise.resolve()
    const next = prev.catch(() => undefined).then(op)
    const settled = next.then(
      () => undefined,
      () => undefined,
    ).finally(() => {
      if (candidateChainsRef.current.get(candidateId) === settled) {
        candidateChainsRef.current.delete(candidateId)
      }
    })
    candidateChainsRef.current.set(candidateId, settled)
    return next
  }, [])

  const clearCandidateTimer = useCallback((candidateId?: number) => {
    if (candidateId != null) {
      const tid = autosaveTimersRef.current.get(candidateId)
      if (tid != null) {
        window.clearTimeout(tid)
        autosaveTimersRef.current.delete(candidateId)
      }
    } else {
      for (const tid of autosaveTimersRef.current.values()) {
        window.clearTimeout(tid)
      }
      autosaveTimersRef.current.clear()
    }
  }, [])

  const flushAutosave = useCallback((candidateId?: number) => {
    clearCandidateTimer(candidateId)
    const targetIds =
      candidateId != null
        ? (pendingPatchesRef.current.has(candidateId) ? [candidateId] : [])
        : [...pendingPatchesRef.current.keys()]

    for (const id of targetIds) {
      const buffered = pendingPatchesRef.current.get(id)
      pendingPatchesRef.current.delete(id)
      if (!buffered || Object.keys(buffered).length === 0) continue
      if (mountedRef.current) setSaveState('saving')
      void enqueueCandidateOp(id, async () => {
        const updated = await patchClipCandidate(id, buffered)
        if (!mountedRef.current) return
        setItems((prev) => prev.map((it) => (it.id === updated.id ? updated : it)))
        if (activeIdRef.current === id) setSaveState('saved')
      }).catch(() => {
        if (mountedRef.current && activeIdRef.current === id) setSaveState('error')
      })
    }
  }, [clearCandidateTimer, enqueueCandidateOp])

  // Flush any buffered edits & clear timers on unmount (never drop edits within 420ms of navigation)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      loadMoreControllerRef.current?.abort()
      flushAutosave()
      if (flashTimer.current) window.clearTimeout(flashTimer.current)
      if (undoTimer.current) window.clearTimeout(undoTimer.current)
    }
  }, [flushAutosave])

  const clearUndo = useCallback(() => {
    if (undoTimer.current) {
      window.clearTimeout(undoTimer.current)
      undoTimer.current = null
    }
    setUndoEntry(null)
  }, [])

  const loadQueue = useCallback(async (signal?: AbortSignal) => {
    const gen = ++generation.current
    loadMoreControllerRef.current?.abort()
    loadMoreControllerRef.current = null
    loadingMoreRef.current = false
    setLoadingMore(false)
    clearUndo()
    setLoading(true)
    setItems([])
    setActiveId(null)
    setDraft(null)
    setHasMore(false)
    setNextCursor(null)
    setError('')
    try {
      const [sum, list] = await Promise.all([
        getClipTriageSummary(signal),
        listClipTriageCandidates({ tab, session_id: sessionFilter, limit: 50 }, signal),
      ])
      if (signal?.aborted || gen !== generation.current) return
      let nextItems = list.items
      let initialActive: number | null = null
      if (tab === 'pending' && nextItems.length > 0) {
        initialActive = nextItems[0].id
      } else if (tab === 'incomplete' && requestedClipId != null) {
        const match = nextItems.find((it) => it.id === requestedClipId)
        if (match) {
          initialActive = match.id
        } else {
          // Fetch requested candidate directly if beyond page 1 or awaiting confirmation
          try {
            const direct = await getClipTriageCandidate(requestedClipId, signal)
            if (signal?.aborted || gen !== generation.current) return
            if (direct.dive_id == null && direct.triage_status === 'kept') {
              nextItems = [direct, ...nextItems]
              initialActive = direct.id
            }
          } catch {
            // Unavailable/already published -> fall back cleanly to incomplete list.
          }
        }
      }
      setSummary(sum)
      setItems(nextItems)
      setHasMore(Boolean(list.has_more && list.next_cursor))
      setNextCursor(list.next_cursor ?? null)
      setDivers(list.divers)
      setActiveId(initialActive)
    } catch (err) {
      if (signal?.aborted || (err as { name?: string })?.name === 'AbortError') return
      setError(t('clipTriage.loadError'))
    } finally {
      if (!signal?.aborted && gen === generation.current) setLoading(false)
    }
  }, [tab, sessionFilter, requestedClipId, clearUndo, t])

  useEffect(() => {
    const controller = new AbortController()
    void loadQueue(controller.signal)
    return () => controller.abort()
  }, [loadQueue])

  const loadMoreItems = useCallback(async () => {
    if (!hasMore || !nextCursor || loadingMoreRef.current) return
    const gen = generation.current
    loadMoreControllerRef.current?.abort()
    const controller = new AbortController()
    loadMoreControllerRef.current = controller
    loadingMoreRef.current = true
    setLoadingMore(true)
    try {
      let cur: string | null = nextCursor
      let lastHasMore = false
      const collected: ClipCandidate[] = []
      const seen = new Set([...itemsRef.current.map((it) => it.id), ...inFlightRemovedRef.current])

      // Advance keyset cursor cleanly; bound multi-hop skips if pending tail repeats locally skipped items.
      for (let hop = 0; hop < 5 && cur; hop += 1) {
        const list = await listClipTriageCandidates(
          {
            tab,
            session_id: sessionFilter,
            limit: 50,
            cursor: cur,
          },
          controller.signal,
        )
        if (!mountedRef.current || controller.signal.aborted || gen !== generation.current) return
        for (const it of list.items) {
          if (!seen.has(it.id)) {
            seen.add(it.id)
            collected.push(it)
          }
        }
        const nextCur = list.next_cursor ?? null
        lastHasMore = Boolean(list.has_more && nextCur && nextCur !== cur)
        cur = lastHasMore ? nextCur : null
        if (collected.length > 0 || !lastHasMore) break
      }

      if (!mountedRef.current || controller.signal.aborted || gen !== generation.current) return
      if (collected.length > 0) {
        setItems((prev) => {
          const prevSeen = new Set([...prev.map((it) => it.id), ...inFlightRemovedRef.current])
          const fresh = collected.filter((it) => !prevSeen.has(it.id))
          if (tab === 'pending') {
            // Place newly fetched unskipped clips ahead of locally skipped items at the tail.
            const unskipped = prev.filter((it) => !it.skipped_at)
            const skipped = prev.filter((it) => Boolean(it.skipped_at))
            return [...unskipped, ...fresh, ...skipped]
          }
          return [...prev, ...fresh]
        })
      }
      setHasMore(lastHasMore)
      setNextCursor(cur)
    } catch (err) {
      if (controller.signal.aborted || (err as { name?: string })?.name === 'AbortError') return
      if (mountedRef.current && gen === generation.current) setError(t('clipTriage.loadError'))
    } finally {
      if (loadMoreControllerRef.current === controller) {
        loadMoreControllerRef.current = null
      }
      if (gen === generation.current) {
        loadingMoreRef.current = false
        if (mountedRef.current) setLoadingMore(false)
      }
    }
  }, [hasMore, nextCursor, tab, sessionFilter, t])

  // Auto-fetch next page in pending mode when unskipped items drop to <= 5 (even if user Skips!)
  const unskippedPendingCount = useMemo(
    () => (tab === 'pending' ? items.filter((it) => !it.skipped_at).length : items.length),
    [tab, items],
  )
  useEffect(() => {
    if (tab === 'pending' && !loading && hasMore && unskippedPendingCount <= 5) {
      void loadMoreItems()
    }
  }, [tab, loading, hasMore, unskippedPendingCount, loadMoreItems])

  // Check browser playability whenever the underlying SessionVideo changes
  const activeVideoId = active?.session_video_id ?? null
  const activeCodec = active?.video_codec_string ?? null
  useEffect(() => {
    setVideoRetry(0)
    setUnplayable(false)
    if (!activeVideoId || !activeCodec) return
    let cancelled = false
    void canDecode({ codec_string: activeCodec } as SessionVideoInfo).then((ok) => {
      if (!cancelled && !ok) setUnplayable(true)
    })
    return () => {
      cancelled = true
    }
  }, [activeVideoId, activeCodec])

  // Sync draft whenever active clip changes
  const activeCandidateId = active?.id ?? null
  useEffect(() => {
    if (!active) {
      setDraft(null)
      setSaveState('idle')
      return
    }
    setDraft(draftFromCandidate(active))
    setSaveState('idle')
    setCurrentTime(active.effective_start_s)
    // Seamless same-video Range seek without destroying <video>
    const el = videoRef.current
    if (el && el.readyState >= 1) {
      el.currentTime = active.effective_start_s
      void el.play().catch(() => {})
    }
  }, [activeCandidateId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Segment loop enforcement + black-frame detection
  useEffect(() => {
    const el = videoRef.current
    if (!el || !draft) return
    el.playbackRate = SPEEDS[speedIdx]
    const onTimeUpdate = () => {
      if (el.seeking) return
      const now = el.currentTime
      setCurrentTime(now)
      if (now >= draft.trimmed_end_s || now < draft.trimmed_start_s - 0.5) {
        el.currentTime = draft.trimmed_start_s
      }
      if (now > draft.trimmed_start_s + 0.4 && el.readyState >= 2 && !framesRendered(el)) {
        setUnplayable(true)
      }
    }
    const onEnded = () => {
      el.currentTime = draft.trimmed_start_s
      void el.play().catch(() => {})
    }
    el.addEventListener('timeupdate', onTimeUpdate)
    el.addEventListener('ended', onEnded)
    return () => {
      el.removeEventListener('timeupdate', onTimeUpdate)
      el.removeEventListener('ended', onEnded)
    }
  }, [draft?.trimmed_start_s, draft?.trimmed_end_s, speedIdx, videoRetry, activeCandidateId])

  const triggerFlash = useCallback((tone: 'kept' | 'rejected' | 'skipped', label: string) => {
    if (flashTimer.current) window.clearTimeout(flashTimer.current)
    setFlash({ tone, label })
    flashTimer.current = window.setTimeout(() => setFlash(null), 550)
  }, [])

  const scheduleAutosave = useCallback((candidateId: number, patch: CandidatePatch) => {
    const existing = pendingPatchesRef.current.get(candidateId) ?? {}
    pendingPatchesRef.current.set(candidateId, { ...existing, ...patch })
    clearCandidateTimer(candidateId)
    setSaveState('saving')
    const tid = window.setTimeout(() => {
      autosaveTimersRef.current.delete(candidateId)
      flushAutosave(candidateId)
    }, 420)
    autosaveTimersRef.current.set(candidateId, tid)
  }, [clearCandidateTimer, flushAutosave])

  const updateDraft = useCallback((partial: Partial<Draft>, immediatePatch?: CandidatePatch) => {
    const currentActive = active
    setDraft((prev) => (prev ? { ...prev, ...partial } : prev))
    if (currentActive && immediatePatch) {
      scheduleAutosave(currentActive.id, immediatePatch)
    }
  }, [active, scheduleAutosave])

  const nudgeBound = useCallback((edge: 'start' | 'end', delta: number) => {
    if (!active || !draft) return
    const maxDur = active.video_duration_seconds ?? draft.trimmed_end_s + 30
    let nextStart = draft.trimmed_start_s
    let nextEnd = draft.trimmed_end_s
    if (edge === 'start') {
      const minStart = Math.max(0, nextEnd - MAX_CLIP_SPAN_S)
      nextStart = Math.max(minStart, Math.min(nextEnd - 1, Math.round((nextStart + delta) * 10) / 10))
    } else {
      const maxEnd = Math.min(maxDur, nextStart + MAX_CLIP_SPAN_S)
      nextEnd = Math.min(maxEnd, Math.max(nextStart + 1, Math.round((nextEnd + delta) * 10) / 10))
    }
    if (nextStart === draft.trimmed_start_s && nextEnd === draft.trimmed_end_s) return
    trimDirtyRef.current.add(active.id)
    setDraft({ ...draft, trimmed_start_s: nextStart, trimmed_end_s: nextEnd })
    if (videoRef.current && videoRef.current.readyState >= 1) {
      videoRef.current.currentTime = edge === 'start' ? nextStart : Math.max(nextStart, nextEnd - 1.2)
    }
    scheduleAutosave(active.id, { trimmed_start_s: nextStart, trimmed_end_s: nextEnd })
  }, [active, draft, scheduleAutosave])

  const setUndo = useCallback((entry: UndoEntry) => {
    if (undoTimer.current) window.clearTimeout(undoTimer.current)
    setUndoEntry(entry)
    undoTimer.current = window.setTimeout(() => setUndoEntry(null), 6500)
  }, [])

  const selectedDiverObj = useMemo(
    () => (draft?.diver_id != null ? divers.find((d) => d.id === draft.diver_id) ?? null : null),
    [divers, draft?.diver_id],
  )

  const codeClean = (draft?.dive_code ?? '').trim().toUpperCase()
  const codeValid = CODE_RE.test(codeClean)
  const hasRating = draft ? (draft.phased ? Boolean(draft.phase1 && draft.phase2) : Boolean(draft.performance)) : false
  const isCompleteDraft = Boolean(draft?.diver_id && codeValid && draft?.height && hasRating)

  const refreshSummary = useCallback(() => {
    void getClipTriageSummary().then((s) => {
      if (mountedRef.current) setSummary(s)
    }).catch(() => {})
  }, [])

  const commitKeep = useCallback(async (overrideDiverId?: number) => {
    if (!active || !draft) return
    const diverId = overrideDiverId ?? draft.diver_id
    if (diverId == null) return

    clearCandidateTimer(active.id)
    const buffered = pendingPatchesRef.current.get(active.id) ?? {}
    pendingPatchesRef.current.delete(active.id)

    const diverName = divers.find((d) => d.id === diverId)?.display_name ?? ''
    const complete = Boolean(diverId && codeValid && draft.height && hasRating)
    const patch: CandidatePatch = {
      ...buffered,
      triage_status: 'kept',
      diver_id: diverId,
      notes: draft.notes.trim() || null,
      visibility: draft.visibility,
    }
    if (trimDirtyRef.current.has(active.id)) {
      patch.trimmed_start_s = draft.trimmed_start_s
      patch.trimmed_end_s = draft.trimmed_end_s
      trimDirtyRef.current.delete(active.id)
    }
    if (codeValid) patch.dive_code = codeClean
    else if (draft.dive_code.trim() === '') patch.dive_code = null
    if (draft.height) patch.height = draft.height
    if (draft.phased && draft.phase1 && draft.phase2) {
      patch.phase1_performance = draft.phase1
      patch.phase2_performance = draft.phase2
    } else if (!draft.phased) {
      patch.performance = draft.performance
      if (active.phase1_performance || active.phase2_performance) {
        patch.phase1_performance = null
        patch.phase2_performance = null
      }
    }
    if (complete) {
      patch.confirm_publish = true
    }

    const snapshot = active
    const opGen = generation.current
    const publishesImmediately = Boolean(complete && snapshot.extraction_status === 'ready')
    const remaining = itemsRef.current.filter((it) => it.id !== snapshot.id)
    const nextActiveId = tab === 'pending' ? (remaining[0]?.id ?? null) : null

    // Optimistic autoadvance + immediate confirmation cue
    inFlightRemovedRef.current.add(snapshot.id)
    hapticPulse(14)
    triggerFlash(
      'kept',
      complete
        ? t('clipTriage.flashKeptPublished', { code: codeClean, diver: diverName })
        : t('clipTriage.flashKept', { diver: diverName }),
    )
    setTriagedThisSession((n) => n + 1)
    setItems(remaining)
    setActiveId(nextActiveId)
    if (!publishesImmediately) {
      setUndo({
        candidate: snapshot,
        label: complete
          ? t('clipTriage.undoKeptComplete', { code: codeClean, diver: diverName })
          : t('clipTriage.undoKeptDraft', { diver: diverName }),
        previousTab: tab,
        originGen: opGen,
      })
    } else {
      clearUndo()
    }

    try {
      await enqueueCandidateOp(snapshot.id, () => patchClipCandidate(snapshot.id, patch))
      inFlightRemovedRef.current.delete(snapshot.id)
      refreshSummary()
    } catch {
      inFlightRemovedRef.current.delete(snapshot.id)
      if (!mountedRef.current || opGen !== generation.current) return
      // Roll back cleanly (deduped) only if still on the same tab/session generation
      setItems((prev) => [snapshot, ...prev.filter((it) => it.id !== snapshot.id)])
      setActiveId(snapshot.id)
      setTriagedThisSession((n) => Math.max(0, n - 1))
      setUndoEntry((prev) => (prev?.candidate.id === snapshot.id ? null : prev))
      setError(t('clipTriage.saveError'))
    }
  }, [active, draft, clearCandidateTimer, clearUndo, divers, codeValid, codeClean, hasRating, t, tab, triggerFlash, setUndo, refreshSummary, enqueueCandidateOp])

  const commitReject = useCallback(async () => {
    if (!active) return
    clearCandidateTimer(active.id)
    pendingPatchesRef.current.delete(active.id)
    trimDirtyRef.current.delete(active.id)

    const snapshot = active
    const opGen = generation.current
    const remaining = itemsRef.current.filter((it) => it.id !== snapshot.id)
    const nextActiveId = tab === 'pending' ? (remaining[0]?.id ?? null) : null

    inFlightRemovedRef.current.add(snapshot.id)
    hapticPulse(10)
    triggerFlash('rejected', t('clipTriage.flashRejected'))
    setTriagedThisSession((n) => n + 1)
    setItems(remaining)
    setActiveId(nextActiveId)
    setUndo({
      candidate: snapshot,
      label: t('clipTriage.undoRejected'),
      previousTab: tab,
      originGen: opGen,
    })

    try {
      await enqueueCandidateOp(snapshot.id, () =>
        patchClipCandidate(snapshot.id, { triage_status: 'rejected', reject_reason: 'false_positive' }),
      )
      inFlightRemovedRef.current.delete(snapshot.id)
      refreshSummary()
    } catch {
      inFlightRemovedRef.current.delete(snapshot.id)
      if (!mountedRef.current || opGen !== generation.current) return
      setItems((prev) => [snapshot, ...prev.filter((it) => it.id !== snapshot.id)])
      setActiveId(snapshot.id)
      setTriagedThisSession((n) => Math.max(0, n - 1))
      setUndoEntry((prev) => (prev?.candidate.id === snapshot.id ? null : prev))
      setError(t('clipTriage.saveError'))
    }
  }, [active, clearCandidateTimer, t, tab, triggerFlash, setUndo, refreshSummary, enqueueCandidateOp])

  const commitSkip = useCallback(async () => {
    if (!active) return
    const snapshot = active
    flushAutosave(snapshot.id)
    triggerFlash('skipped', t('clipTriage.flashSkipped'))
    const skippedCopy: ClipCandidate = { ...snapshot, skipped_at: new Date().toISOString() }
    const rest = itemsRef.current.filter((it) => it.id !== snapshot.id)
    const next = [...rest, skippedCopy]
    setItems(next)
    setActiveId(next[0]?.id ?? null)
    try {
      await enqueueCandidateOp(snapshot.id, () => patchClipCandidate(snapshot.id, { skip: true }))
    } catch {
      // Non-critical; order stays usable locally.
    }
  }, [active, flushAutosave, t, triggerFlash, enqueueCandidateOp])

  const handleUndo = useCallback(async () => {
    if (!undoEntry) return
    const entry = undoEntry
    clearUndo()
    if (entry.previousTab !== tabRef.current || entry.originGen !== generation.current) return
    const targetStatus = entry.candidate.triage_status
    const undoPatch: CandidatePatch =
      targetStatus === 'kept'
        ? { triage_status: 'kept', confirm_publish: false }
        : { triage_status: targetStatus }
    try {
      const restored = await enqueueCandidateOp(entry.candidate.id, () =>
        patchClipCandidate(entry.candidate.id, undoPatch),
      )
      if (!mountedRef.current || entry.originGen !== generation.current || entry.previousTab !== tabRef.current) return
      setItems((prev) => [restored, ...prev.filter((it) => it.id !== restored.id)])
      setActiveId(restored.id)
      setTriagedThisSession((n) => Math.max(0, n - 1))
      refreshSummary()
    } catch {
      if (mountedRef.current && entry.originGen === generation.current) setError(t('clipTriage.saveError'))
    }
  }, [undoEntry, clearUndo, enqueueCandidateOp, refreshSummary, t])

  // Suggested quick-tap divers (top 6)
  const quickDivers = useMemo(() => {
    const preferred = divers.filter((d) => d.is_own || d.suggested)
    const base = preferred.length ? preferred : divers
    return base.slice(0, 6)
  }, [divers])

  // Keyboard shortcuts for desktop fast triage (safely scoped away from controls/modifiers/repeats)
  useEffect(() => {
    if (loading || (tab !== 'pending' && activeId == null)) return
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return
      const { isFormControl, isCodeInput, isInteractive } = isInteractiveTarget(e.target)
      if (isFormControl) {
        if (isCodeInput && e.key === 'Enter' && !e.shiftKey && draftRef.current?.diver_id != null) {
          e.preventDefault()
          void commitKeep()
        }
        return
      }
      if (isInteractive) return

      if (e.key === 'Escape' && tab === 'incomplete' && activeId != null) {
        flushAutosave(activeId)
        setActiveId(null)
        return
      }
      if (e.code === 'Space') {
        e.preventDefault()
        const el = videoRef.current
        if (!el) return
        if (el.paused) void el.play().catch(() => {})
        else el.pause()
      } else if (e.key === 'x' || e.key === 'X') {
        e.preventDefault()
        void commitReject()
      } else if (e.key === 's' || e.key === 'S' || e.key === 'ArrowRight') {
        e.preventDefault()
        void commitSkip()
      } else if (e.key === 'Enter' && draftRef.current?.diver_id != null) {
        e.preventDefault()
        void commitKeep()
      } else if ((e.key === 'z' || e.key === 'Z') && undoEntry) {
        e.preventDefault()
        void handleUndo()
      } else if (e.key >= '1' && e.key <= '6') {
        const picked = quickDivers[Number(e.key) - 1]
        if (picked) {
          e.preventDefault()
          if (expressMode && tab === 'pending') {
            void commitKeep(picked.id)
          } else {
            updateDraft({ diver_id: picked.id }, { diver_id: picked.id })
          }
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [loading, tab, activeId, commitKeep, commitReject, commitSkip, handleUndo, undoEntry, quickDivers, expressMode, updateDraft, flushAutosave])

  const setTab = (nextTab: TabKey, clipId?: number) => {
    flushAutosave()
    clearUndo()
    setSearch((prev) => {
      const next = new URLSearchParams(prev)
      if (nextTab === 'pending') next.delete('tab')
      else next.set('tab', nextTab)
      if (clipId != null) next.set('clip', String(clipId))
      else next.delete('clip')
      return next
    }, { replace: true })
  }

  const setSessionId = (id: string) => {
    flushAutosave()
    clearUndo()
    setSearch((prev) => {
      const next = new URLSearchParams(prev)
      if (id) next.set('session', id)
      else next.delete('session')
      next.delete('clip')
      return next
    }, { replace: true })
  }

  const closeIncompleteEditor = () => {
    if (active) flushAutosave(active.id)
    setActiveId(null)
    if (search.has('clip')) {
      setSearch((prev) => {
        const next = new URLSearchParams(prev)
        next.delete('clip')
        return next
      }, { replace: true })
    }
  }

  const previewScore = useMemo(() => {
    if (!draft) return null
    if (draft.phased) {
      return draft.phase1 && draft.phase2 ? performanceScore10(null, draft.phase1, draft.phase2) : null
    }
    return draft.performance ? performanceScore10(draft.performance) : null
  }, [draft])

  const totalWork = (summary?.pending_count ?? 0) + triagedThisSession
  const progressPct = totalWork > 0 ? Math.min(100, Math.round((triagedThisSession / totalWork) * 100)) : 0

  if (loading && !summary) return <PageLoading />

  if (summary && !summary.can_manage) {
    return (
      <div className="app-panel mx-auto max-w-lg py-10 text-center">
        <p className="text-app-muted">{t('clipTriage.noAccess')}</p>
        <Link to="/dives" className="touch-target mt-4 inline-flex items-center border border-app-accent px-4 text-sm text-app-accent">
          {t('notFound.backToLibrary')}
        </Link>
      </div>
    )
  }

  const showEditor =
    !loading &&
    ((tab === 'pending' && active && draft) || (tab === 'incomplete' && activeId != null && active && draft))

  return (
    <div className="triage-page">
      <MobileShellActions />

      {triagedThisSession > 0 && (
        <div className="triage-progress-track" aria-hidden="true">
          <div className="triage-progress-fill" style={{ width: `${progressPct}%` }} />
        </div>
      )}

      <header className="triage-topbar">
        <div className="triage-tabs" role="tablist" aria-label={t('clipTriage.tabsAria')}>
          <button type="button" role="tab" className="triage-tab" aria-selected={tab === 'pending'} onClick={() => setTab('pending')}>
            {t('clipTriage.tabPending')}
            <span className="font-mono text-xs text-app-accent">{summary?.pending_count ?? 0}</span>
          </button>
          <button type="button" role="tab" className="triage-tab" aria-selected={tab === 'incomplete'} onClick={() => setTab('incomplete')}>
            {t('clipTriage.tabIncomplete')}
            <span className="font-mono text-xs text-amber-300">{summary?.incomplete_count ?? 0}</span>
          </button>
          <button type="button" role="tab" className="triage-tab" aria-selected={tab === 'recent'} onClick={() => setTab('recent')}>
            {t('clipTriage.tabRecent')}
          </button>
        </div>

        <div className="triage-top-controls">
          {tab === 'pending' && (
            <button
              type="button"
              className="triage-express-toggle"
              aria-pressed={expressMode}
              onClick={() => setExpressMode((v) => !v)}
              title={t('clipTriage.expressHint')}
            >
              <Zap size={14} aria-hidden />
              <span>{t('clipTriage.expressMode')}</span>
            </button>
          )}
          {summary && summary.sessions.length > 0 && (
            <select
              aria-label={t('clipTriage.filterSession')}
              className="app-input min-h-[38px] py-1 text-xs"
              value={sessionFilter ?? ''}
              onChange={(e) => setSessionId(e.target.value)}
            >
              <option value="">{t('clipTriage.allSessions')}</option>
              {summary.sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {s.title || s.date} ({s.pending})
                </option>
              ))}
            </select>
          )}
          <span className="triage-save-cue" data-state={saveState} role="status">
            {saveState === 'saving' && t('clipTriage.saving')}
            {saveState === 'saved' && <><Check size={13} aria-hidden /> {t('clipTriage.saved')}</>}
            {saveState === 'error' && t('clipTriage.saveErrorShort')}
          </span>
        </div>
      </header>

      {error && <p role="alert" className="border-l-2 border-red-400 bg-app-panel px-3 py-2 text-sm text-red-300">{error}</p>}

      {undoEntry && (
        <div className="triage-undo-toast" role="status">
          <span>{undoEntry.label}</span>
          <button type="button" onClick={() => void handleUndo()} className="inline-flex items-center gap-1.5">
            <Undo2 size={14} aria-hidden />
            {t('clipTriage.undo')}
          </button>
        </div>
      )}

      {showEditor && active && draft ? (
        <div className="triage-workspace">
          {/* LEFT: Looping B2 Segment Stage */}
          <section className="triage-stage-col">
            {tab === 'incomplete' && (
              <div>
                <button
                  type="button"
                  onClick={closeIncompleteEditor}
                  className="touch-target inline-flex items-center gap-1.5 text-sm font-medium text-app-muted hover:text-app-text"
                >
                  <ArrowLeft size={15} aria-hidden />
                  {t('clipTriage.backToList')}
                </button>
              </div>
            )}

            <div className="triage-video-shell" data-flash={flash?.tone}>
              <video
                key={`${active.session_video_id}:${videoRetry}`}
                ref={videoRef}
                src={withRetryParam(active.video_play_url, videoRetry)}
                poster={active.video_poster_url}
                playsInline
                muted={muted}
                preload="auto"
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onError={() => {
                  if (videoRetry < MAX_VIDEO_RETRIES) {
                    setVideoRetry((r) => r + 1)
                  } else {
                    setUnplayable(true)
                  }
                }}
                onClick={() => {
                  const el = videoRef.current
                  if (!el) return
                  if (el.paused) void el.play().catch(() => {})
                  else el.pause()
                }}
                onLoadedMetadata={(e) => {
                  e.currentTarget.currentTime = draft.trimmed_start_s
                  e.currentTarget.playbackRate = SPEEDS[speedIdx]
                  void e.currentTarget.play().catch(() => {})
                }}
              />
              <div className="triage-hud-top">
                <span className="triage-hud-pill">
                  <span className="triage-hud-dot" />
                  {active.session_title || active.session_date} · {active.video_filename}
                </span>
                {active.confidence != null && (
                  <span className="triage-hud-pill font-mono">
                    {Math.round(active.confidence * 100)}%
                  </span>
                )}
              </div>

              {unplayable && (
                <div className="triage-unplayable" role="alert">
                  <p>{t('clipTriage.unplayable')}</p>
                  <a
                    href={active.video_download_url}
                    className="touch-target inline-flex items-center gap-2 rounded-lg border border-app-accent px-4 text-xs font-semibold text-app-accent"
                  >
                    <Download size={14} aria-hidden />
                    {t('clipTriage.downloadOriginal')}
                  </a>
                </div>
              )}

              {flash && (
                <div className="triage-flash-badge" data-tone={flash.tone}>
                  <span>{flash.label}</span>
                </div>
              )}

              <div className="triage-hud-bottom">
                <input
                  type="range"
                  className="triage-seg-range"
                  aria-label={t('clipTriage.scrubAria')}
                  min={draft.trimmed_start_s}
                  max={Math.max(draft.trimmed_start_s + 0.5, draft.trimmed_end_s)}
                  step={0.1}
                  value={Math.max(draft.trimmed_start_s, Math.min(draft.trimmed_end_s, currentTime))}
                  onChange={(e) => {
                    const target = Number(e.target.value)
                    if (videoRef.current) videoRef.current.currentTime = target
                    setCurrentTime(target)
                  }}
                />
                <div className="triage-transport">
                  <div className="triage-transport-left">
                    <button
                      type="button"
                      className="triage-ctrl-btn"
                      onClick={() => {
                        const el = videoRef.current
                        if (!el) return
                        if (el.paused) void el.play().catch(() => {})
                        else el.pause()
                      }}
                    >
                      {playing ? <Pause size={13} aria-hidden /> : <Play size={13} aria-hidden />}
                      <span>{playing ? t('clipTriage.pause') : t('clipTriage.play')}</span>
                    </button>
                    <button
                      type="button"
                      className="triage-ctrl-btn"
                      aria-label={muted ? t('clipTriage.unmute') : t('clipTriage.mute')}
                      aria-pressed={!muted}
                      onClick={() => setMuted((m) => !m)}
                    >
                      {muted ? <VolumeX size={14} aria-hidden /> : <Volume2 size={14} aria-hidden />}
                    </button>
                    <button
                      type="button"
                      className="triage-ctrl-btn font-mono"
                      onClick={() => setSpeedIdx((i) => (i + 1) % SPEEDS.length)}
                    >
                      {SPEEDS[speedIdx]}×
                    </button>
                  </div>
                  <span className="triage-hud-pill font-mono">
                    {formatClipTime(currentTime)} / {formatClipTime(draft.trimmed_end_s)}
                  </span>
                </div>
              </div>
            </div>

            <div className="triage-trim-strip">
              <div className="triage-trim-group">
                <span>{t('clipTriage.start')}</span>
                <button type="button" className="triage-nudge" aria-label={t('clipTriage.nudgeStartEarlier')} onClick={() => nudgeBound('start', -1)}>-1s</button>
                <button type="button" className="triage-nudge" aria-label={t('clipTriage.nudgeStartLater')} onClick={() => nudgeBound('start', 1)}>+1s</button>
              </div>
              <span className="triage-trim-window">
                {formatClipTime(draft.trimmed_start_s)}–{formatClipTime(draft.trimmed_end_s)} · {Math.round(draft.trimmed_end_s - draft.trimmed_start_s)}s
              </span>
              <div className="triage-trim-group">
                <span>{t('clipTriage.end')}</span>
                <button type="button" className="triage-nudge" aria-label={t('clipTriage.nudgeEndEarlier')} onClick={() => nudgeBound('end', -1)}>-1s</button>
                <button type="button" className="triage-nudge" aria-label={t('clipTriage.nudgeEndLater')} onClick={() => nudgeBound('end', 1)}>+1s</button>
              </div>
            </div>

            <div className="triage-kbd-bar">
              <span><span className="triage-kbd">{t('clipTriage.kbdSpace')}</span>{t('clipTriage.kbdPlay')}</span>
              <span><span className="triage-kbd">1–6</span>{t('clipTriage.kbdDiver')}</span>
              <span><span className="triage-kbd">X</span>{t('clipTriage.reject')}</span>
              <span><span className="triage-kbd">S</span>{t('clipTriage.skip')}</span>
              <span><span className="triage-kbd">{t('clipTriage.kbdEnter')}</span>{t('clipTriage.keep')}</span>
              <span><span className="triage-kbd">Z</span>{t('clipTriage.undo')}</span>
            </div>
          </section>

          {/* RIGHT: Rapid Assignment + Optional 1-Pass Full Rating */}
          <aside className="triage-panel">
            <div>
              <div className="triage-field-head">
                <span className="triage-eyebrow">{t('clipTriage.diver')}</span>
                <span className="triage-field-meta">
                  {expressMode && tab === 'pending' ? t('clipTriage.oneTapActive') : t('clipTriage.required')}
                </span>
              </div>
              <div className="triage-diver-chips">
                {quickDivers.map((d) => (
                  <button
                    key={d.id}
                    type="button"
                    className="triage-diver-chip"
                    aria-pressed={draft.diver_id === d.id}
                    onClick={() => {
                      if (expressMode && tab === 'pending') {
                        void commitKeep(d.id)
                      } else {
                        if (draft.diver_id === d.id && active.triage_status === 'kept') return
                        const nextId = draft.diver_id === d.id ? null : d.id
                        updateDraft({ diver_id: nextId }, { diver_id: nextId })
                      }
                    }}
                  >
                    <span className="triage-diver-av">{d.display_name.slice(0, 1).toUpperCase()}</span>
                    <span>{d.display_name}</span>
                  </button>
                ))}
                {divers.length > quickDivers.length && (
                  <button
                    type="button"
                    className="triage-diver-chip text-app-muted"
                    onClick={() => setShowAllDivers((v) => !v)}
                  >
                    {showAllDivers ? '−' : '+'} {t('clipTriage.otherDiver')}
                  </button>
                )}
              </div>
              {showAllDivers && (
                <select
                  aria-label={t('clipTriage.allDivers')}
                  className="app-input mt-2 w-full text-sm"
                  value={draft.diver_id ?? ''}
                  onChange={(e) => {
                    const id = e.target.value ? Number(e.target.value) : null
                    if (expressMode && id != null && tab === 'pending') {
                      void commitKeep(id)
                    } else {
                      updateDraft({ diver_id: id }, { diver_id: id })
                    }
                  }}
                >
                  {(active.triage_status !== 'kept' || draft.diver_id == null) && (
                    <option value="">{t('clipTriage.pickDiver')}</option>
                  )}
                  {divers.map((d) => (
                    <option key={d.id} value={d.id}>{d.display_name}</option>
                  ))}
                </select>
              )}
            </div>

            {/* Mobile collapsible optional section (always expanded on desktop or in incomplete tab) */}
            <button
              type="button"
              className="triage-collapse-trigger lg:hidden"
              aria-expanded={detailsOpenMobile || tab === 'incomplete'}
              onClick={() => setDetailsOpenMobile((v) => !v)}
            >
              <span>{t('clipTriage.optionalMetadata')}</span>
              {detailsOpenMobile || tab === 'incomplete' ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>

            <div className={`${detailsOpenMobile || tab === 'incomplete' ? 'flex' : 'hidden lg:flex'} flex-col gap-3.5`}>
              <div>
                <div className="triage-field-head">
                  <span className="triage-eyebrow">{t('clipTriage.codeAndHeight')}</span>
                  <span className="triage-field-meta">{t('clipTriage.optional')}</span>
                </div>
                <div className="triage-code-height">
                  <input
                    data-triage-code="true"
                    className="app-input font-mono font-semibold uppercase"
                    placeholder="103B"
                    maxLength={6}
                    aria-label={t('deposits.code')}
                    value={draft.dive_code}
                    onChange={(e) => {
                      const val = e.target.value.toUpperCase()
                      updateDraft(
                        { dive_code: val },
                        val === '' ? { dive_code: null } : CODE_RE.test(val) ? { dive_code: val } : undefined,
                      )
                    }}
                  />
                  <div className="triage-heights" role="group" aria-label={t('deposits.height')}>
                    {HEIGHTS.map((h) => (
                      <button
                        key={h}
                        type="button"
                        className="triage-seg-btn"
                        aria-pressed={draft.height === h}
                        onClick={() => {
                          const nextH = draft.height === h ? '' : h
                          updateDraft({ height: nextH }, { height: nextH || null })
                        }}
                      >
                        {h === '7.5m' ? '7.5' : h}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div>
                <div className="triage-field-head">
                  <span className="triage-eyebrow">{t('diveManagement.rating')}</span>
                  <div className="triage-mode-seg" role="group">
                    <button
                      type="button"
                      aria-pressed={!draft.phased}
                      onClick={() => updateDraft({ phased: false })}
                    >
                      {t('diveManagement.single')}
                    </button>
                    <button
                      type="button"
                      aria-pressed={draft.phased}
                      onClick={() => updateDraft({ phased: true })}
                    >
                      {t('diveManagement.phases')}
                    </button>
                  </div>
                </div>

                {!draft.phased ? (
                  <div className="triage-letters" role="group" aria-label={t('diveManagement.performance')}>
                    {LETTERS.map((l) => (
                      <button
                        key={l}
                        type="button"
                        className={`triage-letter is-${l}`}
                        aria-pressed={draft.performance === l}
                        title={performanceLabel(l)}
                        onClick={() => {
                          const next = draft.performance === l ? null : l
                          updateDraft(
                            { performance: next, phase1: null, phase2: null },
                            { performance: next, phase1_performance: null, phase2_performance: null },
                          )
                        }}
                      >
                        {l}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div>
                    <div className="triage-phase-row">
                      <span className="text-xs text-app-muted">{t('diveManagement.phase1')}</span>
                      <div className="triage-letters">
                        {LETTERS.map((l) => (
                          <button
                            key={l}
                            type="button"
                            className={`triage-letter is-${l}`}
                            aria-pressed={draft.phase1 === l}
                            onClick={() => {
                              const p2 = draft.phase2
                              updateDraft(
                                { phase1: l },
                                p2 ? { phase1_performance: l, phase2_performance: p2 } : undefined,
                              )
                            }}
                          >
                            {l}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="triage-phase-row">
                      <span className="text-xs text-app-muted">{t('diveManagement.phase2')}</span>
                      <div className="triage-letters">
                        {LETTERS.map((l) => (
                          <button
                            key={l}
                            type="button"
                            className={`triage-letter is-${l}`}
                            aria-pressed={draft.phase2 === l}
                            onClick={() => {
                              const p1 = draft.phase1
                              updateDraft(
                                { phase2: l },
                                p1 ? { phase1_performance: p1, phase2_performance: l } : undefined,
                              )
                            }}
                          >
                            {l}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                <div className="mt-1.5 flex items-center justify-between text-xs text-app-muted">
                  <span>
                    {previewScore != null ? (
                      <>
                        <strong className="text-app-text">{scoreNumber(previewScore, i18n.language)}</strong> / 10
                        {!draft.phased && draft.performance && ` · ${performanceLabel(draft.performance)}`}
                      </>
                    ) : t('clipTriage.noRatingYet')}
                  </span>
                </div>
              </div>

              <textarea
                rows={2}
                maxLength={2000}
                className="app-input w-full text-sm"
                placeholder={t('clipTriage.notePlaceholder')}
                aria-label={t('deposits.note')}
                value={draft.notes}
                onChange={(e) => updateDraft({ notes: e.target.value }, { notes: e.target.value || null })}
              />
            </div>

            {selectedDiverObj && (
              <div className="triage-deposit-bar">
                {selectedDiverObj.is_own ? (
                  <>
                    <span>{t('clipTriage.ownProfile')}</span>
                    <button
                      type="button"
                      className="font-semibold text-app-accent"
                      onClick={() => {
                        const nextVis = draft.visibility === 'public' ? 'private' : 'public'
                        updateDraft({ visibility: nextVis }, { visibility: nextVis })
                      }}
                    >
                      {draft.visibility === 'public' ? t('clipTriage.visibilityPublic') : t('clipTriage.visibilityPrivate')}
                    </button>
                  </>
                ) : (
                  <>
                    <span>{t('clipTriage.depositFor', { name: selectedDiverObj.display_name })}</span>
                    <span className="font-semibold text-app-accent">{t('clipTriage.emailHeld')}</span>
                  </>
                )}
              </div>
            )}

            <div className="triage-dock">
              <button type="button" className="triage-btn-reject" onClick={() => void commitReject()}>
                {t('clipTriage.reject')}
              </button>
              {tab === 'pending' && (
                <button type="button" className="triage-btn-skip" onClick={() => void commitSkip()}>
                  {t('clipTriage.skip')}
                </button>
              )}
              <button
                type="button"
                className="triage-btn-keep"
                disabled={draft.diver_id == null}
                onClick={() => void commitKeep()}
              >
                {tab === 'incomplete'
                  ? (isCompleteDraft ? t('clipTriage.publishNow') : t('clipTriage.saveDraft'))
                  : draft.diver_id == null
                    ? t('clipTriage.keep')
                    : isCompleteDraft
                      ? t('clipTriage.keepAndPublish')
                      : t('clipTriage.keepToCode')}
              </button>
            </div>
          </aside>
        </div>
      ) : tab === 'pending' ? (
        loading || loadingMore || hasMore ? (
          <PageLoading />
        ) : (
          <div className="app-panel py-12 text-center">
            <Sparkles className="mx-auto h-7 w-7 text-app-accent" aria-hidden />
            <h2 className="mt-3 text-lg font-semibold text-app-text">{t('clipTriage.allDoneTitle')}</h2>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {(summary?.incomplete_count ?? 0) > 0 && (
                <button type="button" onClick={() => setTab('incomplete')} className="touch-target border border-app-accent bg-app-accent px-4 text-sm font-bold text-black">
                  {t('clipTriage.openIncomplete', { count: summary?.incomplete_count })}
                </button>
              )}
              <Link to="/dives" className="touch-target inline-flex items-center border border-app bg-app-panel-elevated px-4 text-sm text-app-text">
                {t('notFound.backToLibrary')}
              </Link>
            </div>
          </div>
        )
      ) : loading ? (
        <PageLoading />
      ) : (
        <div className="triage-queue-list">
          {items.length === 0 && !hasMore ? (
            <div className="app-panel py-10 text-center text-sm text-app-muted">
              {t('clipTriage.emptyList')}
            </div>
          ) : (
            <>
              {items.map((item) => (
                <article key={item.id} className="triage-queue-row">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-app-text">
                        {item.dive_code ? <span className="font-mono">{item.dive_code} · </span> : null}
                        {item.diver_name || t('clipTriage.unassigned')}
                      </span>
                      {item.triage_status === 'rejected' && (
                        <span className="triage-pill triage-pill-red">{t('clipTriage.statusRejected')}</span>
                      )}
                      {item.triage_status === 'kept' && !item.metadata_complete && (
                        <span className="triage-pill triage-pill-amber">{t('clipTriage.statusNeedsCode')}</span>
                      )}
                      {item.extraction_status === 'queued' && (
                        <span className="triage-pill triage-pill-teal">{t('clipTriage.statusQueued')}</span>
                      )}
                      {(item.extraction_status === 'claimed' || item.extraction_status === 'extracting') && (
                        <span className="triage-pill triage-pill-teal">{t('clipTriage.statusExtracting')}</span>
                      )}
                      {item.extraction_status === 'ready' && (
                        <span className="triage-pill triage-pill-green">{t('clipTriage.statusClipReady')}</span>
                      )}
                      {item.extraction_status === 'published' && (
                        <span className="triage-pill triage-pill-green">{t('clipTriage.statusPublished')}</span>
                      )}
                      {item.extraction_status === 'failed' && (
                        <span className="triage-pill triage-pill-red">{t('clipTriage.statusFailed')}</span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-app-muted">
                      {item.session_title || item.session_date} · {formatClipTime(item.effective_start_s)}–{formatClipTime(item.effective_end_s)} ({Math.round(item.duration_s)}s)
                      {item.extraction_error ? ` · ${item.extraction_error}` : ''}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {item.dive_id != null ? (
                      <Link to={`/dives?clip=${item.dive_id}`} className="touch-target inline-flex items-center border border-app bg-app-panel-elevated px-3 text-xs font-semibold text-app-text">
                        {t('clipTriage.openDive', { id: item.dive_id })}
                      </Link>
                    ) : item.triage_status === 'kept' && (!item.metadata_complete || !item.publish_requested || item.extraction_status === 'ready') ? (
                      <button
                        type="button"
                        className="touch-target border border-app-accent px-3 text-xs font-semibold text-app-accent"
                        onClick={() => {
                          if (tab === 'incomplete') {
                            setActiveId(item.id)
                          } else {
                            setTab('incomplete', item.id)
                          }
                        }}
                      >
                        {t('clipTriage.completeNow')}
                      </button>
                    ) : item.triage_status === 'rejected' ? (
                      <button
                        type="button"
                        className="touch-target inline-flex items-center gap-1.5 border border-app px-3 text-xs text-app-muted hover:text-app-text"
                        onClick={async () => {
                          const opGen = generation.current
                          const originTab = tabRef.current
                          try {
                            await enqueueCandidateOp(item.id, () =>
                              patchClipCandidate(item.id, { triage_status: 'pending' }),
                            )
                            refreshSummary()
                            if (!mountedRef.current || opGen !== generation.current || originTab !== tabRef.current) {
                              return
                            }
                            setItems((prev) => prev.filter((it) => it.id !== item.id))
                          } catch {
                            if (mountedRef.current && opGen === generation.current) {
                              setError(t('clipTriage.saveError'))
                            }
                          }
                        }}
                      >
                        <RotateCcw size={13} aria-hidden />
                        {t('clipTriage.restore')}
                      </button>
                    ) : null}

                    {item.extraction_status === 'failed' && (
                      <button
                        type="button"
                        className="touch-target border border-app px-3 text-xs text-app-text"
                        onClick={async () => {
                          const opGen = generation.current
                          const originTab = tabRef.current
                          try {
                            const updated = await retryClipExtraction(item.id)
                            if (!mountedRef.current || opGen !== generation.current || originTab !== tabRef.current) {
                              return
                            }
                            setItems((prev) => prev.map((it) => (it.id === updated.id ? updated : it)))
                          } catch {
                            if (mountedRef.current && opGen === generation.current) {
                              setError(t('clipTriage.saveError'))
                            }
                          }
                        }}
                      >
                        {t('sessionVideo.retry')}
                      </button>
                    )}

                    <button
                      type="button"
                      className="touch-target inline-flex items-center gap-1 border border-app px-2.5 text-xs text-app-muted hover:text-app-text"
                      title={t('clipTriage.exportGt')}
                      onClick={() => void downloadVideoGroundTruth(item.session_video_id, item.video_filename).catch(() => setError(t('clipTriage.loadError')))}
                    >
                      <Download size={13} aria-hidden />
                      {t('clipTriage.exportGtShort')}
                    </button>
                  </div>
                </article>
              ))}
              {hasMore && (
                <button
                  type="button"
                  disabled={loadingMore}
                  onClick={() => void loadMoreItems()}
                  className="touch-target mx-auto border border-app bg-app-panel px-4 text-sm text-app-text"
                >
                  {t('clipTriage.loadMore')}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
