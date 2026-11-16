import {fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {beforeEach,expect,it,vi} from 'vitest'
import TechniqueAdjustments from './TechniqueAdjustments'
import '../../i18n'
const post=vi.fn(),get=vi.fn(),setup=vi.fn()
vi.mock('../../services/api',()=>({api:{post:(...args:any[])=>post(...args),get:(...args:any[])=>get(...args)}}))
vi.mock('./TechniqueSetup',()=>({default:(props:any)=>{setup(props);return <div>Adjustment setup</div>}}))
vi.mock('./TechniqueTrackChart',()=>({default:()=> <div>Adjustment ratings</div>}))
const context={code:'5132D',apparatus:'springboard',height:'1m',position:'D',sync:false}
const items=[{id:3,track_id:3,track_revision:1,label:'Earlier twist',scope:'5132D',start_at:'2026-10-07T10:00:00',end_at:null,anchor_id:1},{id:2,track_id:2,track_revision:1,label:'Less pike',scope:'5132D',start_at:'2026-09-15T10:00:00',end_at:null},{id:1,track_id:1,track_revision:2,label:'Deeper pike',scope:'5132D',start_at:'2026-04-21T10:00:00',end_at:'2026-09-15T10:00:00'}]
beforeEach(()=>{localStorage.clear();post.mockReset();get.mockReset();setup.mockClear();get.mockResolvedValue({data:{items:[{id:1,revision:2}],next:null}});post.mockResolvedValue({data:{items,revision:7,next:null}})})
it('shows simultaneous ongoing adjustments and keeps saved ends without rewriting history',async()=>{
 render(<TechniqueAdjustments diver={1} viewer={1} context={context}/>);await screen.findByText('Earlier twist')
 expect(screen.getByText('Less pike')).toBeInTheDocument()
 expect(screen.getAllByText('Ongoing')).toHaveLength(3)
 expect(screen.getByText('Ended')).toBeInTheDocument()
 expect(post.mock.calls.every(([url])=>url.endsWith('/list'))).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:/Less pike/}))
 expect(screen.getByRole('button',{name:'Stop this adjustment'})).toBeInTheDocument()
 expect(screen.getByText('Adjustment ratings')).toBeInTheDocument()
})
it('previews stopping only the selected adjustment before any write',async()=>{
 render(<TechniqueAdjustments diver={1} viewer={1} context={context}/>);await screen.findByText('Earlier twist')
 fireEvent.click(screen.getByRole('button',{name:/Earlier twist/}));fireEvent.click(screen.getByRole('button',{name:'Stop this adjustment'}))
 const dialog=await screen.findByRole('dialog');fireEvent.click(within(dialog).getByRole('button',{name:'Review change'}))
 await waitFor(()=>expect(post).toHaveBeenCalledWith('/api/v1/technique-adjustments/1/end',expect.objectContaining({episode_id:3,resume:false,commit:false,revision:7})))
 expect(post.mock.calls.filter(([url])=>url.endsWith('/end')).some(([,body])=>body.commit)).toBe(false)
 fireEvent.click(within(dialog).getByRole('button',{name:'Save'}))
 await waitFor(()=>expect(post).toHaveBeenCalledWith('/api/v1/technique-adjustments/1/end',expect.objectContaining({episode_id:3,commit:true})))
})
it('offers explicit end removal and opens the independent add flow',async()=>{
 render(<TechniqueAdjustments diver={1} viewer={1} context={context}/>);await screen.findByText('Deeper pike')
 fireEvent.click(screen.getByRole('button',{name:/Deeper pike/}))
 expect(screen.getByRole('button',{name:'Remove the end date'})).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'Add an adjustment'}));await screen.findByText('Adjustment setup')
 expect(setup.mock.lastCall?.[0].independent).toEqual(expect.objectContaining({base:'/api/v1/technique-adjustments/1',revision:7,choices:items}))
})

it('can remove two end dates consecutively and cancel or close the next dialog after reloading',async()=>{
 let saved=0
 const ended=items.map(item=>({...item,end_at:'2026-10-18T10:00:00'}))
 post.mockImplementation(async(url:string,body:any)=>{
  if(url.endsWith('/end')&&body.commit){saved++;ended.find(item=>item.id===body.episode_id)!.end_at=null as any}
  return {data:{items:ended.map(item=>({...item})),revision:7+saved,next:null}}
 })
 render(<TechniqueAdjustments diver={1} viewer={1} context={context}/>);await screen.findByText('Earlier twist')
 for(const [index,label] of ['Earlier twist','Less pike'].entries()){
  fireEvent.click(screen.getByRole('button',{name:new RegExp(label)}))
  fireEvent.click(screen.getByRole('button',{name:'Remove the end date'}))
  let dialog=await screen.findByRole('dialog')
  expect(within(dialog).getByRole('button',{name:'Cancel'})).toBeEnabled()
  fireEvent.click(within(dialog).getByRole('button',{name:'Cancel'}))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'Remove the end date'}))
  dialog=await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button',{name:'Review change'}))
  await waitFor(()=>expect(within(dialog).getByRole('button',{name:'Save'})).toBeEnabled())
  fireEvent.click(within(dialog).getByRole('button',{name:'Save'}))
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await waitFor(()=>expect(screen.getByRole('button',{name:'Add an adjustment'})).toBeEnabled())
  expect(saved).toBe(index+1)
 }
 fireEvent.click(screen.getByRole('button',{name:/Deeper pike/}))
 fireEvent.click(screen.getByRole('button',{name:'Remove the end date'}))
 fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button',{name:'Close'}))
 expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
 expect(post.mock.calls.filter(([url,body])=>url.endsWith('/end')&&body.commit).map(([,body])=>body.revision)).toEqual([7,8])
})

it('unlocks the dialog after a failed preview so it can be retried or closed',async()=>{
 render(<TechniqueAdjustments diver={1} viewer={1} context={context}/>);await screen.findByText('Deeper pike')
 fireEvent.click(screen.getByRole('button',{name:/Deeper pike/}))
 fireEvent.click(screen.getByRole('button',{name:'Remove the end date'}))
 const dialog=await screen.findByRole('dialog')
 post.mockRejectedValueOnce(new Error('Unavailable'))
 fireEvent.click(within(dialog).getByRole('button',{name:'Review change'}))
 await within(dialog).findByRole('alert')
 expect(within(dialog).getByRole('button',{name:'Review change'})).toBeEnabled()
 expect(within(dialog).getByRole('button',{name:'Cancel'})).toBeEnabled()
 fireEvent.click(within(dialog).getByRole('button',{name:'Close'}))
 expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('ignores a pending preview from the previous dive context',async()=>{
 const {rerender}=render(<TechniqueAdjustments diver={1} viewer={1} context={context}/>);await screen.findByText('Deeper pike')
 fireEvent.click(screen.getByRole('button',{name:/Deeper pike/}))
 fireEvent.click(screen.getByRole('button',{name:'Remove the end date'}))
 let resolvePreview!:(value:any)=>void
 post.mockImplementationOnce(()=>new Promise(resolve=>{resolvePreview=resolve}))
 fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button',{name:'Review change'}))
 rerender(<TechniqueAdjustments diver={1} viewer={1} context={{...context,height:'3m'}}/>)
 await waitFor(()=>expect(screen.getByRole('button',{name:'Add an adjustment'})).toBeEnabled())
 resolvePreview({data:{revision:7}})
 await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
 fireEvent.click(screen.getByRole('button',{name:/Deeper pike/}))
 fireEvent.click(screen.getByRole('button',{name:'Remove the end date'}))
 const dialog=await screen.findByRole('dialog')
 expect(within(dialog).getByRole('button',{name:'Review change'})).toBeEnabled()
 expect(within(dialog).queryByRole('button',{name:'Save'})).not.toBeInTheDocument()
})
