import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { unlockRoomAudio } from './audioUnlock'
import useRoomPreload from './useRoomPreload'
import type { Dive } from '../../services/judgeRoomApi'

afterEach(() => { vi.unstubAllGlobals() })

it('calls both persistent videos unmuted inside the gesture, then pauses primers', async () => {
  const videos = [document.createElement('video'),document.createElement('video')]
  videos.forEach(video => { video.muted=true; vi.spyOn(video,'play').mockResolvedValue(); vi.spyOn(video,'pause').mockImplementation(()=>{}) })
  const unlocked = unlockRoomAudio(videos)
  for (const video of videos) { expect(video.muted).toBe(false); expect(video.play).toHaveBeenCalledOnce() }
  expect(await unlocked).toEqual([true,true])
  videos.forEach(video => expect(video.pause).toHaveBeenCalledOnce())
})

it('fetches the entire lobby playlist with at most two concurrent downloads and revokes blobs', async () => {
  let active=0, peak=0, started=0
  const resolve:Array<()=>void>=[]
  const fetcher=vi.fn(()=>new Promise<Response>(done=>{
    active++;started++;peak=Math.max(peak,active)
    resolve.push(()=>{active--;done({ok:true,blob:async()=>new Blob(['video'])} as Response)})
  }))
  vi.stubGlobal('fetch',fetcher)
  const create=vi.fn(()=>`blob:${started}`), revoke=vi.fn()
  vi.stubGlobal('URL',Object.assign(class extends URL {},{createObjectURL:create,revokeObjectURL:revoke}))
  const dives=Array.from({length:8},(_,id)=>({id,playback_url:`/api/v1/rooms/ABCD/media/${id}/video`}) as Dive)
  const {result,unmount}=renderHook(()=>useRoomPreload('ABCD',dives))
  expect(started).toBe(2)
  for(let i=0;i<8;i++) await act(async()=>{resolve[i]()})
  await waitFor(()=>expect(Object.keys(result.current)).toHaveLength(8))
  expect(peak).toBe(2)
  expect(fetcher).toHaveBeenCalledTimes(8)
  unmount();expect(revoke).toHaveBeenCalledTimes(8)

})
